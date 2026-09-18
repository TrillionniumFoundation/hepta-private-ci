import {
  ERROR_CODES,
  MAX_REQUEST_BYTES,
  MAX_VIEW_BYTES,
  UiControlError,
  fail,
  utf8Bytes,
} from "./protocol.js";

const MAX_CSRF_BYTES = 512;
const DEFAULT_TIMEOUT_MS = 10_000;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });

async function boundedResponseText(response, maxBytes) {
  const contentLength = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response exceeds byte limit");
  }

  if (response.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!(value instanceof Uint8Array)) {
          fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response body is not byte data");
        }
        total += value.byteLength;
        if (total > maxBytes) {
          try { await reader.cancel(); } catch {}
          fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response exceeds byte limit");
        }
        chunks.push(value);
      }
    } catch (error) {
      if (error instanceof UiControlError) throw error;
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control transport response body failed");
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    try {
      return UTF8_DECODER.decode(bytes);
    } catch {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response is not valid UTF-8");
    }
  }

  let encoded;
  try {
    encoded = await response.text();
  } catch {
    fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control transport response body failed");
  }
  if (utf8Bytes(encoded) > maxBytes) {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response exceeds byte limit");
  }
  return encoded;
}

function loopbackHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function boundedCsrfToken(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    utf8Bytes(value) > MAX_CSRF_BYTES ||
    /[\r\n]/.test(value)
  ) {
    fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "CSRF token is missing or malformed");
  }
  return value;
}

export class SameOriginHttpTransport {
  #baseUrl;
  #fetch;
  #csrfTokenProvider;
  #timeoutMs;

  constructor({
    baseUrl = "/api/ui-control",
    origin = globalThis.location?.origin,
    fetchImpl = globalThis.fetch?.bind(globalThis),
    csrfTokenProvider = null,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = {}) {
    if (typeof origin !== "string" || origin.length === 0) {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "browser origin is required");
    }
    if (typeof fetchImpl !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "fetchImpl must be a function");
    }
    if (csrfTokenProvider !== null && typeof csrfTokenProvider !== "function") {
      fail(ERROR_CODES.INVALID_INPUT, "csrfTokenProvider must be a function");
    }
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000) {
      fail(ERROR_CODES.INVALID_INPUT, "timeoutMs must be between 1 and 120000 ms");
    }

    let current;
    let target;
    try {
      current = new URL(origin);
      target = new URL(baseUrl, current);
    } catch {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "transport URL is invalid");
    }
    if (target.origin !== current.origin) {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "control transport must be same-origin");
    }
    if (target.username || target.password || target.hash) {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "control transport URL contains forbidden credentials or fragment");
    }
    if (target.protocol !== "https:" && !(target.protocol === "http:" && loopbackHost(target.hostname))) {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "control transport requires HTTPS outside loopback");
    }
    target.pathname = target.pathname.replace(/\/+$/, "");
    target.search = "";
    this.#baseUrl = target;
    this.#fetch = fetchImpl;
    this.#csrfTokenProvider = csrfTokenProvider;
    this.#timeoutMs = timeoutMs;
  }

  async connect(input) {
    return this.#post("connect", input);
  }

  async request(method, request) {
    return this.#post("request", { method, request });
  }

  async reconcile(query) {
    return this.#post("reconcile", query);
  }

  async close(input) {
    return this.#post("close", input);
  }

  async readSnapshot() {
    return this.#json("snapshot", {
      method: "GET",
      maxBytes: MAX_VIEW_BYTES,
      csrf: false,
    });
  }

  async #post(path, body) {
    return this.#json(path, {
      method: "POST",
      body,
      maxBytes: MAX_REQUEST_BYTES,
      csrf: true,
    });
  }

  async #csrfToken() {
    if (this.#csrfTokenProvider) {
      return boundedCsrfToken(await this.#csrfTokenProvider());
    }
    const response = await this.#json("csrf", {
      method: "GET",
      maxBytes: 4096,
      csrf: false,
    });
    return boundedCsrfToken(response?.token);
  }

  async #json(path, { method, body = undefined, maxBytes, csrf }) {
    const target = new URL(`${this.#baseUrl.pathname}/${path}`, this.#baseUrl.origin);
    if (target.origin !== this.#baseUrl.origin) {
      fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "transport path escaped configured origin");
    }
    const headers = new Headers({ accept: "application/json" });
    let encodedBody;
    if (body !== undefined) {
      encodedBody = JSON.stringify(body);
      if (utf8Bytes(encodedBody) > MAX_REQUEST_BYTES) {
        fail(ERROR_CODES.INVALID_INPUT, "transport request exceeds 64 KiB");
      }
      headers.set("content-type", "application/json");
    }
    if (csrf) {
      headers.set("x-hepta-csrf", await this.#csrfToken());
    }

    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller
      ? setTimeout(() => controller.abort(new Error("control transport timeout")), this.#timeoutMs)
      : null;
    timer?.unref?.();
    let response;
    try {
      response = await this.#fetch(target.href, {
        method,
        headers,
        body: encodedBody,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        referrerPolicy: "same-origin",
        signal: controller?.signal,
      });
    } catch (error) {
      if (error instanceof UiControlError) throw error;
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control transport request failed");
    } finally {
      if (timer !== null) clearTimeout(timer);
    }

    if (response.status === 401 || response.status === 403) {
      fail(ERROR_CODES.UNAUTHENTICATED, "control transport authentication or CSRF check failed");
    }
    if (!response.ok) {
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, `control transport returned HTTP ${response.status}`);
    }
    const contentType = response.headers?.get?.("content-type") ?? "";
    const mediaType = contentType.split(";", 1)[0].trim().toLowerCase();
    if (mediaType !== "application/json") {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response is not JSON");
    }
    const encoded = await boundedResponseText(response, maxBytes);
    try {
      return JSON.parse(encoded);
    } catch {
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "control transport response is invalid JSON");
    }
  }
}
