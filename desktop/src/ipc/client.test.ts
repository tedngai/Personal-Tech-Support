import { describe, expect, it, vi } from "vitest";
import { SidecarClient } from "./client";
import type {
  AttachmentGetResult,
  CaptureStartResult,
  HelloResult,
  SubmitResult,
} from "./types";

// Tauri's event layer is mocked: these tests exercise listener lifecycle.
const counters = vi.hoisted(() => ({ listenCalls: 0, unlistenCalls: 0 }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(() => {
    counters.listenCalls += 1;
    return Promise.resolve(() => {
      counters.unlistenCalls += 1;
    });
  }),
}));

// Golden fixtures generated from the Python sidecar's contract tests
// (scripts/generate_ipc_fixtures.py). If the Python service's response
// shapes drift from the TS types, these tests fail.
import helloFixture from "./fixtures/hello.json";
import healthFixture from "./fixtures/health-check.json";
import permissionsFixture from "./fixtures/permissions-status.json";
import captureStartFixture from "./fixtures/capture-start.json";
import attachmentGetFixture from "./fixtures/attachment-get.json";
import attachmentGetEmptyFixture from "./fixtures/attachment-get-empty.json";
import unknownMethodFixture from "./fixtures/unknown-method.json";
import windowIdentityErrorFixture from "./fixtures/window-identity-error.json";
import backendErrorFixture from "./fixtures/backend-error.json";

function testClient() {
  const sentLines: string[] = [];
  const client = new SidecarClient((line) => {
    sentLines.push(line);
  });
  return { client, sentLines };
}

/** Feed a fixture as the response to the client's Nth request (1-based). */
function respond(client: SidecarClient, fixture: object, requestId: number): void {
  client.handleLine(JSON.stringify({ ...fixture, id: requestId }));
}

describe("sidecar client against Python golden fixtures", () => {
  it("sends a well-formed JSON-RPC request line", () => {
    const { client, sentLines } = testClient();
    void client.request("hello");
    expect(sentLines).toHaveLength(1);
    expect(JSON.parse(sentLines[0])).toEqual({
      jsonrpc: "2.0",
      id: 1,
      method: "hello",
      params: {},
    });
  });

  it("parses the hello result into HelloResult", async () => {
    const { client } = testClient();
    const request = client.request<HelloResult>("hello", {}, 100).then((r) => {
      expect(r.service).toBe("labguide-sidecar");
      expect(r.protocol).toBe("2.0");
      expect(r.capabilities.window_capture).toBe(true);
      expect(r.config.jpeg_max_bytes).toBe(2_000_000);
    });
    client.handleLine(JSON.stringify(helloFixture));
    await request;
  });

  it("parses the health check result", async () => {
    const { client } = testClient();
    const request = client.request<{ reachable: boolean }>("health.check", {}, 100).then((r) => {
      expect(r.reachable).toBe(true);
    });
    respond(client, healthFixture, 1);
    await request;
  });

  it("parses permissions.status result", async () => {
    const { client } = testClient();
    const request = client
      .request<HelloResult>("permissions.status", {}, 100)
      .then((r) => {
        expect(r.capabilities.screenshot).toBe(true);
      });
    respond(client, permissionsFixture, 1);
    await request;
  });

  it("parses capture.start result with target metadata", async () => {
    const { client } = testClient();
    const request = client
      .request<CaptureStartResult>("capture.start", {}, 100)
      .then((r) => {
        expect(r.pending).toBe(true);
        expect(r.capture.target?.process_name).toBe("Notepad");
        expect(r.capture.ui?.status).toBe("pending");
        expect(r.capture.byte_count).toBeGreaterThan(0);
      });
    respond(client, captureStartFixture, 1);
    await request;
  });

  it("parses attachment.get result with base64 payload", async () => {
    const { client } = testClient();
    const request = client
      .request<AttachmentGetResult>("attachment.get", {}, 100)
      .then((r) => {
        expect(r.pending).toBe(true);
        expect(r.attachment?.image_base64).toBeTruthy();
        expect(r.attachment?.target?.window_title).toBe("Untitled");
      });
    respond(client, attachmentGetFixture, 1);
    await request;
  });

  it("parses empty attachment result", async () => {
    const { client } = testClient();
    const request = client
      .request<AttachmentGetResult>("attachment.get", {}, 100)
      .then((r) => {
        expect(r.pending).toBe(false);
        expect(r.attachment).toBeNull();
      });
    respond(client, attachmentGetEmptyFixture, 1);
    await request;
  });

  it("rejects unknown-method errors with stage data", async () => {
    const { client } = testClient();
    const request = client.request("nope", {}, 100);
    respond(client, unknownMethodFixture, 1);
    await expect(request).rejects.toMatchObject({
      code: -32601,
      stage: "dispatch",
    });
  });

  it("rejects window-identity errors with reason category", async () => {
    const { client } = testClient();
    const request = client.request<CaptureStartResult>("capture.start", {}, 100);
    respond(client, windowIdentityErrorFixture, 1);
    await expect(request).rejects.toMatchObject({
      code: -32002,
      category: "closed",
      stage: "window-identity",
    });
  });

  it("rejects backend errors with stage data", async () => {
    const { client } = testClient();
    const request = client.request<SubmitResult>("submit", {}, 100);
    respond(client, backendErrorFixture, 1);
    await expect(request).rejects.toMatchObject({
      code: -32004,
      stage: "backend",
    });
  });

  it("times out a request that never gets a response", async () => {
    vi.useFakeTimers();
    try {
      const { client } = testClient();
      const request = client.request("hello", {}, 1000);
      const expectation = expect(request).rejects.toMatchObject({ code: -32005 });
      await vi.advanceTimersByTimeAsync(1001);
      await expectation;
    } finally {
      vi.useRealTimers();
    }
  });

  it("detach removes event listeners so a remount cannot duplicate them", () => {
    const { client } = testClient();
    const listener = vi.fn();
    client.onEvent(listener);
    client.detach();
    client.handleLine(JSON.stringify({ event: "capture.completed", data: {} }));
    expect(listener).not.toHaveBeenCalled();
  });

  it("dispatches events to subscribers", () => {
    const { client } = testClient();
    const listener = vi.fn();
    client.onEvent(listener);
    client.handleLine(
      JSON.stringify({ event: "capture.completed", data: { capture: { capture_id: "x" } } })
    );
    expect(listener).toHaveBeenCalledWith("capture.completed", {
      capture: { capture_id: "x" },
    });
  });

  it("surfaces unparsable lines as degraded protocol events", () => {
    const { client } = testClient();
    const listener = vi.fn();
    client.onEvent(listener);
    client.handleLine("not json at all");
    expect(listener).toHaveBeenCalledWith(
      "degraded",
      expect.objectContaining({ reason: "protocol" })
    );
  });
});

describe("attach lifecycle (StrictMode double-mount safety)", () => {
  it("concurrent attach calls register exactly one listener pair", async () => {
    const before = counters.listenCalls;
    const client = new SidecarClient(() => {});
    await Promise.all([client.attach(), client.attach()]);
    // One line listener + one shell listener, never doubled.
    expect(counters.listenCalls - before).toBe(2);
    client.detach();
  });

  it("detach racing an in-flight attach leaves no listener behind", async () => {
    const beforeListen = counters.listenCalls;
    const beforeUnlisten = counters.unlistenCalls;
    const client = new SidecarClient(() => {});
    const pending = client.attach();
    client.detach(); // runs before the attach awaits resolve
    await pending;
    expect(counters.listenCalls - beforeListen).toBe(2);
    // Both half-registered listeners must be unlistened by the loser.
    expect(counters.unlistenCalls - beforeUnlisten).toBe(2);
  });

  it("detach then re-attach works and stays single", async () => {
    const before = counters.listenCalls;
    const client = new SidecarClient(() => {});
    await client.attach();
    client.detach();
    await client.attach();
    expect(counters.listenCalls - before).toBe(4);
    client.detach();
  });
});
