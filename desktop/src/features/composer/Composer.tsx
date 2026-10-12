import { useState, type KeyboardEvent } from "react";

interface ComposerProps {
  disabled: boolean;
  onSubmit: (prompt: string) => void;
}

export function Composer({ disabled, onSubmit }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    const clean = text.trim();
    if (!clean || disabled) return;
    onSubmit(clean);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter submits; Shift+Enter is a newline, like the TUI composer.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex items-end gap-2 bg-surface border border-edge rounded-lg p-3">
      <textarea
        className="flex-1 bg-transparent text-ink text-sm resize-none outline-none placeholder:text-ink-dim"
        placeholder="Describe the problem, then send. A pending capture is attached automatically."
        rows={2}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <button
        className="bg-accent text-canvas text-sm font-semibold rounded-md px-4 py-2 disabled:opacity-40 disabled:cursor-not-allowed"
        disabled={disabled || !text.trim()}
        onClick={submit}
      >
        Send
      </button>
    </div>
  );
}
