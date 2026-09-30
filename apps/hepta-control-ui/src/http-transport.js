import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  canonicalJson,
} from "./canonical.js";
import { assertPlainObject } from "./runtime-contract.js";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  asUiControlError,
  uiControlError,
} from "./errors.js";

const encoder = new TextEncoder();
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_REQUEST_BYTES = 64 * 1024;
const JSON_CONTENT_TYPE = /^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/iu;
const SAFE_BACKEND_CODE = /^[A-Za-z0-9._:-]{1,128}$/u;

function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, { details });
}

function preparationFailure(cause) {
  const error = asUiControlError(cause, UI_CONTROL_ERROR_CODES.INVALID_INPUT,
    "ui.control request preparation failed before dispatch");
  return uiControlError(error.code, error.message, {
    retryable: error.retryable,
    details: { ...error.details, requestDispatched: false },
    cause,
  });
}

function anySignal(signals) {
  const usable = signals.filter(Boolean);
  if (usable.length === 0) return undefined;
  if (usable.length === 1) return usable[0];
  if (typeof AbortSignal.any === "function") return AbortSignal.any(usable);
  const controller = new AbortController();
  const abort = event => controller.abort(event.target?.reason);
  for (const signal of usable) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      break;
    }
    signal.addEventListener("abort", abort, { once: true });
  }
  return controller.signal;
}

function responseTooLarge(status) {
  return uiControlError(
    UI_CONTROL_ERROR_CODES.TRANSPORT,
    "ui.control response exceeds the maximum allowed size",
    { details: { status, requestDispatched: true, maxBytes: MAX_RESPONSE_BYTES } },
  );
}

function validateResponseHeaders(response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (!JSON_CONTENT_TYPE.test(contentType)) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.TRANSPORT,
      "ui.control backend returned a non-JSON content type",
      { details: { status: response.status, contentType, requestDispatched: true } },
    );
  }

  const rawLength = response.headers.get("content-length");
  if (rawLength === null) return;
  const normalizedLength = rawLength.trim();
  if (!/^(?:0|[1-9][0-9]*)$/u.test(normalizedLength)) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.TRANSPORT,
      "ui.control backend returned an invalid Content-Length header",
      { details: { status: response.status, requestDispatched: true } },
    );
  }
  const declaredLength = Number(normalizedLength);
  if (!Number.isSafeInteger(declaredLength)) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.TRANSPORT,
      "ui.control backend returned an unsafe Content-Length header",
      { details: { status: response.status, requestDispatched: true } },
    );
  }
  if (declaredLength > MAX_RESPONSE_BYTES) throw responseTooLarge(response.status);
}

async function readResponseText(response, signal) {
  if (signal?.aborted) {
    throw signal.reason ?? new DOMException("request aborted", "AbortError");
  }
  if (response.body === null) return "";
  if (typeof response.body?.getReader !== "function") {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.TRANSPORT,
      "ui.control response body is not a readable byte stream",
      { details: { status: response.status, requestDispatched: true } },
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let bytes = 0;
  let output = "";
  let removeAbortListener = () => {};
  const aborted = signal
    ? new Promise((_, reject) => {
        const onAbort = () => {
          void reader.cancel(signal.reason).catch(() => {});
          reject(signal.reason ?? new DOMException("request aborted", "AbortError"));
        };
        signal.addEventListener("abort", onAbort, { once: true });
        removeAbortListener = () => signal.removeEventListener("abort", onAbort);
      })
    : null;

  try {
    while (true) {
      const chunk = aborted
        ? await Promise.race([reader.read(), aborted])
        : await reader.read();
      if (chunk.done) break;
      if (!(chunk.value instanceof Uint8Array)) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.TRANSPORT,
          "ui.control response stream yielded a non-byte chunk",
          { details: { status: response.status, requestDispatched: true } },
        );
      }
      bytes += chunk.value.byteLength;
      if (bytes > MAX_RESPONSE_BYTES) {
        void reader.cancel("ui.control response too large").catch(() => {});
        throw responseTooLarge(response.status);
      }
      output += decoder.decode(chunk.value, { stream: true });
    }
    if (signal?.aborted) {
      throw signal.reason ?? new DOMException("request aborted", "AbortError");
    }
    output += decoder.decode();
    return output;
  } finally {
    removeAbortListener();
    try {
      reader.releaseLock();
    } catch {
      // The stream may still be settling after abort/cancel; no authority state
      // depends on releasing the local reader lock.
    }
  }
}

function classifyHttpFailure(status, payload) {
  const backendCode =
    typeof payload?.errorCode === "string" && SAFE_BACKEND_CODE.test(payload.errorCode)
      ? payload.errorCode
      : null;
  const details = {
    status,
    backendCode,
    requestDispatched: true,
  };
  if (status === 401) {
    return uiControlError(
      UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
      "ui.control authentication expired",
      { retryable: true, details },
    );
  }
  if (status === 403) {
    return uiControlError(
      UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
      "ui.control permission was denied",
      { details },
    );
  }
  if (status === 409) {
    return uiControlError(
      UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
      "ui.control operation identity conflicts with an existing request",
      { retryable: true, details },
    );
  }
  if (status === 412) {
    return uiControlError(
      UI_CONTROL_ERROR_CODES.STALE_REVISION,
      "ui.control runtime view is stale",
      { retryable: true, details },
    );
  }
  if ([400, 404, 422].includes(status)) {
    return uiControlError(
      UI_CONTROL_ERROR_CODES.BACKEND_REJECTED,
      "ui.control backend rejected the request",
      { details },
    );
  }
  return uiControlError(
    UI_CONTROL_ERROR_CODES.TRANSPORT,
    `ui.control backend returned HTTP ${status}`,
    { retryable: status >= 429, details },
  );
}

export class SameOriginHttpTransport {
  #origin;
  #baseUrl;
  #fetch;
  #csrfTokenProvider;
  #timeoutMs;
  #session = null;

  constructor({
    baseUrl = "/api/ui-control/v1/",
    origin = globalThis.location?.origin,
    fetchImpl = globalThis.fetch,
    csrfTokenProvider = () => null,
    timeoutMs = 15_000,
  } = {}) {
    if (typeof fetchImpl !== "function") {
      throw invalid("fetchImpl must be a function");
    }
    if (typeof origin !== "string" || origin.length === 0) {
      throw invalid("origin is required outside a browser environment");
    }
    const canonicalOrigin = new URL(origin).origin;
    const resolved = new URL(baseUrl, `${canonicalOrigin}/`);
    if (resolved.origin !== canonicalOrigin || !resolved.pathname.endsWith("/")) {
      throw invalid("baseUrl must be a same-origin directory URL");
    }
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 120_000) {
      throw invalid("timeoutMs must be a safe integer in [100, 120000]");
    }
    if (typeof csrfTokenProvider !== "function") {
      throw invalid("csrfTokenProvider must be a function");
    }
    this.#origin = canonicalOrigin;
    this.#baseUrl = resolved;
    // Browser Web APIs such as window.fetch require the global object as their
    // receiver in some engines. Keep the public fetch injection point while
    // normalising invocation semantics for both the native function and test
    // doubles.
    this.#fetch = fetchImpl.bind(globalThis);
    this.#csrfTokenProvider = csrfTokenProvider;
    this.#timeoutMs = timeoutMs;
  }

  async connect(endpointManifest, { signal } = {}) {
    const session = await this.#fetchJson("session/connect", {
      method: "POST",
      body: endpointManifest,
      signal,
      mutation: false,
      csrf: true,
    });
    this.#session = session;
    return session;
  }

  async readSnapshot(input, { signal } = {}) {
    return this.#fetchJson("view", {
      method: "POST",
      body: input,
      signal,
      mutation: false,
    });
  }

  async request(method, input, { signal } = {}) {
    try {
      assertCanonicalText(method, "method", { maxBytes: 64 });
      assertPlainObject(input, "mutation envelope");
      if (input.method !== undefined && input.method !== method) {
        throw invalid("mutation envelope cannot replace its transport method");
      }
      input = Object.freeze({ ...input });
    } catch (cause) {
      throw preparationFailure(cause);
    }
    try {
      return await this.#fetchJson("operations", {
        method: "POST",
        body: { ...input, method },
        signal,
        mutation: true,
        requestId: input.operationId,
      });
    } catch (cause) {
      if (
        cause instanceof UiControlError &&
        (cause.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT ||
          cause.code === UI_CONTROL_ERROR_CODES.BACKEND_REJECTED ||
          cause.code === UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT ||
          cause.code === UI_CONTROL_ERROR_CODES.STALE_REVISION ||
          cause.code === UI_CONTROL_ERROR_CODES.SESSION_EXPIRED ||
          cause.code === UI_CONTROL_ERROR_CODES.PERMISSION_DENIED ||
          cause.code === UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION ||
          cause.details.requestDispatched === false)
      ) {
        throw cause;
      }
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION,
        "mutation transport failed after dispatch",
        {
          retryable: true,
          details: {
            requestDispatched: true,
            operationId: input.operationId,
          },
          cause,
        },
      );
    }
  }

  async lookup(input, { signal } = {}) {
    const operationId = assertStableIdentifier(input.operationId, "operationId");
    const sessionId = assertStableIdentifier(input.sessionId, "sessionId");
    const connectionGeneration = assertSafeInteger(
      input.connectionGeneration,
      "connectionGeneration",
      { min: 1 },
    );
    const semanticDigest = assertSha256(input.semanticDigest, "semanticDigest");
    const query = new URLSearchParams({
      sessionId,
      connectionGeneration: String(connectionGeneration),
      semanticDigest,
    });
    return this.#fetchJson(
      `operations/${encodeURIComponent(operationId)}?${query.toString()}`,
      { method: "GET", signal, mutation: false },
    );
  }

  async refresh(session, { signal } = {}) {
    const refreshed = await this.#fetchJson("session/refresh", {
      method: "POST",
      body: {
        sessionId: session.sessionId,
        connectionGeneration: session.connectionGeneration,
        permissionRevision: session.permissionRevision,
      },
      signal,
      mutation: false,
      csrf: true,
    });
    this.#session = refreshed;
    return refreshed;
  }

  async revoke(session, { signal } = {}) {
    await this.#fetchJson("session/revoke", {
      method: "POST",
      body: {
        sessionId: session.sessionId,
        connectionGeneration: session.connectionGeneration,
      },
      signal,
      mutation: true,
      requestId: `revoke:${session.sessionId}`,
    });
    this.#session = null;
  }

  async close(session, { signal } = {}) {
    try {
      await this.#fetchJson("session/close", {
        method: "POST",
        body: {
          sessionId: session.sessionId,
          connectionGeneration: session.connectionGeneration,
        },
        signal,
        mutation: false,
        csrf: true,
      });
    } finally {
      this.#session = null;
    }
  }

  async #fetchJson(
    path,
    {
      method,
      body,
      signal,
      mutation,
      csrf = mutation,
      requestId = globalThis.crypto.randomUUID(),
    },
  ) {
    let url;
    let serializedBody;
    let requestHeader;
    let csrfToken = null;
    try {
      url = new URL(path, this.#baseUrl);
      if (url.origin !== this.#origin || !url.href.startsWith(this.#baseUrl.href)) {
        throw invalid("transport path escaped the same-origin API base", { path });
      }
      if (csrf) {
        const providedToken = this.#csrfTokenProvider();
        if (typeof providedToken !== "string" || providedToken.length === 0) {
          throw uiControlError(
            UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
            "POST request requires a CSRF token",
            { details: { requestDispatched: false } },
          );
        }
        csrfToken = assertCanonicalText(providedToken, "CSRF token", { maxBytes: 512 });
      }
      if (signal?.aborted) {
        throw uiControlError(UI_CONTROL_ERROR_CODES.ABORTED, "request was aborted before dispatch", {
          retryable: true,
          details: { requestDispatched: false },
        });
      }

      if (body !== undefined) {
        serializedBody = canonicalJson(body, { maxEncodedBytes: MAX_REQUEST_BYTES });
      }
      requestHeader = assertStableIdentifier(requestId, "requestId", { maxBytes: 192 });
    } catch (cause) {
      throw preparationFailure(cause);
    }

    const timeout = new AbortController();
    const timeoutHandle = setTimeout(
      () => timeout.abort(new DOMException("request timeout", "TimeoutError")),
      this.#timeoutMs,
    );
    const combinedSignal = anySignal([signal, timeout.signal]);
    let response;
    let text;
    try {
      response = await this.#fetch(url, {
        method,
        credentials: "include",
        cache: "no-store",
        redirect: "error",
        referrerPolicy: "no-referrer",
        headers: {
          accept: "application/json",
          ...(serializedBody === undefined ? {} : { "content-type": "application/json" }),
          "x-hepta-request-id": requestHeader,
          ...(csrfToken ? { "x-hepta-csrf-token": csrfToken } : {}),
        },
        body: serializedBody,
        signal: combinedSignal,
      });
      validateResponseHeaders(response);
      text = await readResponseText(response, combinedSignal);
    } catch (cause) {
      // Header/decoder rejection must stop an unread or unfinished body too.
      if (response?.body) void response.body.cancel(cause).catch(() => {});
      if (combinedSignal?.aborted) {
        const code = mutation
          ? UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION
          : UI_CONTROL_ERROR_CODES.ABORTED;
        throw uiControlError(code, "ui.control request was aborted or timed out", {
          retryable: true,
          details: { requestDispatched: true, mutation },
          cause,
        });
      }
      if (cause instanceof UiControlError) throw cause;
      throw asUiControlError(cause, UI_CONTROL_ERROR_CODES.TRANSPORT, "ui.control network failure", {
        retryable: true,
        details: { requestDispatched: true, mutation },
      });
    } finally {
      clearTimeout(timeoutHandle);
    }

    if (encoder.encode(text).byteLength > MAX_RESPONSE_BYTES) {
      throw responseTooLarge(response.status);
    }
    let payload = null;
    if (text.length > 0) {
      try {
        payload = JSON.parse(text);
      } catch (cause) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.TRANSPORT,
          "ui.control backend returned malformed JSON",
          { details: { status: response.status, requestDispatched: true }, cause },
        );
      }
    }
    if (!response.ok) throw classifyHttpFailure(response.status, payload);
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        "ui.control backend returned an invalid response object",
        { details: { status: response.status, requestDispatched: true } },
      );
    }
    return payload;
  }
}
