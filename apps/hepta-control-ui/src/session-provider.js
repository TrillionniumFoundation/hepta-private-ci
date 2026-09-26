import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  uiControlError,
} from "./errors.js";

export class SessionProvider {
  #client;
  #manifest;
  #clock;
  #refreshSkewMs;
  #timer = null;
  #listeners = new Set();

  constructor({ client, endpointManifest, clock = () => Date.now(), refreshSkewMs = 60_000 }) {
    if (!client || typeof client.connect !== "function" || typeof client.refreshSession !== "function") {
      throw new TypeError("client must implement connect and refreshSession");
    }
    if (!Number.isSafeInteger(refreshSkewMs) || refreshSkewMs < 5_000 || refreshSkewMs > 600_000) {
      throw new TypeError("refreshSkewMs must be a safe integer in [5000, 600000]");
    }
    this.#client = client;
    this.#manifest = endpointManifest;
    this.#clock = clock;
    this.#refreshSkewMs = refreshSkewMs;
  }

  subscribe(listener) {
    if (typeof listener !== "function") throw new TypeError("listener must be a function");
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  async start({ signal } = {}) {
    await this.#client.connect(this.#manifest, { signal });
    this.#emit("connected");
    this.#schedule();
    return this.#client.readView();
  }

  async refresh({ signal } = {}) {
    try {
      await this.#client.refreshSession({ signal });
      this.#emit("refreshed");
      this.#schedule();
      return this.#client.readView();
    } catch (error) {
      if (
        error instanceof UiControlError &&
        [
          UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
          UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
        ].includes(error.code)
      ) {
        this.#emit("revoked", error);
      }
      throw error;
    }
  }

  async revoke({ signal } = {}) {
    this.#clearTimer();
    await this.#client.revokeSession({ signal });
    this.#emit("revoked");
  }

  stop() {
    this.#clearTimer();
  }

  #schedule() {
    this.#clearTimer();
    const view = this.#client.readView();
    if (!view.connected || !view.expiresAt) return;
    const delay = Math.max(0, view.expiresAt - this.#clock() - this.#refreshSkewMs);
    this.#timer = setTimeout(() => {
      this.refresh().catch(error => this.#emit("refresh-failed", error));
    }, delay);
  }

  #clearTimer() {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
  }

  #emit(type, error) {
    const event = Object.freeze({ type, view: this.#client.readView(), error: error ?? null });
    for (const listener of this.#listeners) {
      try {
        listener(event);
      } catch (cause) {
        queueMicrotask(() => {
          throw uiControlError(
            UI_CONTROL_ERROR_CODES.INVALID_INPUT,
            "session listener failed",
            { cause },
          );
        });
      }
    }
  }
}
