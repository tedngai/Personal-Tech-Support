import { useEffect, useRef, useState } from "react";
import { Composer } from "./features/composer/Composer";
import { PendingCapturePanel } from "./features/pending-capture/PendingCapturePanel";
import { WindowPicker } from "./features/pending-capture/WindowPicker";
import { Transcript } from "./features/transcript/Transcript";
import { useSidecar } from "./hooks/useSidecar";

export default function App() {
  const {
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
    notice,
  } = useSidecar();
  const [pickerOpen, setPickerOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const degraded = connection !== "online";

  return (
    <div className="h-full flex flex-col bg-canvas text-ink">
      {degraded && (
        <div className="bg-role-error/10 border-b border-role-error px-4 py-2 text-sm text-role-error">
          {connection === "connecting"
            ? "Connecting to the capture service…"
            : "Capture service unavailable — capture and sending are paused. Retrying automatically."}
        </div>
      )}

      <header className="flex items-center gap-3 px-4 py-2 border-b border-edge text-sm text-ink-dim">
        <span className="font-semibold text-ink">Pratt Lab Guide</span>
        {hello && <span>model {hello.config.model}</span>}
        {hello && (
          <span className={hello.config.ui_enabled ? "text-role-assistant" : ""}>
            {hello.config.ui_enabled ? "UI context on" : "UI context off"}
          </span>
        )}
        {hello && hello.capabilities.global_hotkey && (
          <span className="text-role-capture">hotkey: {hello.config.global_hotkey}</span>
        )}
        <span className={`ml-auto ${degraded ? "text-role-error" : "text-role-assistant"}`}>
          {connection === "connecting" ? "connecting" : degraded ? "offline" : "online"}
        </span>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
        <Transcript messages={messages} />
      </div>

      {pickerOpen && (
        <WindowPicker
          onCaptured={() => void refreshPending()}
          onClose={() => setPickerOpen(false)}
          onNotice={(role, message) => notice(role, message)}
        />
      )}

      <div className="p-4 pt-0 flex flex-col gap-3">
        <PendingCapturePanel attachment={pending} disabled={inFlight} onDiscard={() => void discard()} />
        <div className="flex gap-2">
          <button
            className="bg-role-capture text-canvas text-sm font-semibold rounded-md px-4 py-2 disabled:opacity-40 disabled:cursor-not-allowed"
            disabled={degraded || inFlight}
            onClick={() => setPickerOpen(true)}
          >
            Capture window…
          </button>
          <button
            className="bg-surface border border-edge text-ink text-sm rounded-md px-4 py-2 hover:bg-edge disabled:opacity-40 disabled:cursor-not-allowed"
            disabled={degraded || inFlight}
            onClick={() => void captureWindow()}
          >
            Capture screen
          </button>
          <button
            className="border border-edge text-ink-dim text-sm rounded-md px-3 py-2 hover:bg-surface disabled:opacity-40"
            disabled={degraded}
            onClick={() => void resetConversation()}
          >
            Clear conversation
          </button>
        </div>
        <Composer disabled={degraded || inFlight} onSubmit={(prompt) => void submitPrompt(prompt)} />
      </div>
    </div>
  );
}
