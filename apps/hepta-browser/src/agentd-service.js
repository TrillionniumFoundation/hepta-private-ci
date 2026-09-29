import {
  AgentdBrowserFrameDecoder,
  encodeAgentdBrowserFrame,
  buildAgentdBrowserFrame,
  canonicalAgentdBrowserJson,
} from "./agentd-protocol.js";

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
  return String(error?.message ?? error ?? "browser service error").slice(0, 512);
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

class AgentdBrowserChannelClosed extends Error {}

export class AgentdBrowserChannel {
  #input;
  #output;
  #decoder = new AgentdBrowserFrameDecoder();
  #nextIncomingSequence = 1;
  #nextOutgoingSequence = 1;
  #queue = [];
  #queuedBytes = 0;
  #writes = new Set();
  #pendingWriteBytes = 0;
  #waiters = [];
  #failed = null;
  #ended = false;

  constructor({ input, output }) {
    if (!input?.on || typeof output?.write !== "function") {
      throw new TypeError("Agentd browser channel requires readable and writable streams");
    }
    this.#input = input;
    this.#output = output;
    input.on("data", (chunk) => this.#onBytes(chunk));
    input.on("end", () => this.#onEnd());
    input.on("error", (error) => this.#fail(error));
    input.on("close", () => this.#streamClosed("input"));
    output.on?.("error", (error) => this.#fail(error));
    output.on?.("close", () => this.#streamClosed("output"));
    output.on?.("finish", () => this.#streamClosed("output"));
    this.#checkStreams();
  }

  async nextFrame({ signal } = {}) {
    this.#checkStreams();
    if (this.#failed) throw this.#failed;
    if (signal?.aborted) throw new Error("Agentd browser receive was cancelled");
    if (this.#queue.length) {
      const { frame, bytes } = this.#queue.shift();
      this.#queuedBytes -= bytes;
      return frame;
    }
    if (this.#ended) return null;
    if (this.#waiters.length >= 8) {
      throw new TypeError("Agentd browser receive waiter capacity occupied");
    }
    return new Promise((resolve, reject) => {
      const cleanup = () => signal?.removeEventListener("abort", abort);
      const waiter = {
        resolve: (frame) => { cleanup(); resolve(frame); },
        reject: (error) => { cleanup(); reject(error); },
      };
      const abort = () => {
        const index = this.#waiters.indexOf(waiter);
        if (index !== -1) this.#waiters.splice(index, 1);
        waiter.reject(new Error("Agentd browser receive was cancelled"));
      };
      this.#waiters.push(waiter);
      signal?.addEventListener("abort", abort, { once: true });
    });
  }

  invalidate(error) {
    this.#fail(error);
  }

  assertUsable() {
    this.#checkStreams();
    if (this.#failed) throw this.#failed;
    if (this.#ended) throw new Error("Agentd browser channel is closed");
  }

  async send(kind, requestId, payload) {
    this.assertUsable();
    const encoded = encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: this.#nextOutgoingSequence,
        kind,
        requestId,
        payload,
      }),
    );
    if (this.#writes.size >= 8 || this.#pendingWriteBytes + encoded.length > 4 * 1_048_576) {
      // Nothing was written and the sequence has not advanced. Backpressure is
      // a rejection, not a lost/unknown write and not permission to retry effects.
      throw new TypeError("Agentd browser output capacity occupied");
    }
    this.#nextOutgoingSequence++;
    this.#pendingWriteBytes += encoded.length;
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        this.#writes.delete(finish);
        this.#pendingWriteBytes -= encoded.length;
        if (error) this.#fail(error);
        if (this.#failed) reject(this.#failed);
        else resolve();
      };
      this.#writes.add(finish);
      try {
        this.#output.write(encoded, finish);
      } catch (error) {
        finish(error);
      }
    });
  }

  #onBytes(chunk) {
    if (this.#failed || this.#ended) return;
    try {
      const frames = this.#decoder.push(chunk);
      let nextSequence = this.#nextIncomingSequence;
      // Validate the entire decoded batch before resolving any reader. A valid
      // authority_enter prefix followed by a replay must not release a callback.
      for (const frame of frames) {
        if (frame.sequence !== nextSequence++) {
          throw new TypeError("Agentd browser input sequence is not monotonic");
        }
      }
      const pending = frames.slice(this.#waiters.length).map((frame) => ({
        frame,
        bytes: Buffer.byteLength(canonicalAgentdBrowserJson(frame), "utf8") + 4,
      }));
      const pendingBytes = pending.reduce((sum, entry) => sum + entry.bytes, 0);
      if (this.#queue.length + pending.length > 64 || this.#queuedBytes + pendingBytes > 4 * 1_048_576) {
        throw new TypeError("Agentd browser receive queue exceeds capacity");
      }
      this.#nextIncomingSequence = nextSequence;
      for (const frame of frames.slice(0, this.#waiters.length)) {
        this.#waiters.shift().resolve(frame);
      }
      this.#queue.push(...pending);
      this.#queuedBytes += pendingBytes;
    } catch (error) {
      this.#fail(error);
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
    // A queued request cannot cross authority after its parent has left. EOF
    // also cannot acknowledge an output write whose callback never arrived.
    this.#queue = [];
    this.#queuedBytes = 0;
    if (this.#writes.size) {
      this.#fail(new AgentdBrowserChannelClosed("Agentd browser input ended before output acknowledgement"));
      return;
    }
    for (const waiter of this.#waiters.splice(0)) waiter.resolve(null);
  }

  #checkStreams() {
    // destroy() changes these flags before the asynchronous close event. Check
    // them at actual use as well as construction, not just in event callbacks.
    if (this.#failed || this.#ended) return;
    if (this.#input.destroyed || this.#input.closed || this.#input.readableEnded) {
      this.#streamClosed("input");
    } else if (this.#output.destroyed || this.#output.closed || this.#output.writableEnded) {
      this.#streamClosed("output");
    }
  }

  #streamClosed(side) {
    // Normal retirement after an already observed idle EOF remains a clean end.
    if (this.#ended && this.#writes.size === 0) return;
    this.#fail(new AgentdBrowserChannelClosed(`Agentd browser ${side} stream closed`));
  }

  #fail(error) {
    if (this.#failed) return;
    this.#failed = error instanceof Error ? error : new Error(String(error));
    this.#queue = [];
    this.#queuedBytes = 0;
    for (const waiter of this.#waiters.splice(0)) waiter.reject(this.#failed);
    for (const finish of [...this.#writes]) finish(this.#failed);
  }
}

export class ParentFinalUseAuthority {
  #channel;
  #activeRequest = null;

  constructor(channel) {
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError("ParentFinalUseAuthority requires AgentdBrowserChannel");
    }
    this.#channel = channel;
  }

  async withRequest(requestId, call) {
    if (this.#activeRequest !== null) {
      throw new TypeError("browser service authority request is already active");
    }
    const scope = { requestId, controller: new AbortController(), used: false, pending: false };
    this.#activeRequest = scope;
    try {
      return await call();
    } finally {
      this.#activeRequest = null;
      scope.controller.abort();
      if (scope.pending) {
        // A late authority_enter cannot be assigned to another request, even
        // with reused IDs. The owner must reconcile over a new channel.
        this.#channel.invalidate(new Error("final-use exchange outlived its request scope"));
      }
    }
  }

  async withVerifiedUse(request, consumer) {
    requireRecord(request, "final-use request");
    const scope = this.#activeRequest;
    if (scope === null || scope.used) {
      throw new TypeError("final-use authority requires one unused active Agentd request");
    }
    if (typeof consumer !== "function") throw new TypeError("final-use consumer is required");
    scope.used = true;
    scope.pending = true;
    try {
      const requireActive = () => {
        this.#channel.assertUsable();
        if (this.#activeRequest !== scope || scope.controller.signal.aborted) {
          throw new TypeError("final-use authority request scope is closed");
        }
      };
      const requestId = scope.requestId;
      const requestDigest = digest(request.requestDigest, "requestDigest");
      const authorityEpoch = positiveInteger(request.authorityEpoch, "authorityEpoch");
      await this.#channel.send("authority_challenge", requestId, {
        request,
        requestDigest,
        authorityEpoch,
      });
      requireActive();
      const enter = await this.#channel.nextFrame({ signal: scope.controller.signal });
      requireActive();
      if (!enter || enter.kind !== "authority_enter" || enter.requestId !== requestId) {
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
      if (witness.requestDigest !== requestDigest || witness.authorityEpoch !== authorityEpoch) {
        throw new TypeError("Agentd final-use witness does not bind the Browser request");
      }
      requireActive();
      const result = await consumer(witness);
      requireActive();
      await this.#channel.send("dispatch_boundary", requestId, {
        requestDigest,
        witnessDigest: witness.witnessDigest,
        localDispatchCrossed: true,
      });
      return result;
    } finally {
      scope.pending = false;
    }
  }
}

export class BrowserAgentdService {
  #host;
  #channel;
  #authority;

  constructor({ host, channel, authority }) {
    // A selected host is an implementation object (BrowserProfileHost has
    // prototype methods), not an untrusted JSON payload. Keep wire records
    // strict while checking this owner against its executable method contract.
    if (host === null || typeof host !== "object" || Array.isArray(host)) {
      throw new TypeError("browser host must be an implementation object");
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
      if (typeof host[method] !== "function") throw new TypeError(`browser host.${method} is required`);
    }
    if (!(channel instanceof AgentdBrowserChannel)) {
      throw new TypeError("BrowserAgentdService requires AgentdBrowserChannel");
    }
    if (!(authority instanceof ParentFinalUseAuthority)) {
      throw new TypeError("BrowserAgentdService requires ParentFinalUseAuthority");
    }
    this.#host = host;
    this.#channel = channel;
    this.#authority = authority;
  }

  async run() {
    while (true) {
      let frame;
      try {
        frame = await this.#channel.nextFrame();
      } catch (error) {
        // Idle transport retirement stops the service. It emits no response and
        // does not settle an effect; closure during #serve still rejects there.
        if (error instanceof AgentdBrowserChannelClosed) return;
        throw error;
      }
      if (frame === null) return;
      this.#channel.assertUsable();
      if (frame.kind !== "request") {
        throw new TypeError("Browser service expected an Agentd request frame");
      }
      await this.#serve(frame);
    }
  }

  async #serve(frame) {
    try {
      const payload = requireRecord(frame.payload, "Browser service request payload");
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
      await this.#channel.send("response", frame.requestId, { ok: true, result });
    } catch (error) {
      await this.#channel.send("response", frame.requestId, {
        ok: false,
        error: boundedError(error),
      });
    }
  }
}
