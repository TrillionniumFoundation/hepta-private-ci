import {
  UI_CONTROL_ERROR_CODES,
  UiControlError,
  uiControlError,
} from "./errors.js";

const MAX_TIMER_DELAY_MS = 2_147_000_000;
const SESSION_AUTHORITY_LOSS = new Set([
  UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
  UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
  UI_CONTROL_ERROR_CODES.SESSION_IDENTITY_CHANGED,
  UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
  UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
  UI_CONTROL_ERROR_CODES.PROTOCOL_MISMATCH,
]);

export class SessionProvider {
  #client;
  #manifest;
  #clock;
  #refreshSkewMs;
  #timer = null;
  #listeners = new Set();
  #active = false;
  #epoch = 0;
  #startPromise = null;
  #refreshPromise = null;
  #refreshFailures = 0;

  constructor({ client, endpointManifest, clock = () => Date.now(), refreshSkewMs = 60_000 }) {
    const requiredMethods = [
      "connect",
      "refreshSession",
      "revokeSession",
      "close",
      "readView",
    ];
    if (
      !client ||
      requiredMethods.some(method => typeof client[method] !== "function")
    ) {
      throw new TypeError(
        "client must implement connect, refreshSession, revokeSession, close, and readView",
      );
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
    if (this.#startPromise) return this.#startPromise;
    const current = this.#client.readView();
    if (this.#active && current.connected) {
      this.#schedule(this.#epoch);
      return current;
    }

    this.#active = true;
    this.#refreshFailures = 0;
    const epoch = ++this.#epoch;
    this.#clearTimer();
    const startPromise = this.#startOnce(epoch, signal);
    this.#startPromise = startPromise;
    try {
      return await startPromise;
    } finally {
      if (this.#startPromise === startPromise) this.#startPromise = null;
    }
  }

  async #startOnce(epoch, signal) {
    try {
      if (!this.#client.readView().connected) {
        await this.#client.connect(this.#manifest, { signal });
      }
    } catch (error) {
      if (this.#active && epoch === this.#epoch) {
        this.#active = false;
        ++this.#epoch;
        this.#clearTimer();
        this.#emit("connect-failed", error);
      }
      throw error;
    }

    if (!this.#active || epoch !== this.#epoch) {
      try {
        await this.#client.close({ signal });
      } catch {
        // RuntimeClient closes local authority before attempting transport
        // cleanup, so a lost close acknowledgement cannot restore access.
      }
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.ABORTED,
        "session provider stopped while connection was being established",
        { retryable: true, details: { requestDispatched: true } },
      );
    }
    this.#emit("connected");
    this.#schedule(epoch);
    return this.#client.readView();
  }

  async refresh({ signal } = {}) {
    if (!this.#active) {
      throw uiControlError(
        UI_CONTROL_ERROR_CODES.NOT_CONNECTED,
        "session provider is stopped",
        { retryable: true },
      );
    }
    if (this.#refreshPromise) return this.#refreshPromise;
    const epoch = this.#epoch;
    const refreshPromise = this.#refreshOnce(epoch, signal);
    this.#refreshPromise = refreshPromise;
    try {
      return await refreshPromise;
    } finally {
      if (this.#refreshPromise === refreshPromise) this.#refreshPromise = null;
    }
  }

  async #refreshOnce(epoch, signal) {
    try {
      await this.#client.refreshSession({ signal });
      if (!this.#active || epoch !== this.#epoch) {
        throw uiControlError(
          UI_CONTROL_ERROR_CODES.ABORTED,
          "session provider stopped while refresh was in flight",
          { retryable: true, details: { requestDispatched: true } },
        );
      }
      this.#refreshFailures = 0;
      this.#emit("refreshed");
      this.#schedule(epoch);
      return this.#client.readView();
    } catch (error) {
      if (
        error instanceof UiControlError &&
        SESSION_AUTHORITY_LOSS.has(error.code) &&
        this.#active &&
        epoch === this.#epoch
      ) {
        this.#active = false;
        ++this.#epoch;
        this.#clearTimer();
        try {
          await this.#client.close({ signal });
        } catch {
          // Local authority is already removed by RuntimeClient.close().
        }
        this.#emit("revoked", error);
      } else if (this.#active && epoch === this.#epoch) {
        this.#refreshFailures += 1;
        this.#schedule(epoch);
      }
      throw error;
    }
  }

  async revoke({ signal } = {}) {
    this.#active = false;
    ++this.#epoch;
    this.#clearTimer();
    try {
      await this.#client.revokeSession({ signal });
    } finally {
      this.#emit("revoked");
    }
  }

  stop() {
    this.#active = false;
    ++this.#epoch;
    this.#clearTimer();
  }

  #schedule(epoch = this.#epoch) {
    this.#clearTimer();
    if (!this.#active || epoch !== this.#epoch) return;
    const view = this.#client.readView();
    if (!view.connected || !view.expiresAt) return;
    const remaining = Math.max(0, view.expiresAt - this.#clock());
    const backoff = Math.min(60_000, 1_000 * (2 ** Math.min(this.#refreshFailures - 1, 6)));
    // Bound transient retries by expiry. Unchanged short-lived sessions must
    // not turn refresh skew into an immediate successful-refresh busy loop.
    const desiredDelay = Math.min(remaining, this.#refreshFailures > 0
      ? backoff : Math.max(1_000, remaining - this.#refreshSkewMs));
    const delay = Math.min(desiredDelay, MAX_TIMER_DELAY_MS);
    this.#timer = setTimeout(() => {
      this.#timer = null;
      if (!this.#active || epoch !== this.#epoch) return;
      if (desiredDelay > MAX_TIMER_DELAY_MS) {
        this.#schedule(epoch);
        return;
      }
      this.refresh().catch(error => {
        if (this.#active && epoch === this.#epoch) this.#emit("refresh-failed", error);
      });
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
        const failure = uiControlError(
          UI_CONTROL_ERROR_CODES.INVALID_INPUT,
          "session listener failed",
          { cause },
        );
        if (typeof globalThis.reportError === "function") globalThis.reportError(failure);
        else globalThis.console?.error?.(failure);
      }
    }
  }
}
