import assert from "node:assert/strict";
import test from "node:test";
import {
  SameOriginHttpTransport,
  UI_CONTROL_ERROR_CODES,
  UiControlError,
} from "../src/index.js";

function response(payload, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

test("HTTP transport enforces same-origin URLs, credentials, and lifecycle CSRF", async () => {
  let observed;
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    fetchImpl: async (url, options) => {
      observed = { url: String(url), options };
      return response({ authenticated: true });
    },
  });
  await transport.connect({ client: "test" });
  assert.equal(observed.url, "https://control.example/api/ui-control/v1/session/connect");
  assert.equal(observed.options.credentials, "include");
  assert.equal(observed.options.redirect, "error");
  assert.equal(observed.options.referrerPolicy, "no-referrer");
  assert.equal(observed.options.headers["x-hepta-csrf-token"], "csrf-token");
});

test("default fetch is invoked with the global receiver", async t => {
  const originalFetch = globalThis.fetch;
  let receiver;
  let observedUrl;
  globalThis.fetch = async function receiverSensitiveFetch(url) {
    receiver = this;
    observedUrl = String(url);
    return response({ authenticated: true });
  };
  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
  });
  await transport.connect({ client: "test" });

  assert.equal(receiver, globalThis);
  assert.equal(observedUrl, "https://control.example/api/ui-control/v1/session/connect");
});

test("session lifecycle POSTs require CSRF before dispatch", async () => {
  let calls = 0;
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => null,
    fetchImpl: async () => {
      calls += 1;
      return response({});
    },
  });
  await assert.rejects(
    transport.connect({ client: "test" }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.PERMISSION_DENIED &&
      error.details.requestDispatched === false,
  );
  assert.equal(calls, 0);
});

test("mutations require bounded CSRF and are never automatically retried", async () => {
  let calls = 0;
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => null,
    fetchImpl: async () => {
      calls += 1;
      return response({});
    },
  });
  await assert.rejects(
    transport.request("runtime/stop", {
      operationId: "operation-1",
      semanticDigest: "a".repeat(64),
    }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
  );
  assert.equal(calls, 0);

  const malformed = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf\nheader",
    fetchImpl: async () => {
      calls += 1;
      return response({});
    },
  });
  await assert.rejects(
    malformed.request("runtime/stop", {
      operationId: "operation-2",
      semanticDigest: "b".repeat(64),
    }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(calls, 0);
});

test("backend conflicts and stale revisions preserve typed definite rejection", async () => {
  for (const [status, expectedCode] of [
    [409, UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT],
    [412, UI_CONTROL_ERROR_CODES.STALE_REVISION],
    [403, UI_CONTROL_ERROR_CODES.PERMISSION_DENIED],
  ]) {
    const transport = new SameOriginHttpTransport({
      origin: "https://control.example",
      csrfTokenProvider: () => "csrf-token",
      fetchImpl: async () => response(
        { errorCode: `STATUS_${status}`, message: "internal secret must not be reflected" },
        { status },
      ),
    });
    await assert.rejects(
      transport.request("runtime/stop", {
        operationId: `operation-${status}`,
        semanticDigest: "a".repeat(64),
      }),
      error =>
        error instanceof UiControlError &&
        error.code === expectedCode &&
        !error.message.includes("internal secret"),
    );
  }
});

test("network loss after mutation dispatch is ambiguous", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    fetchImpl: async () => {
      throw new TypeError("connection reset");
    },
  });
  await assert.rejects(
    transport.request("runtime/stop", {
      operationId: "operation-1",
      semanticDigest: "a".repeat(64),
    }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION,
  );
});

test("timeout remains active while the response body stream is being read", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    timeoutMs: 100,
    fetchImpl: async () => new Response(
      new ReadableStream({
        pull() {
          return new Promise(() => {});
        },
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    ),
  });
  await assert.rejects(
    transport.connect({ client: "test" }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );
});

test("chunked responses are rejected as soon as the hard byte ceiling is crossed", async () => {
  const first = new Uint8Array(700 * 1024).fill(0x20);
  const second = new Uint8Array(400 * 1024).fill(0x20);
  const chunks = [first, second];
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    fetchImpl: async () => new Response(
      new ReadableStream({
        pull(controller) {
          const chunk = chunks.shift();
          if (chunk) controller.enqueue(chunk);
          else controller.close();
        },
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    ),
  });
  await assert.rejects(
    transport.connect({ client: "test" }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.TRANSPORT &&
      error.details.maxBytes === 1024 * 1024,
  );
});

test("operation lookup validates every identity binding before dispatch", async () => {
  let calls = 0;
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    fetchImpl: async () => {
      calls += 1;
      return response({ found: false });
    },
  });
  await assert.rejects(
    transport.lookup({
      operationId: "operation-1",
      sessionId: "session-1",
      connectionGeneration: 0,
      semanticDigest: "a".repeat(64),
    }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(calls, 0);
});

test("successful responses require an explicit JSON media type", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    fetchImpl: async () => new Response("{}", {
      status: 200,
      headers: { "content-type": "text/plain" },
    }),
  });
  await assert.rejects(
    transport.connect({ client: "test" }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.TRANSPORT,
  );
});

test("invalid pre-dispatch CSRF has a definite unsent outcome", async () => {
  let calls = 0;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf\ninvalid", fetchImpl: async () => { calls += 1; return response({}); } });
  await assert.rejects(transport.request("runtime/stop", { operationId: "unsent-operation" }),
    error => error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT && error.details.requestDispatched === false);
  assert.equal(calls, 0);
});

test("request serialization rejects accessors and toJSON without running them", async () => {
  let effects = 0;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token", fetchImpl: async () => { effects += 1; return response({}); } });
  for (const body of [{ get client() { effects += 1; return "unsafe"; } },
    { toJSON() { effects += 1; return {}; } }]) {
    await assert.rejects(transport.connect(body), error =>
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT && error.details.requestDispatched === false);
  }
  assert.equal(effects, 0);
});

test("an oversized request is rejected before network dispatch", async () => {
  let calls = 0;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token", fetchImpl: async () => { calls += 1; return response({}); } });
  await assert.rejects(transport.connect({ padding: "x".repeat(64 * 1024) }), error =>
    error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT && error.details.requestDispatched === false);
  assert.equal(calls, 0);
});

test("mutation envelope validation cannot invoke accessors or overwrite its method", async () => {
  let effects = 0;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token", fetchImpl: async () => { effects += 1; return response({}); } });
  for (const body of [{ operationId: "method-operation", method: "runtime/start" },
    { get operationId() { effects += 1; return "getter-operation"; } }]) {
    await assert.rejects(transport.request("runtime/stop", body), error =>
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT && error.details.requestDispatched === false);
  }
  assert.equal(effects, 0);
});

test("header rejection cancels the unread response stream", async () => {
  let cancelled = false;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token", fetchImpl: async () => new Response(new ReadableStream({
      pull() { return new Promise(() => {}); }, cancel() { cancelled = true; },
    }), { headers: { "content-type": "text/plain" } }) });
  await assert.rejects(transport.connect({}), { code: UI_CONTROL_ERROR_CODES.TRANSPORT });
  assert.equal(cancelled, true);
});

test("UTF-8 rejection cancels the unfinished response stream", async () => {
  let cancelled = false;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token", fetchImpl: async () => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array([0xff])); },
      pull() { return new Promise(() => {}); }, cancel() { cancelled = true; },
    }), { headers: { "content-type": "application/json" } }) });
  await assert.rejects(transport.connect({}), { code: UI_CONTROL_ERROR_CODES.TRANSPORT });
  assert.equal(cancelled, true);
});
