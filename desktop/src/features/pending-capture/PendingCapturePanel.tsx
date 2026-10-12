import type { Attachment } from "../../ipc/types";

interface PendingCapturePanelProps {
  attachment: Attachment | null;
  disabled: boolean;
  onDiscard: () => void;
}

/** Local pending attachment. Nothing is sent until the composer submits. */
export function PendingCapturePanel({ attachment, disabled, onDiscard }: PendingCapturePanelProps) {
  if (!attachment) return null;
  return (
    <div className="bg-surface border border-edge rounded-lg p-3 flex items-center gap-3">
      <img
        className="max-h-24 rounded border border-edge"
        src={`data:image/jpeg;base64,${attachment.image_base64}`}
        alt="Pending capture preview"
      />
      <div className="flex-1 text-sm text-ink-dim">
        <div className="text-ink">
          {attachment.target
            ? `${attachment.target.process_name} — ${attachment.target.window_title}`
            : "Screen capture"}
        </div>
        <div>
          {attachment.width}x{attachment.height} ·{" "}
          {Math.round(attachment.byte_count / 1024)}KB
          {attachment.ui && ["complete", "partial"].includes(attachment.ui.status)
            ? ` · ${attachment.ui.element_count} UI elements`
            : " · screenshot only"}
        </div>
      </div>
      <button
        className="text-role-error text-sm border border-edge rounded-md px-3 py-1.5 hover:bg-edge disabled:opacity-40"
        disabled={disabled}
        onClick={onDiscard}
      >
        Discard
      </button>
    </div>
  );
}
