import { useCallback, useEffect, useRef, useState } from "react";
import { sidecar } from "../ipc/client";
import type {
  Attachment,
  AttachmentGetResult,
  CaptureCompletedEvent,
  CaptureFailedEvent,
  CaptureStartResult,
  DegradedEvent,
  DiscardResult,
  HelloResult,
  SubmitResult,
} from "../ipc/types";

export type Role = "user" | "assistant" | "system" | "error" | "capture";

export interface Message {
  id: number;
  role: Role;
  content: string;
}

export type ConnectionState = "connecting" | "online" | "degraded";

export function formatIpcError(err: unknown): string {
  if (typeof err === "object" && err !== null && "message" in err) {
    const info = err as { code?: number; message: string; stage?: string; category?: string };
    const where = info.stage ? ` (${info.stage})` : "";
    return `${info.message}${where}`;
  }
  return String(err);
}

/**
 * Owns the UI mirror of the sidecar's state: transcript, pending
 * attachment, connection health. The sidecar remains the source of truth;
 * this hook only reflects it. Invariants enforced here mirror the
 * sidecar's: a successful send clears the pending attachment, errors
 * retain it, and only explicit user actions trigger capture or submit.
 */
export function useSidecar() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<Attachment | null>(null);
  const [hello, setHello] = useState<HelloResult | null>(null);
  const [connection, setConnectionState] = useState<ConnectionState>("connecting");
  const [inFlight, setInFlight] = useState(false);
  const nextId = useRef(1);
  const connectionRef = useRef<ConnectionState>("connecting");

  const setConnection = useCallback((state: ConnectionState) => {
    connectionRef.current = state;
    setConnectionState(state);
  }, []);

  const append = useCallback((role: Role, content: string) => {
    setMessages((previous) => [
      ...previous,
      { id: nextId.current++, role, content },
    ]);
  }, []);

  useEffect(() => {
    let disposed = false;
    let stopped = false;
    let offEvent: (() => void) | null = null;

    void (async () => {
      const client = sidecar;
      try {
        await client.attach();
      } catch {
        // In the webview, attach only fails if the event API is absent.
        if (!disposed) setConnection("degraded");
        return;
      }

      offEvent = client.onEvent((name, data) => {
        if (disposed) return;
        if (name === "capture.completed") {
          const event = data as CaptureCompletedEvent;
          void (async () => {
            try {
              const result = await client.request<AttachmentGetResult>(
                "attachment.get",
                {},
                15000,
              );
              if (disposed) return;
              setConnection("online");
              setPending(result.attachment);
              append("capture", describeCapture(event.capture));
            } catch (err) {
              if (!disposed) append("error", `Attachment unavailable: ${formatIpcError(err)}`);
            }
          })();
        } else if (name === "capture.failed") {
          append("error", (data as CaptureFailedEvent).message);
        } else if (name === "capture.ignored") {
          append("system", (data as CaptureFailedEvent).message);
        } else if (name === "hotkey.pressed") {
          append("system", "Capture hotkey pressed.");
        } else if (name === "degraded") {
          const event = data as DegradedEvent;
          append("system", event.message);
        } else if (name === "shell.event") {
          // Diagnostics from the Rust shell: spawn failures, terminations,
          // sidecar stderr. These explain WHY the sidecar is unreachable.
          const shell = data as { kind: string; message?: string; code?: number | null };
          if (shell.kind === "spawn-failed") {
            setConnection("degraded");
            append("error", `Sidecar spawn failed: ${shell.message ?? "unknown error"}`);
          } else if (shell.kind === "terminated") {
            setConnection("degraded");
            append("system", `Sidecar exited (code ${shell.code ?? "?"}); restarting…`);
          } else if (shell.kind === "stderr" && shell.message?.trim()) {
            append("system", `Sidecar: ${shell.message.trim()}`);
          } else if (shell.kind === "error") {
            append("error", `Sidecar stream error: ${shell.message ?? "unknown"}`);
          }
        }
      });

      // Watchdog: try hello immediately, then keep retrying while degraded
      // so a slow sidecar start (PyInstaller extraction) or a respawn
      // recovers without user action.
      const attemptHello = async (): Promise<boolean> => {
        try {
          const helloResult = await client.request<HelloResult>("hello", {}, 30000);
          if (disposed) return true;
          const wasOffline = connectionRef.current !== "online";
          setHello(helloResult);
          setConnection("online");
          if (wasOffline) {
            append(
              "system",
              `Sidecar online (${helloResult.adapter}) · model ${helloResult.config.model}`,
            );
          }
          return true;
        } catch (err) {
          if (disposed) return true;
          if (connectionRef.current === "connecting") {
            // First attempt failed: say so, then retry quietly.
            append("error", `Sidecar unavailable: ${formatIpcError(err)}`);
          }
          setConnection("degraded");
          return false;
        }
      };

      const runWatchdog = async () => {
        for (;;) {
          if (disposed || stopped) return;
          const online = await attemptHello();
          if (online || disposed || stopped) return;
          await new Promise((resolve) => setTimeout(resolve, 3000));
        }
      };
      void runWatchdog();
    })();

    return () => {
      disposed = true;
      stopped = true;
      offEvent?.();
      sidecar.detach();
    };
  }, [append, setConnection]);

  const captureWindow = useCallback(async () => {
    try {
      const result = await sidecar.request<CaptureStartResult>("capture.start", { mode: "below" });
      setConnection("online");
      // Pull the payload the sidecar just stored; events also refresh this.
      const attachment = await sidecar.request<AttachmentGetResult>("attachment.get", {}, 15000);
      setPending(attachment.attachment);
      append("capture", describeCapture(result.capture));
    } catch (err) {
      // The sidecar retains the previous pending capture on failure.
      append("error", `Capture failed: ${formatIpcError(err)} — previous capture kept.`);
    }
  }, [append]);

  const submitPrompt = useCallback(
    async (prompt: string) => {
      const clean = prompt.trim();
      if (!clean) return;
      append("user", clean);
      setInFlight(true);
      try {
        const result = await sidecar.request<SubmitResult>("submit", { prompt: clean });
        setConnection("online");
        append("assistant", result.answer);
        // Cleared only after a successful send; the sidecar cleared its
        // copy of the same capture.
        setPending(null);
      } catch (err) {
        append("error", formatIpcError(err));
      } finally {
        setInFlight(false);
      }
    },
    [append],
  );

  const discard = useCallback(async () => {
    try {
      const result = await sidecar.request<DiscardResult>("discard");
      setPending(null);
      append(
        "system",
        result.discarded ? "Pending capture discarded." : "No pending capture to discard.",
      );
    } catch (err) {
      append("error", formatIpcError(err));
    }
  }, [append]);

  const resetConversation = useCallback(async () => {
    try {
      await sidecar.request("conversation.reset");
      setMessages([]);
    } catch (err) {
      append("error", formatIpcError(err));
    }
  }, [append]);

  const refreshPending = useCallback(async () => {
    try {
      const result = await sidecar.request<AttachmentGetResult>("attachment.get", {}, 15000);
      setPending(result.attachment);
    } catch (err) {
      append("error", `Attachment unavailable: ${formatIpcError(err)}`);
    }
  }, [append]);

  return {
    messages,
    pending,
    hello,
    connection,
    inFlight,
    captureWindow,
    refreshPending,
    submitPrompt,
    discard,
    resetConversation,
    notice: append,
  };
}

function describeCapture(capture: {
  byte_count: number;
  width: number;
  height: number;
  target: { process_name: string; window_title: string } | null;
  ui: { status: string; element_count: number; truncated: boolean } | null;
}): string {
  const parts = [
    `Captured ${
      capture.target ? `${capture.target.process_name} "${capture.target.window_title}"` : "screen"
    }`,
    `${capture.width}x${capture.height}`,
    `${Math.round(capture.byte_count / 1024)}KB`,
  ];
  if (capture.ui && ["complete", "partial"].includes(capture.ui.status)) {
    parts.push(`${capture.ui.element_count} UI elements${capture.ui.truncated ? ", truncated" : ""}`);
  } else if (capture.ui) {
    parts.push(`UI text ${capture.ui.status} (screenshot only)`);
  } else {
    parts.push("screenshot only");
  }
  return `${parts[0]} (${parts.slice(1).join(", ")})`;
}
