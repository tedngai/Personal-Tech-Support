//! LabGuide desktop shell glue.
//!
//! The Rust layer owns exactly three things: spawning the Python sidecar,
//! supervising it (respawn with backoff), and shuttling JSON-RPC lines
//! between the webview and the sidecar's stdio. No product logic lives
//! here; see docs/Desktop-App-Migration-Plan.md.
//!
//! The webview never gets shell access: it can only invoke `sidecar_send`
//! and listen for `sidecar-line` / `sidecar-event` emissions.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::json;
use tauri::{Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Delay before respawning a dead sidecar. Fixed for now; a backoff
/// sequence can replace it if flapping shows up in the field.
const RESPAWN_DELAY: Duration = Duration::from_millis(1500);

struct SidecarState {
    child: Mutex<Option<CommandChild>>,
    shutting_down: AtomicBool,
}

/// Spawn the sidecar and forward its output to the webview.
///
/// Runs from the setup hook and again from the supervision thread after a
/// termination, so it must tolerate being called concurrently.
fn spawn_supervised(app: tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    if state.shutting_down.load(Ordering::Relaxed) {
        return;
    }

    let spawn_result = app
        .shell()
        .sidecar("labguide-sidecar")
        .and_then(|command| command.spawn());
    let (mut receiver, child) = match spawn_result {
        Ok(pair) => pair,
        Err(err) => {
            let _ = app.emit(
                "sidecar-event",
                json!({"kind": "spawn-failed", "message": err.to_string()}),
            );
            schedule_respawn(app);
            return;
        }
    };
    *state.child.lock().expect("sidecar state poisoned") = Some(child);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let _ = app.emit("sidecar-line", String::from_utf8_lossy(&line).to_string());
                }
                // Diagnostics channel only (the service never logs captured
                // content to stderr). Surfaced for the degraded-state banner.
                CommandEvent::Stderr(line) => {
                    let _ = app.emit(
                        "sidecar-event",
                        json!({"kind": "stderr", "message": String::from_utf8_lossy(&line)}),
                    );
                }
                CommandEvent::Error(err) => {
                    let _ = app.emit(
                        "sidecar-event",
                        json!({"kind": "error", "message": err.to_string()}),
                    );
                }
                CommandEvent::Terminated(status) => {
                    let state = app.state::<SidecarState>();
                    *state.child.lock().expect("sidecar state poisoned") = None;
                    if state.shutting_down.load(Ordering::Relaxed) {
                        return;
                    }
                    let _ = app.emit(
                        "sidecar-event",
                        json!({"kind": "terminated", "code": status.code}),
                    );
                    schedule_respawn(app);
                    return;
                }
                _ => {}
            }
        }
    });
}

fn schedule_respawn(app: tauri::AppHandle) {
    if app.state::<SidecarState>().shutting_down.load(Ordering::Relaxed) {
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
    let child = state.child.lock().expect("sidecar state poisoned").take();
    if let Some(mut child) = child {
        // Shutdown is a request, not a kill (AX-wedge finding): ask the
        // service to stop, give it a moment to drain, then force.
        let request = json!({"jsonrpc": "2.0", "id": -1, "method": "shutdown"}).to_string();
        let _ = child.write(format!("{request}\n").as_bytes());
        std::thread::sleep(Duration::from_millis(500));
        let _ = child.kill();
    }
}

/// Send one JSON-RPC line to the sidecar. The webview's only write path.
#[tauri::command]
fn sidecar_send(state: State<'_, SidecarState>, line: String) -> Result<(), String> {
    let mut guard = state.child.lock().expect("sidecar state poisoned");
    match guard.as_mut() {
        Some(child) => child.write(line.as_bytes()).map_err(|err| err.to_string()),
        None => Err("sidecar not running".into()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            app.manage(SidecarState {
                child: Mutex::new(None),
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
