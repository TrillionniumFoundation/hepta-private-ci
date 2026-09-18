import { ERROR_CODES, UiControlError, fail, requireRecord, stableId, utf8Bytes } from "./protocol.js";

const MAX_BOOTSTRAP_BYTES = 16 * 1024;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });

async function boundedBootstrapText(response) {
  const contentLength = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_BOOTSTRAP_BYTES) {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap exceeds byte limit");
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
          fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap body is not byte data");
        }
        total += value.byteLength;
        if (total > MAX_BOOTSTRAP_BYTES) {
          try { await reader.cancel(); } catch {}
          fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap exceeds byte limit");
        }
        chunks.push(value);
      }
    } catch (error) {
      if (error instanceof UiControlError) throw error;
      fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control bootstrap response body failed");
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
      fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap is not valid UTF-8");
    }
  }
  let encoded;
  try {
    encoded = await response.text();
  } catch {
    fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control bootstrap response body failed");
  }
  if (utf8Bytes(encoded) > MAX_BOOTSTRAP_BYTES) {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap exceeds byte limit");
  }
  return encoded;
}

function isLoopback(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

export async function loadBrowserBootstrap({
  url = "/api/ui-control/bootstrap",
  origin = globalThis.location?.origin,
  fetchImpl = globalThis.fetch?.bind(globalThis),
} = {}) {
  if (typeof origin !== "string" || typeof fetchImpl !== "function") {
    fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "bootstrap requires browser origin and fetch");
  }
  let target;
  let current;
  try {
    current = new URL(origin);
    target = new URL(url, current);
  } catch {
    fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "bootstrap URL is invalid");
  }
  if (target.origin !== current.origin || target.username || target.password || target.hash) {
    fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "bootstrap must be same-origin without embedded credentials");
  }
  if (target.protocol !== "https:" && !(target.protocol === "http:" && isLoopback(target.hostname))) {
    fail(ERROR_CODES.TRANSPORT_SECURITY_VIOLATION, "bootstrap requires HTTPS outside loopback");
  }

  let response;
  try {
    response = await fetchImpl(target.href, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "same-origin",
      headers: { accept: "application/json" },
    });
  } catch {
    fail(ERROR_CODES.BACKEND_UNAVAILABLE, "control bootstrap request failed");
  }
  if (response.status === 401 || response.status === 403) {
    fail(ERROR_CODES.UNAUTHENTICATED, "control bootstrap is not authenticated");
  }
  if (!response.ok) {
    fail(ERROR_CODES.BACKEND_UNAVAILABLE, `control bootstrap returned HTTP ${response.status}`);
  }
  const contentType = response.headers?.get?.("content-type") ?? "";
  const mediaType = contentType.split(";", 1)[0].trim().toLowerCase();
  if (mediaType !== "application/json") {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap response is not JSON");
  }
  const encoded = await boundedBootstrapText(response);
  let config;
  try { config = JSON.parse(encoded); } catch { fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap is invalid JSON"); }
  requireRecord(config, "control bootstrap");
  stableId(config.persistenceNamespace, "persistenceNamespace");
  if (typeof config.basePath !== "string" || config.basePath.length === 0 || config.basePath.length > 256) {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "control bootstrap basePath is invalid");
  }
  return Object.freeze(config);
}

export function createAccessibleConfirmAction({ document, mount = document?.body } = {}) {
  if (!document || typeof document.createElement !== "function" || !mount || typeof mount.append !== "function") {
    fail(ERROR_CODES.INVALID_INPUT, "confirmation host requires a document and mount element");
  }
  let sequence = 0;
  return async ({ kind, request }) => {
    requireRecord(request, "confirmation request");
    return new Promise((resolve) => {
      sequence += 1;
      const dialog = document.createElement("dialog");
      const titleId = `hepta-confirm-title-${sequence}`;
      dialog.setAttribute("aria-labelledby", titleId);
      dialog.setAttribute("aria-modal", "true");
      dialog.setAttribute("data-hepta-confirm", kind);

      const title = document.createElement("h2");
      title.setAttribute("id", titleId);
      title.textContent = kind === "stop" ? "Confirm runtime stop request" : "Confirm control-plane request";
      dialog.append(title);

      const instruction = document.createElement("p");
      instruction.textContent = "Review the exact immutable request below before submitting.";
      dialog.append(instruction);

      const exact = document.createElement("pre");
      exact.setAttribute("aria-label", "Exact request payload");
      exact.textContent = JSON.stringify(request, null, 2);
      dialog.append(exact);

      const controls = document.createElement("div");
      const cancel = document.createElement("button");
      cancel.setAttribute("type", "button");
      cancel.textContent = "Cancel";
      const confirm = document.createElement("button");
      confirm.setAttribute("type", "button");
      confirm.setAttribute("data-hepta-confirm-submit", "true");
      confirm.textContent = kind === "stop" ? "Confirm stop request" : "Confirm request";
      controls.append(cancel, confirm);
      dialog.append(controls);

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        dialog.close?.();
        dialog.remove?.();
        resolve(value);
      };
      cancel.addEventListener("click", () => finish(false));
      confirm.addEventListener("click", () => finish(true));
      dialog.addEventListener("cancel", (event) => {
        event?.preventDefault?.();
        finish(false);
      });
      mount.append(dialog);
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      confirm.focus?.();
    });
  };
}
