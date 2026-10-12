import Markdown from "react-markdown";
import type { Message } from "../../hooks/useSidecar";

/**
 * Role-coded transcript entry. Assistant answers render as markdown;
 * every other role renders as plain text — captured UI content and system
 * messages are untrusted observed data and are never interpreted.
 */

// Literal class strings only, so Tailwind's scanner keeps every role token.
const ROLE_STYLES: Record<Message["role"], { bar: string; label: string }> = {
  user: { bar: "border-l-role-user", label: "text-role-user" },
  assistant: { bar: "border-l-role-assistant", label: "text-role-assistant" },
  system: { bar: "border-l-role-system", label: "text-role-system" },
  error: { bar: "border-l-role-error", label: "text-role-error" },
  capture: { bar: "border-l-role-capture", label: "text-role-capture" },
};

const ROLE_LABELS: Record<Message["role"], string> = {
  user: "You",
  assistant: "LabGuide",
  system: "System",
  error: "Error",
  capture: "Capture",
};

export function TranscriptMessage({ message }: { message: Message }) {
  const style = ROLE_STYLES[message.role];
  return (
    <div className={`border-l-4 ${style.bar} bg-surface rounded-r-md px-4 py-3`}>
      <div className={`text-xs font-semibold uppercase tracking-wide mb-1 ${style.label}`}>
        {ROLE_LABELS[message.role]}
      </div>
      {message.role === "assistant" ? (
        <div className="prose-invert text-ink text-sm leading-relaxed [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_code]:bg-edge [&_code]:px-1 [&_code]:rounded">
          <Markdown>{message.content}</Markdown>
        </div>
      ) : (
        <div className="text-ink text-sm whitespace-pre-wrap break-words">{message.content}</div>
      )}
    </div>
  );
}

export function Transcript({ messages }: { messages: Message[] }) {
  return (
    <div className="flex flex-col gap-3">
      {messages.map((message) => (
        <TranscriptMessage key={message.id} message={message} />
      ))}
    </div>
  );
}
