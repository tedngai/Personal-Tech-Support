/**
 * Typed client for the LabGuide sidecar's JSON-RPC stdio channel.
 *
 * The only transport the webview has is the `sidecar_send` Tauri command
 * (one JSON-RPC line per call) and `sidecar-line` events (the sidecar's
 * stdout, forwarded by the shell). This module layers request/response
 * correlation and event subscription on top of that pipe.
 *
 * Contract shapes come from ./types; golden fixtures under ./fixtures are
 * generated from the Python service and keep the two sides honest.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { IpcErrorInfo } from "./types";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: IpcErrorInfo) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class SidecarClient {
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private readonly eventListeners = new Set<(name: string, data: unknown) => void>();
  private unlistenLine: UnlistenFn | null = null;
  private unlistenShell: UnlistenFn | null = null;
  private attached = false;

  constructor(
    private readonly sendLine: (line: string) => void | Promise<void> = (line) =>
      invoke("sidecar_send", { line }),
  ) {}

  /** Begin consuming `sidecar-line` and `sidecar-event` events. Idempotent. */
  async attach(): Promise<void> {
    if (this.attached) return;
    this.unlistenLine = await listen<string>("sidecar-line", (event) => {
      this.handleLine(event.payload);
    });
    // Shell diagnostics (spawn failures, terminations, sidecar stderr).
    // Dispatched under a reserved name so consumers can distinguish them
    // from sidecar protocol events.
    this.unlistenShell = await listen<unknown>("sidecar-event", (event) => {
      this.dispatch("shell.event", event.payload);
    });
    this.attached = true;
  }

  detach(): void {
    this.unlistenLine?.();
    this.unlistenLine = null;
    this.unlistenShell?.();
    this.unlistenShell = null;
    this.attached = false;
    // Stale listeners must not survive a detach: a second mount would then
    // receive every event twice (observed as duplicated transcript lines).
    this.eventListeners.clear();
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject({ code: -32603, message: "sidecar client detached" });
    }
    this.pending.clear();
  }

  /**
   * Send one request and await its response. Bounded by timeoutMs; a
   * timeout rejects with the sidecar's TIMED_OUT shape (the server enforces
   * its own deadline too — this is the UI-side guard so the UI never wedges).
   */
  request<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 45000): Promise<T> {
    const id = this.nextId++;
    const line = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject({ code: -32005, message: `request timed out after ${timeoutMs}ms`, stage: method });
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      });
      try {
        void Promise.resolve(this.sendLine(line)).catch((err: unknown) => {
          clearTimeout(timer);
          if (this.pending.delete(id)) {
            reject({ code: -32603, message: String(err), stage: method });
          }
        });
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject({ code: -32603, message: String(err), stage: method });
      }
    });
  }

  /** Subscribe to sidecar-initiated events. Returns an unsubscribe function. */
  onEvent(listener: (name: string, data: unknown) => void): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Handle one raw transport line. Public so tests (and golden fixtures)
   * can drive the client without a running sidecar.
   */
  handleLine(line: string): void {
    let payload: unknown;
    try {
      payload = JSON.parse(line);
    } catch {
      // A non-JSON line on the protocol channel is a sidecar bug; surface
      // it as an error event rather than crashing the UI.
      this.dispatch("degraded", { reason: "protocol", message: "unparsable sidecar output" });
      return;
    }
    if (!isRecord(payload)) return;

    if ("event" in payload) {
      const name = payload["event"];
      if (typeof name === "string") {
        this.dispatch(name, isRecord(payload["data"]) ? payload["data"] : {});
      }
      return;
    }

    if ("id" in payload) {
      const id = payload["id"];
      if (typeof id !== "number" || !this.pending.has(id)) return;
      const pending = this.pending.get(id)!;
      clearTimeout(pending.timer);
      this.pending.delete(id);
      if ("result" in payload) {
        pending.resolve(payload["result"]);
      } else if (isRecord(payload["error"])) {
        const error = payload["error"];
        const data = isRecord(error["data"]) ? error["data"] : undefined;
        pending.reject({
          code: typeof error["code"] === "number" ? error["code"] : -32603,
          message: typeof error["message"] === "string" ? error["message"] : "unknown error",
          stage: typeof data?.["stage"] === "string" ? data["stage"] : undefined,
          category: typeof data?.["category"] === "string" ? data["category"] : undefined,
        });
      } else {
        pending.reject({ code: -32603, message: "malformed response" });
      }
    }
  }

  private dispatch(name: string, data: unknown): void {
    for (const listener of this.eventListeners) {
      try {
        listener(name, data);
      } catch (err) {
        console.error("sidecar event listener failed", err);
      }
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Singleton for the app runtime; tests construct their own instances. */
export const sidecar = new SidecarClient();
