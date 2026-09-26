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

test("mutations require CSRF and are never automatically retried", async () => {
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
});

test("backend conflicts are typed definite rejections", async () => {
  const transport = new SameOriginHttpTransport({
    origin: "https://control.example",
    csrfTokenProvider: () => "csrf-token",
    fetchImpl: async () => response(
      { errorCode: "OPERATION_ID_CONFLICT", message: "operation id already exists" },
      { status: 409 },
    ),
  });
  await assert.rejects(
    transport.request("runtime/stop", {
      operationId: "operation-1",
      semanticDigest: "a".repeat(64),
    }),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.BACKEND_REJECTED,
  );
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
      [
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION,
      ].includes(error.code),
  );
});
