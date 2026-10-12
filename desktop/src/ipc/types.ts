/**
 * Types mirroring the Python sidecar's IPC payloads (src/labguide/ipc.py and
 * src/labguide/service/server.py). Golden fixtures under ./fixtures are
 * generated from the Python service contract tests — see
 * scripts/generate_ipc_fixtures.py — and validate these shapes in vitest.
 */

export const TIMED_OUT = -32005;
export const CAPTURE_FAILED = -32000;
export const WINDOW_UNAVAILABLE = -32002;
export const HOTKEY_UNAVAILABLE = -32003;
export const BACKEND_FAILED = -32004;

export interface IpcErrorInfo {
  code: number;
  message: string;
  stage?: string;
  category?: string;
}

export interface PlatformCapabilities {
  screenshot: boolean;
  window_capture: boolean;
  accessibility: boolean;
  global_hotkey: boolean;
}

export interface ConfigSummary {
  model: string;
  backend_url: string;
  ui_enabled: boolean;
  global_hotkey: string;
  jpeg_max_dimension: number;
  jpeg_max_bytes: number;
  ui_max_nodes: number;
  max_history_turns: number;
}

export interface HelloResult {
  service: string;
  protocol: string;
  adapter: string;
  capabilities: PlatformCapabilities;
  config: ConfigSummary;
}

export interface TargetInfo {
  process_name: string;
  window_title: string;
  bounds: { x: number; y: number; width: number; height: number };
}

export interface UiInfo {
  status: string;
  element_count: number;
  truncated: boolean;
  warnings: string[];
}

export interface CaptureSummary {
  capture_id: string;
  byte_count: number;
  width: number;
  height: number;
  target: TargetInfo | null;
  ui: UiInfo | null;
  ui_elements?: number;
}

export interface CaptureStartResult {
  pending: true;
  capture: CaptureSummary;
}

export interface Attachment {
  capture_id: string;
  image_base64: string;
  byte_count: number;
  width: number;
  height: number;
  target: TargetInfo | null;
  ui: UiInfo | null;
}

export interface AttachmentGetResult {
  pending: boolean;
  attachment: Attachment | null;
}

export interface SubmitResult {
  answer: string;
  model: string | null;
  latency_ms: number | null;
  used_capture_id: string | null;
}

export interface DiscardResult {
  discarded: boolean;
}

/** Shape of a `capture.completed` event's data. */
export interface CaptureCompletedEvent {
  capture: CaptureSummary;
}

/** Shape of a `capture.failed` / `capture.ignored` event's data. */
export interface CaptureFailedEvent {
  message: string;
  stage?: string;
  category?: string;
  reason?: string;
}

/** Shape of a `degraded` event's data. */
export interface DegradedEvent {
  reason: string;
  message: string;
}

/** Union of sidecar-initiated events the UI consumes. */
export type SidecarEventName =
  | "hotkey.pressed"
  | "capture.completed"
  | "capture.failed"
  | "capture.ignored"
  | "degraded";
