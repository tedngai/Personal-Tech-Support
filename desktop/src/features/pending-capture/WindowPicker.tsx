import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { WindowChoice } from "../../ipc/types";
import type { IpcErrorInfo } from "../../ipc/types";
import { sidecar } from "../../ipc/client";
import type { CaptureStartResult } from "../../ipc/types";
import { formatIpcError } from "../../hooks/useSidecar";

interface WindowPickerProps {
  onCaptureStarted: () => void;
  onClose: () => void;
  onNotice: (role: "error" | "system" | "capture", message: string) => void;
}

const HIDE_SETTLE_MS = 250;

/**
 * Lets the user pick which window to capture instead of guessing from
 * z-order. While the capture runs, LabGuide's own window is hidden so it
 * cannot occlude the target (the Windows adapter crops the desktop region).
 */
export function WindowPicker({ onCaptureStarted, onClose, onNotice }: WindowPickerProps) {
  const [windows, setWindows] = useState<WindowChoice[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    sidecar
      .request<{ windows: WindowChoice[] }>("windows.list", {}, 15000)
      .then((result) => {
        if (!cancelled) setWindows(result.windows);
      })
      .catch((err: IpcErrorInfo) => {
        if (!cancelled) onNotice("error", `Could not list windows: ${formatIpcError(err)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [onNotice]);

  const capture = async (choice: WindowChoice) => {
    setBusyId(choice.id);
    let hidden = false;
    try {
      await invoke("set_window_visible", { visible: false });
      hidden = true;
      await new Promise((resolve) => setTimeout(resolve, HIDE_SETTLE_MS));
      const result = await sidecar.request<CaptureStartResult>(
        "capture.start",
        { mode: "window", hwnd: choice.id },
      );
      onCaptureStarted();
      onNotice(
        "capture",
        `Captured ${choice.process_name} "${choice.title}" — ${result.capture.width}x${result.capture.height}.`,
      );
    } catch (err) {
      onNotice("error", `Capture failed: ${formatIpcError(err)}`);
    } finally {
      if (hidden) {
        try {
          await invoke("set_window_visible", { visible: true });
        } catch {
          // Showing the window must never strand the user without the app.
        }
      }
      setBusyId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-canvas/70 p-6">
      <div className="bg-surface border border-edge rounded-lg shadow-xl w-full max-w-md">
        <div className="flex items-center px-4 py-3 border-b border-edge">
          <h2 className="text-sm font-semibold text-ink">Capture which window?</h2>
          <button
            className="ml-auto text-ink-dim hover:text-ink text-sm"
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {windows === null && (
            <div className="px-3 py-6 text-sm text-ink-dim text-center">Loading windows…</div>
          )}
          {windows !== null && windows.length === 0 && (
            <div className="px-3 py-6 text-sm text-ink-dim text-center">
              No other capturable windows found.
            </div>
          )}
          {windows?.map((choice) => (
            <button
              key={choice.id}
              className="w-full text-left px-3 py-2 rounded-md hover:bg-edge disabled:opacity-40"
              disabled={busyId !== null}
              onClick={() => void capture(choice)}
            >
              <div className="text-sm text-ink truncate">{choice.title}</div>
              <div className="text-xs text-ink-dim">{choice.process_name}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
