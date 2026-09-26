import {
  assertCanonicalText,
  assertStableIdentifier,
} from "./canonical.js";
import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  asUiControlError,
  uiControlError,
} from "./errors.js";

const encoder = new TextEncoder();
const MAX_RESPONSE_BYTES = 1024 * 1024;

function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, { details });
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

function classifyHttpFailure(status, payload) {
  const message =
    payload && typeof payload.message === "string"
      ? payload.message
      : `ui.control backend returned HTTP ${status}`;
  if ([400, 403, 404, 409, 412, 422].includes(status)) {
    return uiControlError(UI_CONTROL_ERROR_CODES.BACKEND_REJECTED, message, {
      retryable: status === 409 || status === 412,
      details: {
        status,
        backendCode: payload?.errorCode ?? null,
        requestDispatched: true,
      },
    });
  }
  if (status === 401) {
    return uiControlError(UI_CONTROL_ERROR_CODES.SESSION_EXPIRED, message, {
      retryable: true,
      details: { status, requestDispatched: true },
    });
  }
  return uiControlError(UI_CONTROL_ERROR_CODES.TRANSPORT, message, {
    retryable: status >= 429,
    details: { status, requestDispatched: true },
  });
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
    this.#fetch = fetchImpl;
    this.#csrfTokenProvider = csrfTokenProvider;
    this.#timeoutMs = timeoutMs;
  }

  async connect(endpointManifest, { signal } = {}) {
    const session = await this.#fetchJson("session/connect", {
      method: "POST",
      body: endpointManifest,
      signal,
      mutation: false,
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
    assertCanonicalText(method, "method", { maxBytes: 64 });
    try {
      return await this.#fetchJson("operations", {
        method: "POST",
        body: { method, ...input },
        signal,
        mutation: true,
        requestId: input.operationId,
      });
    } catch (cause) {
      if (
        cause instanceof UiControlError &&
        (cause.code === UI_CONTROL_ERROR_CODES.BACKEND_REJECTED ||
          cause.code === UI_CONTROL_ERROR_CODES.SESSION_EXPIRED ||
          cause.code === UI_CONTROL_ERROR_CODES.PERMISSION_DENIED ||
          cause.code === UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION ||
          (cause.code === UI_CONTROL_ERROR_CODES.ABORTED &&
            cause.details.requestDispatched === false))
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
    const query = new URLSearchParams({
      sessionId: input.sessionId,
      connectionGeneration: String(input.connectionGeneration),
      semanticDigest: input.semanticDigest,
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
      });
    } finally {
      this.#session = null;
    }
  }

  async #fetchJson(
    path,
    { method, body, signal, mutation, requestId = globalThis.crypto.randomUUID() },
  ) {
    const url = new URL(path, this.#baseUrl);
    if (url.origin !== this.#origin || !url.href.startsWith(this.#baseUrl.href)) {
      throw invalid("transport path escaped the same-origin API base", { path });
    }
    const csrfToken = this.#csrfTokenProvider();
    if (mutation && (typeof csrfToken !== "string" || csrfToken.length === 0)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
        "mutation request requires a CSRF token",
        { details: { requestDispatched: false } },
      );
    }
    if (signal?.aborted) {
      throw uiControlError(UI_CONTROL_ERROR_CODES.ABORTED, "request was aborted before dispatch", {
        retryable: true,
        details: { requestDispatched: false },
      });
    }

    const timeout = new AbortController();
    const timeoutHandle = setTimeout(
      () => timeout.abort(new DOMException("request timeout", "TimeoutError")),
      this.#timeoutMs,
    );
    const combinedSignal = anySignal([signal, timeout.signal]);
    let response;
    try {
      response = await this.#fetch(url, {
        method,
        credentials: "include",
        cache: "no-store",
        redirect: "error",
        referrerPolicy: "no-referrer",
        headers: {
          accept: "application/json",
          ...(body === undefined ? {} : { "content-type": "application/json" }),
          "x-hepta-request-id": assertCanonicalText(requestId, "requestId", {
            maxBytes: 192,
          }),
          ...(csrfToken ? { "x-hepta-csrf-token": csrfToken } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: combinedSignal,
      });
    } catch (cause) {
      clearTimeout(timeoutHandle);
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
      throw asUiControlError(cause, UI_CONTROL_ERROR_CODES.TRANSPORT, "ui.control network failure", {
        retryable: true,
        details: { requestDispatched: true, mutation },
      });
    } finally {
      clearTimeout(timeoutHandle);
    }

    const declaredLength = Number(response.headers.get("content-length") ?? 0);
    if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        "ui.control response exceeds the maximum allowed size",
        { details: { status: response.status } },
      );
    }
    const text = await response.text();
    if (encoder.encode(text).byteLength > MAX_RESPONSE_BYTES) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        "ui.control response exceeds the maximum allowed size",
        { details: { status: response.status } },
      );
    }
    let payload = null;
    if (text.length > 0) {
      try {
        payload = JSON.parse(text);
      } catch (cause) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.TRANSPORT,
          "ui.control backend returned malformed JSON",
          { details: { status: response.status }, cause },
        );
      }
    }
    if (!response.ok) throw classifyHttpFailure(response.status, payload);
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.TRANSPORT,
        "ui.control backend returned an invalid response object",
        { details: { status: response.status } },
      );
    }
    return payload;
  }
}
