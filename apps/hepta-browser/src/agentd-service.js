import {
  AgentdBrowserFrameDecoder,
  encodeAgentdBrowserFrame,
  buildAgentdBrowserFrame,
  canonicalAgentdBrowserJson,
  MAX_BROWSER_AGENTD_FRAME_BYTES,
} from "./agentd-protocol.js";
import { browserReplayEvidence } from "./replay-evidence.js";

const MAX_QUEUED_FRAMES = 64;
const MAX_QUEUED_BYTES = 4 * MAX_BROWSER_AGENTD_FRAME_BYTES;

const SERVICE_METHODS = new Set([
  "open_profile",
  "admit_effect_grant",
  "observe_page",
  "navigate_or_act",
  "reconcile_operation",
  "reconcile_persisted_operation",
  "close_profile",
]);

function requireRecord(value, name) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw new TypeError(`${name} must be a plain object`);
  }
  return value;
}

function boundedError(error) {
  return String(error?.message ?? error ?? "browser service error").slice(
    0,
    512,
  );
}

function digest(value, name) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

export class AgentdBrowserChannel {
  #input;
  #output;
  #decoder = new AgentdBrowserFrameDecoder();
  #nextIncomingSequence = 1;
  #nextOutgoingSequence = 1;
  #queue = [];
  #queuedBytes = 0;
  #waiters = [];
  #pendingSends = new Set();
  #failed = null;
  #ended = false;
  #closeController = new AbortController();

  constructor({ input, output }) {
    if (!input?.on || typeof output?.write !== "function") {
      throw new TypeError(
        "Agentd browser channel requires readable and writable streams",
      );
    }
    this.#input = input;
    this.#output = output;
    input.on("data", (chunk) => this.#onBytes(chunk));
    input.on("end", () => this.#onEnd());
    input.on("error", (error) => this.#fail(error));
    input.on("close", () => {
      if (!this.#ended)
        this.#fail(new Error("Agentd browser input closed unexpectedly"));
    });
    output.on?.("error", (error) => this.#fail(error));
    for (const event of ["close", "finish"]) {
      output.on?.(event, () => {
        if (!this.#ended) this.#fail(new Error("Agentd browser output closed"));
      });
    }
  }

  async nextFrame({ signal } = {}) {
    if (signal?.aborted) throw signal.reason;
    if (this.#failed) throw this.#failed;
    if (this.#queue.length) {
      const queued = this.#queue.shift();
      this.#queuedBytes -= queued.bytes;
      return queued.frame;
    }
    if (this.#ended) return null;
    return new Promise((resolve, reject) => {
      const cleanup = () => signal?.removeEventListener("abort", abort);
      const waiter = {
        resolve(frame) {
          cleanup();
          resolve(frame);
        },
        reject(error) {
          cleanup();
          reject(error);
        },
      };
      const abort = () => {
        const index = this.#waiters.indexOf(waiter);
        if (index !== -1) this.#waiters.splice(index, 1);
        waiter.reject(signal.reason);
      };
      signal?.addEventListener("abort", abort, { once: true });
      this.#waiters.push(waiter);
    });
  }

  assertOpen() {
    if (this.#output.destroyed || this.#output.writableEnded) {
      this.#fail(new Error("Agentd browser output closed"));
    }
    if (this.#failed) throw this.#failed;
    if (this.#ended) throw new Error("Agentd browser channel is closed");
  }

  get signal() {
    return this.#closeController.signal;
  }

  send(kind, requestId, payload) {
    try {
      this.assertOpen();
    } catch (error) {
      return Promise.reject(error);
    }
    const encoded = encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: this.#nextOutgoingSequence,
        kind,
        requestId,
        payload,
      }),
    );
    this.#nextOutgoingSequence += 1;
    return new Promise((resolve, reject) => {
      const pending = { resolve, reject };
      this.#pendingSends.add(pending);
      try {
        this.#output.write(encoded, (error) => {
          if (!this.#pendingSends.delete(pending)) return;
          if (error) {
            this.#fail(error);
            reject(error);
          } else resolve();
        });
      } catch (error) {
        this.#pendingSends.delete(pending);
        this.#fail(error);
        reject(error);
      }
    });
  }

  #onBytes(chunk) {
    if (this.#failed || this.#ended) return;
    let frames;
    try {
      frames = this.#decoder.push(chunk);
    } catch (error) {
      this.#fail(error);
      return;
    }
    for (const frame of frames) {
      if (frame.sequence !== this.#nextIncomingSequence++) {
        this.#fail(
          new TypeError("Agentd browser input sequence is not monotonic"),
        );
        return;
      }
      const waiter = this.#waiters.shift();
      if (waiter) waiter.resolve(frame);
      else {
        const bytes = Buffer.byteLength(
          canonicalAgentdBrowserJson(frame),
          "utf8",
        );
        if (
          this.#queue.length >= MAX_QUEUED_FRAMES ||
          this.#queuedBytes + bytes > MAX_QUEUED_BYTES
        ) {
          this.#fail(new TypeError("Agentd browser input queue exceeds limit"));
          return;
        }
        this.#queue.push({ frame, bytes });
        this.#queuedBytes += bytes;
      }
    }
  }

  #onEnd() {
    if (this.#failed || this.#ended) return;
    try {
      this.#decoder.end();
    } catch (error) {
      this.#fail(error);
      return;
    }
    this.#ended = true;
    this.#closeController.abort(new Error("Agentd browser channel is closed"));
    this.#queue.length = 0;
    this.#queuedBytes = 0;
    this.#rejectSends(new Error("Agentd browser channel is closed"));
    for (const waiter of this.#waiters.splice(0)) waiter.resolve(null);
  }

  #fail(error) {
    if (this.#failed) return;
    this.#failed = error instanceof Error ? error : new Error(String(error));
    this.#closeController.abort(this.#failed);
    this.#queue.length = 0;
    this.#queuedBytes = 0;
    this.#rejectSends(this.#failed);
    for (const waiter of this.#waiters.splice(0)) waiter.reject(this.#failed);
  }

  #rejectSends(error) {
    for (const pending of this.#pendingSends) pending.reject(error);
    this.#pendingSends.clear();
  }
}

export class ParentFinalUseAuthority {
  #channel;
  #activeRequestId = null;
  #activeRequestController = null;

  constructor(channel) {
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError(
        "ParentFinalUseAuthority requires AgentdBrowserChannel",
      );
    }
    this.#channel = channel;
  }

  async withRequest(requestId, call) {
    this.#channel.assertOpen();
    if (this.#activeRequestId !== null) {
      throw new TypeError(
        "browser service authority request is already active",
      );
    }
    this.#activeRequestId = requestId;
    const controller = new AbortController();
    const onChannelClose = () => controller.abort(this.#channel.signal.reason);
    this.#channel.signal.addEventListener("abort", onChannelClose, {
      once: true,
    });
    this.#activeRequestController = controller;
    try {
      return await call();
    } finally {
      this.#channel.signal.removeEventListener("abort", onChannelClose);
      controller.abort(
        new Error(
          "browser authority request ended before authorization completed",
        ),
      );
      this.#activeRequestId = null;
      this.#activeRequestController = null;
    }
  }

  async withVerifiedUse(request, consumer) {
    requireRecord(request, "final-use request");
    if (this.#activeRequestId === null) {
      throw new TypeError(
        "final-use authority may only run inside one Agentd request",
      );
    }
    const requestId = this.#activeRequestId;
    const signal = this.#activeRequestController.signal;
    const requestDigest = digest(request.requestDigest, "requestDigest");
    const authorityEpoch = positiveInteger(
      request.authorityEpoch,
      "authorityEpoch",
    );
    await this.#channel.send("authority_challenge", requestId, {
      request,
      requestDigest,
      authorityEpoch,
    });
    const enter = await this.#channel.nextFrame({ signal });
    if (signal.aborted) throw signal.reason;
    this.#channel.assertOpen();
    if (
      !enter ||
      enter.kind !== "authority_enter" ||
      enter.requestId !== requestId
    ) {
      throw new TypeError("Agentd did not enter the matching final-use fence");
    }
    const payload = requireRecord(enter.payload, "authority enter payload");
    if (payload.authorized !== true) {
      throw new TypeError("Agentd final-use authority denied browser dispatch");
    }
    const witness = Object.freeze({
      authorized: true,
      witnessDigest: digest(payload.witnessDigest, "witnessDigest"),
      authorityEpoch: positiveInteger(payload.authorityEpoch, "authorityEpoch"),
      requestDigest: digest(payload.requestDigest, "requestDigest"),
    });
    if (
      witness.requestDigest !== requestDigest ||
      witness.authorityEpoch !== authorityEpoch
    ) {
      throw new TypeError(
        "Agentd final-use witness does not bind the Browser request",
      );
    }
    const result = await consumer(witness, Object.freeze({ signal }));
    if (signal.aborted) throw signal.reason;
    this.#channel.assertOpen();
    await this.#channel.send("dispatch_boundary", requestId, {
      requestDigest,
      witnessDigest: witness.witnessDigest,
      localDispatchCrossed: true,
    });
    return result;
  }
}

export class BrowserAgentdService {
  #host;
  #channel;
  #authority;

  constructor({ host, channel, authority }) {
    if (host === null || typeof host !== "object" || Array.isArray(host)) {
      throw new TypeError(
        "browser host must implement the Browser owner interface",
      );
    }
    for (const method of [
      "openProfile",
      "admitEffectGrant",
      "observePage",
      "navigateOrAct",
      "reconcileOperation",
      "reconcilePersistedOperation",
      "closeProfile",
    ]) {
      if (typeof host[method] !== "function")
        throw new TypeError(`browser host.${method} is required`);
    }
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError("BrowserAgentdService requires AgentdBrowserChannel");
    }
    if (!(authority instanceof ParentFinalUseAuthority)) {
      throw new TypeError(
        "BrowserAgentdService requires ParentFinalUseAuthority",
      );
    }
    this.#host = host;
    this.#channel = channel;
    this.#authority = authority;
  }

  async run() {
    while (true) {
      const frame = await this.#channel.nextFrame();
      if (frame === null) return;
      if (frame.kind !== "request") {
        throw new TypeError("Browser service expected an Agentd request frame");
      }
      await this.#serve(frame);
    }
  }

  async #serve(frame) {
    try {
      const payload = requireRecord(
        frame.payload,
        "Browser service request payload",
      );
      if (!SERVICE_METHODS.has(payload.method)) {
        throw new TypeError("Browser service method is not registered");
      }
      const input = requireRecord(payload.input, "Browser service input");
      let result;
      switch (payload.method) {
        case "open_profile":
          result = await this.#host.openProfile(input);
          break;
        case "admit_effect_grant":
          result = await this.#host.admitEffectGrant(input);
          break;
        case "observe_page":
          result = await this.#host.observePage(input);
          break;
        case "navigate_or_act":
          result = await this.#authority.withRequest(frame.requestId, () =>
            this.#host.navigateOrAct(input),
          );
          break;
        case "reconcile_operation":
          result = await this.#host.reconcileOperation(input);
          break;
        case "reconcile_persisted_operation":
          result = await this.#host.reconcilePersistedOperation(input);
          break;
        case "close_profile":
          result = await this.#host.closeProfile(input);
          break;
        default:
          throw new TypeError("unreachable Browser service method");
      }
      const response = {
        ok: true,
        result,
      };
      if (payload.method === "navigate_or_act") {
        const replay = browserReplayEvidence(result);
        if (replay) response.replay = replay;
      }
      await this.#channel.send("response", frame.requestId, response);
    } catch (error) {
      await this.#channel.send("response", frame.requestId, {
        ok: false,
        error: boundedError(error),
      });
    }
  }
}
