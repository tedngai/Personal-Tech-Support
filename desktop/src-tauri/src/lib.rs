//! LabGuide desktop shell glue.
//!
//! The Rust layer owns exactly three things: spawning the Python sidecar,
//! supervising it (respawn with backoff), and shuttling JSON-RPC lines
//! between the webview and the sidecar's stdio. No product logic lives
//! here; see docs/Desktop-App-Migration-Plan.md.
//!
//! The sidecar is spawned with std::process directly (not
//! tauri-plugin-shell): the plugin's pipe-reader path dropped events in
//! practice, and direct stdio gives bounded, debuggable forwarding.
//!
//! The webview never gets shell access: it can only invoke `sidecar_send`
//! and listen for `sidecar-line` / `sidecar-event` emissions.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::json;
use tauri::{Emitter, Manager, RunEvent, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// Delay before respawning a dead sidecar. Fixed for now; a backoff
/// sequence can replace it if flapping shows up in the field.
const RESPAWN_DELAY: Duration = Duration::from_millis(1500);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct SidecarState {
    /// The child's stdin. The Child itself lives in the watcher thread,
    /// which reaps it; a dead pipe surfaces as a write error in
    /// `sidecar_send` and as a terminated event from the watcher.
    stdin: Mutex<Option<ChildStdin>>,
    shutting_down: AtomicBool,
}

fn sidecar_path() -> Result<PathBuf, String> {
    // Dev: target/debug/. Bundled: install dir, next to the main exe —
    // both match where the CLI/bundler places externalBin binaries.
    let exe = std::env::current_exe().map_err(|err| err.to_string())?;
    let dir = exe.parent().ok_or("executable has no parent directory")?;
    #[cfg(windows)]
    let path = dir.join("labguide-sidecar.exe");
    #[cfg(not(windows))]
    let path = dir.join("labguide-sidecar");
    Ok(path)
}

fn spawn_supervised(app: tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    if state.shutting_down.load(Ordering::Relaxed) {
        return;
    }

    let path = match sidecar_path() {
        Ok(path) => path,
        Err(err) => {
            eprintln!("sidecar: could not resolve path: {err}");
            let _ = app.emit(
                "sidecar-event",
                json!({"kind": "spawn-failed", "message": err}),
            );
            schedule_respawn(app);
            return;
        }
    };

    let mut command = Command::new(&path);
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(err) => {
            eprintln!("sidecar: spawn failed ({path:?}): {err}");
            let _ = app.emit(
                "sidecar-event",
                json!({"kind": "spawn-failed", "message": err.to_string()}),
            );
            schedule_respawn(app);
            return;
        }
    };

    let stdout = child.stdout.take().expect("stdout was piped");
    let stderr = child.stderr.take().expect("stderr was piped");
    let stdin = child.stdin.take().expect("stdin was piped");
    *state.stdin.lock().expect("sidecar state poisoned") = Some(stdin);
    eprintln!("sidecar: spawned ({})", path.display());

    // stdout → sidecar-line. Plain blocking thread; lines are short JSON-RPC
    // messages, so line buffering costs nothing and keeps ordering.
    let forward_app = app.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(line) => {
                    let _ = forward_app.emit("sidecar-line", line);
                }
                Err(err) => {
                    eprintln!("sidecar: stdout read error: {err}");
                    return;
                }
            }
        }
    });

    // stderr → sidecar-event (diagnostics only; the service never logs
    // captured content to stderr).
    let forward_app = app.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            match line {
                Ok(line) => {
                    if line.trim().is_empty() {
                        continue;
                    }
                    let _ = forward_app.emit(
                        "sidecar-event",
                        json!({"kind": "stderr", "message": line}),
                    );
                }
                Err(_) => return,
            }
        }
    });

    // Watcher: own the Child, reap it, emit terminated, respawn.
    let watcher_app = app.clone();
    std::thread::spawn(move || {
        let status = child.wait();
        *watcher_app
            .state::<SidecarState>()
            .stdin
            .lock()
            .expect("sidecar state poisoned") = None;
        if watcher_app
            .state::<SidecarState>()
            .shutting_down
            .load(Ordering::Relaxed)
        {
            return;
        }
        match status {
            Ok(status) => {
                eprintln!(
                    "sidecar: exited (code {:?}); respawning in {RESPAWN_DELAY:?}",
                    status.code()
                );
                let _ = watcher_app.emit(
                    "sidecar-event",
                    json!({"kind": "terminated", "code": status.code()}),
                );
            }
            Err(err) => {
                eprintln!("sidecar: wait failed: {err}");
                let _ = watcher_app.emit(
                    "sidecar-event",
                    json!({"kind": "error", "message": err.to_string()}),
                );
            }
        }
        schedule_respawn(watcher_app);
    });
}

fn schedule_respawn(app: tauri::AppHandle) {
    if app
        .state::<SidecarState>()
        .shutting_down
        .load(Ordering::Relaxed)
    {
        return;
    }
    std::thread::spawn(move || {
        std::thread::sleep(RESPAWN_DELAY);
        spawn_supervised(app);
    });
}

fn graceful_shutdown(app: &tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    state.shutting_down.store(true, Ordering::Relaxed);
    let stdin = state
        .stdin
        .lock()
        .expect("sidecar state poisoned")
        .take();
    if let Some(mut stdin) = stdin {
        // Shutdown is a request, not a kill (AX-wedge finding): ask the
        // service to stop, give it a moment to drain, then close stdin so
        // the reader loop sees EOF and exits.
        let request = json!({"jsonrpc": "2.0", "id": -1, "method": "shutdown"}).to_string();
        let _ = stdin.write_all(format!("{request}\n").as_bytes());
        let _ = stdin.flush();
        std::thread::sleep(Duration::from_millis(500));
        drop(stdin);
        std::thread::sleep(Duration::from_millis(500));
    }
}

/// Send one JSON-RPC line to the sidecar. The webview's only write path.
#[tauri::command]
fn sidecar_send(state: State<'_, SidecarState>, line: String) -> Result<(), String> {
    let mut guard = state.stdin.lock().expect("sidecar state poisoned");
    match guard.as_mut() {
        Some(stdin) => stdin
            .write_all(line.as_bytes())
            .and_then(|_| stdin.write_all(b"\n"))
            .and_then(|_| stdin.flush())
            .map_err(|err| err.to_string()),
        None => Err("sidecar not running".into()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            app.manage(SidecarState {
                stdin: Mutex::new(None),
                shutting_down: AtomicBool::new(false),
            });
            spawn_supervised(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar_send])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                graceful_shutdown(app_handle);
            }
        });
}
