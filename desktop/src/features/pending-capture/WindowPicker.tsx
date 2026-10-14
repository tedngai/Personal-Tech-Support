import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { sidecar } from "../../ipc/client";
import type { CaptureStartResult, IpcErrorInfo, WindowChoice } from "../../ipc/types";
import { formatIpcError } from "../../hooks/useSidecar";

interface WindowPickerProps {
  onCaptured: () => void;
  onClose: () => void;
  onNotice: (role: "capture", message: string) => void;
}

const HIDE_SETTLE_MS = 250;

/**
 * Thumbnail grid of capturable windows. Errors stay in this panel so the
 * user is never stranded in the picker while the message lands behind it.
 * Capture does not hide or restack windows in the common case; PrintWindow
 * reads the target's own pixels when the OS allows it. When that fails and
 * the capture falls back to a desktop crop, LabGuide hides itself for the
 * retry so its own window is not painted over the target in the shot.
 */
export function WindowPicker({ onCaptured, onClose, onNotice }: WindowPickerProps) {
  const [windows, setWindows] = useState<WindowChoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    sidecar
      .request<{ windows: WindowChoice[] }>("windows.list", {}, 20000)
      .then((result) => {
        if (!cancelled) setWindows(result.windows);
      })
      .catch((err: IpcErrorInfo) => {
        if (!cancelled) setError(`Could not list windows: ${formatIpcError(err)}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const capture = async (choice: WindowChoice) => {
    setBusyId(choice.id);
    setError(null);
    try {
      const params = { mode: "window", hwnd: choice.id };
      let result = await sidecar.request<CaptureStartResult>("capture.start", params);
      if (result.capture.warnings?.length) {
        // Desktop-crop fallback: LabGuide's own window (and this panel) may
        // be painted over the target in the region crop. Hide, recapture,
        // and always restore the app.
        await invoke("set_window_visible", { visible: false });
        try {
          await new Promise((resolve) => setTimeout(resolve, HIDE_SETTLE_MS));
          result = await sidecar.request<CaptureStartResult>("capture.start", params);
        } finally {
          await invoke("set_window_visible", { visible: true }).catch(() => {
            // Showing the window must never strand the user without the app.
          });
        }
      }
      const warning = result.capture.warnings?.[0];
      onNotice(
        "capture",
        warning
          ? `Captured ${choice.process_name} "${choice.title}". ${warning}`
          : `Captured ${choice.process_name} "${choice.title}".`,
      );
      onCaptured();
      onClose();
    } catch (err) {
      setError(formatIpcError(err));
      setBusyId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-canvas/70 p-6">
      <div className="bg-surface border border-edge rounded-lg shadow-xl w-full max-w-3xl">
        <div className="flex items-center px-4 py-3 border-b border-edge">
          <h2 className="text-sm font-semibold text-ink">Capture which window?</h2>
          <button className="ml-auto text-ink-dim hover:text-ink text-sm" onClick={onClose}>
            Cancel
          </button>
        </div>
        {error && (
          <div className="mx-4 mt-3 rounded-md border border-role-error bg-role-error/10 px-3 py-2 text-sm text-role-error">
            {error}
          </div>
        )}
        <div className="max-h-[70vh] overflow-y-auto p-4">
          {windows === null && !error && (
            <div className="py-10 text-sm text-ink-dim text-center">Loading windows…</div>
          )}
          {windows !== null && windows.length === 0 && (
            <div className="py-10 text-sm text-ink-dim text-center">
              No other capturable windows found. Minimized windows are omitted.
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {windows?.map((choice) => (
              <button
                key={choice.id}
                className="text-left rounded-md border border-edge bg-canvas hover:border-accent disabled:opacity-40 overflow-hidden"
                disabled={busyId !== null}
                onClick={() => void capture(choice)}
              >
                <div className="h-28 bg-edge flex items-center justify-center">
                  {choice.thumbnail_base64 ? (
                    <img
                      className="max-h-28 w-full object-contain"
                      src={`data:image/jpeg;base64,${choice.thumbnail_base64}`}
                      alt=""
                    />
                  ) : (
                    <span className="text-xs text-ink-dim px-2 text-center">No preview</span>
                  )}
                </div>
                <div className="px-2 py-2">
                  <div className="text-sm text-ink truncate">{choice.title}</div>
                  <div className="text-xs text-ink-dim truncate">{choice.process_name}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
