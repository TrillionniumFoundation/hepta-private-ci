// Private transport implementation for SubprocessBrowserDriver. This owns no
// authority, operation journal or resource-settlement proof. Poisoning prevents
// further writes; only the process owner can establish physical retirement.
import { createHash } from "node:crypto";
import { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame } from "./worker-protocol.js";

const MAX_PENDING = 8;
const MAX_PENDING_BYTES = 4 * 1_048_576;
const MAX_ABANDONED = 1024;
const MAX_DIAGNOSTIC_BYTES = 16_384;

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)
      || Object.getPrototypeOf(value) !== Object.prototype) {
    throw new TypeError(`${name} must be a plain object`);
  }
  return value;
}

function abortError() {
  const error = new Error("browser worker request aborted");
  error.name = "AbortError";
  return error;
}

export class PrivateWorkerClient {
  #child;
  #sessionId;
  #generation;
  #decoder = new WorkerFrameDecoder();
  #nextOutgoingSequence = 1;
  #lastIncomingSequence = 0;
  #pending = new Map();
  #abandoned = new Set();
  #writes = new Set();
  #pendingBytes = 0;
  #diagnosticBytes = 0;
  #failure = null;
  #exited = false;

  constructor({ child, sessionId, generation }) {
    this.#child = child;
    this.#sessionId = sessionId;
    this.#generation = generation;
    child.stdout.on("data", (chunk) => this.#onBytes(chunk));
    child.stdout.on("close", () => this.#fail(new Error("browser worker response stream closed")));
    child.stdin.on("close", () => this.#fail(new Error("browser worker request stream closed")));
    child.stdin.on("finish", () => this.#fail(new Error("browser worker request stream finished")));
    child.stdout.on("end", () => {
      try { this.#decoder.end(); }
      catch (error) { this.#fail(error); return; }
      this.#fail(new Error("browser worker response stream ended"));
    });
    for (const stream of [child.stdin, child.stdout, child.stderr]) {
      stream?.on("error", (error) => this.#fail(error));
    }
    child.stderr?.on("data", (chunk) => {
      // Drain the pipe, but never retain or publish raw diagnostics.
      if (this.#failure) return;
      this.#diagnosticBytes += chunk.byteLength;
      if (this.#diagnosticBytes > MAX_DIAGNOSTIC_BYTES) {
        this.#fail(new Error("browser worker diagnostic capacity exhausted"));
      }
    });
    child.on("error", (error) => this.#fail(error));
    child.on("exit", (code, signal) => {
      this.#exited = true;
      this.#fail(new Error(`browser worker exited: code=${code} signal=${signal}`));
    });
    this.#checkStreams();
  }

  request(kind, semanticId, payload, { signal, onDispatched } = {}) {
    this.#checkStreams();
    if (this.#failure) return Promise.reject(this.#failure);
    if (signal?.aborted) return Promise.reject(abortError());
    const digest = createHash("sha256").update(`${kind}\u0000${semanticId}`).digest("hex");
    const id = `browser.${kind}.${digest.slice(0, 32)}`;
    if (this.#pending.has(id) || this.#abandoned.has(id)) {
      return Promise.reject(new TypeError("browser worker request identity is already live"));
    }
    if (this.#pending.size >= MAX_PENDING || this.#writes.size >= MAX_PENDING) {
      return Promise.reject(new TypeError("browser worker pending request capacity exhausted"));
    }
    let encoded;
    try {
      encoded = encodeWorkerFrame(buildWorkerFrame({ sessionId: this.#sessionId,
        generation: this.#generation, sequence: this.#nextOutgoingSequence,
        kind, requestId: id, payload }));
    } catch (error) {
      return Promise.reject(error);
    }
    if (this.#pendingBytes + encoded.length > MAX_PENDING_BYTES) {
      return Promise.reject(new TypeError("browser worker pending output byte capacity exhausted"));
    }
    return new Promise((resolve, reject) => {
      let writeStarted = false;
      const entry = { resolve, reject, cleanup: null };
      const abort = () => {
        if (this.#pending.get(id) !== entry) return;
        this.#pending.delete(id);
        entry.cleanup?.();
        if (writeStarted) {
          // A complete later reply may be discarded, never transferred to a
          // new same-ID operation. Durable outcome/retry decisions stay outside.
          if (this.#abandoned.size >= MAX_ABANDONED) {
            this.#fail(new Error("browser worker abandoned-response capacity exhausted"));
          } else this.#abandoned.add(id);
        }
        reject(abortError());
      };
      this.#pending.set(id, entry);
      if (signal) {
        signal.addEventListener("abort", abort, { once: true });
        entry.cleanup = () => signal.removeEventListener("abort", abort);
        if (signal.aborted) { abort(); return; }
      }
      let writeFinished = false;
      const finish = (error) => {
        if (writeFinished) return;
        writeFinished = true;
        this.#writes.delete(finish);
        this.#pendingBytes -= encoded.length;
        if (error) { this.#fail(error); return; }
        // Cancellation, terminal reply or channel poison closes the callback's
        // lifetime, including reuse of the same string ID by a later request.
        this.#checkStreams();
        if (this.#failure || this.#pending.get(id) !== entry) return;
        try { onDispatched?.(); }
        catch (callbackError) { this.#fail(callbackError); }
      };
      this.#writes.add(finish);
      this.#pendingBytes += encoded.length;
      this.#nextOutgoingSequence++;
      writeStarted = true;
      try { this.#child.stdin.write(encoded, finish); }
      catch (error) { finish(error); }
    });
  }

  close() {
    this.#fail(new Error("browser worker channel closed"));
    try { this.#child.stdin.end(); } catch { /* admission is already closed */ }
  }

  #onBytes(chunk) {
    this.#checkStreams();
    if (this.#failure) return;
    try {
      const frames = this.#decoder.push(chunk);
      let sequence = this.#lastIncomingSequence;
      const seen = new Set();
      const deliveries = [];
      // Validate the whole decoded batch before resolving even one promise.
      // A valid prefix must not escape a later replay or malformed observation.
      for (const frame of frames) {
        if (frame.sessionId !== this.#sessionId || frame.generation !== this.#generation) {
          throw new TypeError("browser worker response crossed session or generation");
        }
        if (frame.sequence !== ++sequence) {
          throw new TypeError("browser worker response sequence is not monotonic");
        }
        if (frame.kind !== "response" || seen.has(frame.requestId)) {
          throw new TypeError("browser worker emitted an unexpected or repeated response");
        }
        seen.add(frame.requestId);
        const pending = this.#pending.get(frame.requestId);
        if (!pending && !this.#abandoned.has(frame.requestId)) {
          throw new TypeError("browser worker response has no pending request");
        }
        const payload = record(frame.payload, "worker response payload");
        let observation;
        let rejection;
        if (payload.ok === true) observation = record(payload.observation, "worker observation");
        else if (payload.ok === false && typeof payload.error === "string") {
          rejection = new Error(`browser worker rejected request: ${payload.error}`);
        } else throw new TypeError("browser worker response payload is invalid");
        deliveries.push({ id: frame.requestId, pending, observation, rejection });
      }
      this.#lastIncomingSequence = sequence;
      for (const { id, pending, observation, rejection } of deliveries) {
        if (!pending) { this.#abandoned.delete(id); continue; }
        this.#pending.delete(id);
        pending.cleanup?.();
        if (rejection) pending.reject(rejection);
        else pending.resolve(observation);
      }
    } catch (error) { this.#fail(error); }
  }

  #checkStreams() {
    // A real stream can mark itself destroyed/ended before emitting close.
    // Neither a late write callback nor a buffered reply may cross that fence.
    if (this.#failure) return;
    const { stdin, stdout } = this.#child;
    if (stdin.destroyed || stdin.closed || stdin.writableEnded
        || stdout.destroyed || stdout.closed || stdout.readableEnded) {
      this.#fail(new Error("browser worker transport stream is closed"));
    }
  }

  #fail(error) {
    if (this.#failure) return;
    this.#failure = error instanceof Error ? error : new Error(String(error));
    for (const pending of this.#pending.values()) {
      pending.cleanup?.();
      pending.reject(this.#failure);
    }
    this.#pending.clear();
    this.#abandoned.clear();
    for (const finish of [...this.#writes]) finish(this.#failure);
    // Signalling is best effort, NOT observed exit or resource reclamation.
    // Keep the child owned by SubprocessBrowserDriver even when kill fails.
    if (!this.#exited) {
      try { this.#child.kill("SIGKILL"); } catch { /* owner must reconcile cleanup */ }
    }
  }
}
