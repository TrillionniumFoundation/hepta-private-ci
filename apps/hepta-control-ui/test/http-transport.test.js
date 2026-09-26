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

test("HTTP transport enforces same-origin URLs and credentials", async () => {
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
  });
  await transport.connect({ client: "test" });

  assert.equal(receiver, globalThis);
  assert.equal(observedUrl, "https://control.example/api/ui-control/v1/session/connect");
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
        { errorCode: `STATUS_${status}`, message: `backend returned ${status}` },
        { status },
      ),
    });
    await assert.rejects(
      transport.request("runtime/stop", {
        operationId: `operation-${status}`,
        semanticDigest: "a".repeat(64),
      }),
      error => error instanceof UiControlError && error.code === expectedCode,
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

test("timeout remains active while the response body is being read", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    timeoutMs: 100,
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      text: async () => new Promise(() => {}),
    }),
  });
  await assert.rejects(
    transport.connect({ client: "test" }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.ABORTED,
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
