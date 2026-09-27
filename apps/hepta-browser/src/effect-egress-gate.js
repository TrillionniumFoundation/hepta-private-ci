import { createHash } from "node:crypto";
import net from "node:net";
import { lstat, mkdtemp, rm, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Transform } from "node:stream";
import { performance } from "node:perf_hooks";

import { GrantScopedEgressBroker } from "./egress-broker.js";

const DEFAULT_MAX_REQUEST_BYTES = 1 * 1024 * 1024;
const DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
const MAX_HEADER_BYTES = 64 * 1024;
const HEADER_TIMEOUT_MS = 5_000;
const MAX_RECEIPTS = 256;
const MAX_COMPLETED_OPERATIONS = 65_536;
const MAX_CONNECTIONS = 64;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    /^0+$/.test(value)
  ) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positiveInteger(value, name, maximum = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${name} must be a bounded positive safe integer`);
  }
  return value;
}

function canonicalOrigin(value) {
  if (typeof value !== "string") {
    throw new TypeError("destinationOrigin must be a string");
  }
  const url = new URL(value);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.origin !== value ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new TypeError(
      "destinationOrigin must be a canonical HTTP(S) origin",
    );
  }
  return value;
}

function receiptDigest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function requestOriginFromHeader(header) {
  const firstLine = header.slice(0, header.indexOf("\r\n"));
  const parts = firstLine.split(" ");
  if (parts.length !== 3 || !/^HTTP\/1\.[01]$/.test(parts[2])) {
    throw new Error("egress proxy request line is invalid");
  }
  const [method, target] = parts;
  if (!/^[A-Z]{1,16}$/.test(method)) {
    throw new Error("egress proxy request method is invalid");
  }
  if (method === "CONNECT") {
    if (target.length < 1 || target.length > 4096) {
      throw new Error("egress CONNECT authority is outside bounds");
    }
    const url = new URL(`https://${target}`);
    if (
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    ) {
      throw new Error("egress CONNECT authority is invalid");
    }
    return url.origin;
  }
  const url = new URL(target);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  ) {
    throw new Error("egress proxy target is invalid");
  }
  return url.origin;
}

// A stream is not an authority scope: HTTP keep-alive/pipelining may contain
// multiple requests. Buffer each header until its origin and framing are checked.
class HttpOperationScopeGuard extends Transform {
  #origin;
  #assertLease;
  #maximum;
  #buffer = Buffer.alloc(0);
  #phase = "header";
  #remaining = 0;

  constructor(origin, assertLease, maximum) {
    super();
    this.#origin = origin;
    this.#assertLease = assertLease;
    this.#maximum = maximum;
  }

  #emit(length) {
    this.push(this.#buffer.subarray(0, length));
    this.#buffer = this.#buffer.subarray(length);
  }

  _transform(chunk, _encoding, callback) {
    try {
      this.#assertLease();
      this.#buffer = Buffer.concat([this.#buffer, chunk]);
      while (this.#buffer.length > 0) {
        this.#assertLease();
        if (this.#phase === "body" || this.#phase === "chunk-body") {
          const length = Math.min(this.#remaining, this.#buffer.length);
          this.#emit(length);
          this.#remaining -= length;
          if (this.#remaining > 0) break;
          this.#phase = this.#phase === "body" ? "header" : "chunk-end";
        } else if (this.#phase === "chunk-end") {
          if (this.#buffer.length < 2) break;
          if (this.#buffer.subarray(0, 2).toString("ascii") !== "\r\n") {
            throw new Error("egress chunk terminator is invalid");
          }
          this.#emit(2);
          this.#phase = "chunk-size";
        } else if (this.#phase === "chunk-size") {
          const end = this.#buffer.indexOf("\r\n");
          if (end < 0) {
            if (this.#buffer.length > 128) throw new Error("egress chunk size line is too large");
            break;
          }
          const line = this.#buffer.subarray(0, end).toString("latin1");
          if (end > 128 || !/^[0-9a-fA-F]+(?:;[\x20-\x7e]*)?$/.test(line)) {
            throw new Error("egress chunk size is invalid");
          }
          const length = Number.parseInt(line.split(";")[0], 16);
          if (!Number.isSafeInteger(length) || length > this.#maximum) {
            throw new Error("egress chunk exceeds request budget");
          }
          this.#emit(end + 2);
          this.#remaining = length;
          this.#phase = length === 0 ? "trailers" : "chunk-body";
        } else if (this.#phase === "trailers") {
          if (this.#buffer.length < 2) break;
          if (this.#buffer.subarray(0, 2).toString("ascii") === "\r\n") {
            this.#emit(2);
            this.#phase = "header";
            continue;
          }
          const end = this.#buffer.indexOf("\r\n\r\n");
          if (end < 0) {
            if (this.#buffer.length > MAX_HEADER_BYTES) throw new Error("egress trailers exceed limit");
            break;
          }
          if (end > MAX_HEADER_BYTES) throw new Error("egress trailers exceed limit");
          for (const line of this.#buffer.subarray(0, end).toString("latin1").split("\r\n")) {
            const match = /^([!#$%&'*+.^_`|~0-9A-Za-z-]+):[\t\x20-\x7e]*$/.exec(line);
            if (!match || /^(host|content-length|transfer-encoding|connection|upgrade|authorization|proxy-authorization)$/i.test(match[1])) {
              throw new Error("egress trailer may not change request authority or framing");
            }
          }
          this.#emit(end + 4);
          this.#phase = "header";
        } else {
          const end = this.#buffer.indexOf("\r\n\r\n");
          if (end < 0) {
            if (this.#buffer.length > MAX_HEADER_BYTES) throw new Error("egress request header exceeds limit");
            break;
          }
          if (end + 4 > MAX_HEADER_BYTES) throw new Error("egress request header exceeds limit");
          const header = this.#buffer.subarray(0, end + 4).toString("latin1");
          if (header.startsWith("CONNECT ") || requestOriginFromHeader(header) !== this.#origin) {
            throw new Error("pipelined request origin drifted from the admitted effect");
          }
          const headers = new Map();
          for (const line of header.split("\r\n").slice(1, -2)) {
            const match = /^([!#$%&'*+.^_`|~0-9A-Za-z-]+):[\t ]*([\t\x20-\x7e]*)$/.exec(line);
            if (!match) throw new Error("egress request header is malformed");
            const name = match[1].toLowerCase();
            const value = match[2].trim();
            if (headers.has(name) && ["host", "content-length", "transfer-encoding"].includes(name)) {
              throw new Error("egress request contains ambiguous framing");
            }
            headers.set(name, value);
          }
          const target = new URL(this.#origin);
          const host = headers.get("host");
          if (host !== target.host) throw new Error("egress Host drifted from the admitted effect");
          if (headers.has("upgrade") || /(?:^|,)\s*upgrade\s*(?:,|$)/i.test(headers.get("connection") ?? "")) {
            throw new Error("HTTP protocol upgrade is not an admitted egress capability");
          }
          const transfer = headers.get("transfer-encoding");
          const lengthText = headers.get("content-length");
          if (transfer !== undefined) {
            if (transfer.toLowerCase() !== "chunked" || lengthText !== undefined) {
              throw new Error("egress request contains ambiguous transfer framing");
            }
            this.#phase = "chunk-size";
          } else {
            if (lengthText !== undefined && !/^[0-9]+$/.test(lengthText)) {
              throw new Error("egress Content-Length is invalid");
            }
            const length = Number(lengthText ?? 0);
            if (!Number.isSafeInteger(length) || length > this.#maximum) {
              throw new Error("egress body exceeds request budget");
            }
            this.#remaining = length;
            this.#phase = length === 0 ? "header" : "body";
          }
          this.#emit(end + 4);
        }
      }
      callback();
    } catch (error) {
      callback(error);
    }
  }

  _flush(callback) {
    callback(this.#phase === "header" && this.#buffer.length === 0
      ? null : new Error("egress HTTP request ended with incomplete framing"));
  }
}

class ByteLimitTransform extends Transform {
  #maximum;
  #onBytes;
  #onExceeded;
  #total = 0;

  constructor({ maximum, onBytes, onExceeded }) {
    super();
    this.#maximum = maximum;
    this.#onBytes = onBytes;
    this.#onExceeded = onExceeded;
  }

  _transform(chunk, _encoding, callback) {
    this.#total += chunk.length;
    let aggregate;
    try {
      aggregate = this.#onBytes(chunk.length);
    } catch (error) {
      callback(error);
      return;
    }
    if (this.#total > this.#maximum || aggregate > this.#maximum) {
      this.#onExceeded(Math.max(this.#total, aggregate));
      const error = new Error("egress byte budget exceeded");
      error.code = "BROWSER_EGRESS_BYTE_BUDGET_EXCEEDED";
      callback(error);
      return;
    }
    callback(null, chunk);
  }
}

export class EffectScopedEgressBroker {
  #socketPath;
  #innerSocketPath;
  #manageInner;
  #profileGrantDigest;
  #allowedOrigins;
  #allowPrivateNetworkForTests;
  #resolver;
  #maxRequestBytes;
  #maxResponseBytes;
  #inner = null;
  #server = null;
  #sockets = new Set();
  #contexts = new Set();
  #active = null;
  #receipts = [];
  #completed = new Set();
  #expiryTimer = null;
  #innerPrivateDir = null;
  #starting = false;

  constructor({
    socketPath,
    upstreamSocketPath,
    grantDigest,
    allowedOrigins,
    allowPrivateNetworkForTests = false,
    resolver,
    maxRequestBytes = DEFAULT_MAX_REQUEST_BYTES,
    maxResponseBytes = DEFAULT_MAX_RESPONSE_BYTES,
  }) {
    if (typeof socketPath !== "string" || socketPath.length === 0) {
      throw new TypeError("effect egress socketPath must be a non-empty string");
    }
    if (
      upstreamSocketPath !== undefined &&
      (typeof upstreamSocketPath !== "string" || upstreamSocketPath.length === 0)
    ) {
      throw new TypeError(
        "effect egress upstreamSocketPath must be a non-empty string",
      );
    }
    this.#socketPath = socketPath;
    this.#manageInner = upstreamSocketPath === undefined;
    this.#innerSocketPath = upstreamSocketPath ?? null;
    if (this.#innerSocketPath === this.#socketPath) {
      throw new TypeError(
        "effect egress public and policy socket paths must differ",
      );
    }
    this.#profileGrantDigest = digest(grantDigest, "grantDigest");
    if (!Array.isArray(allowedOrigins) || allowedOrigins.length > 128) {
      throw new TypeError("allowedOrigins must be a bounded array");
    }
    this.#allowedOrigins = [...allowedOrigins].map(canonicalOrigin);
    if (new Set(this.#allowedOrigins).size !== this.#allowedOrigins.length) {
      throw new TypeError("allowedOrigins contains duplicates");
    }
    if (typeof allowPrivateNetworkForTests !== "boolean") {
      throw new TypeError("allowPrivateNetworkForTests must be boolean");
    }
    if (resolver !== undefined && typeof resolver !== "function") {
      throw new TypeError("resolver must be a function when supplied");
    }
    this.#allowPrivateNetworkForTests = allowPrivateNetworkForTests;
    this.#resolver = resolver;
    this.#maxRequestBytes = positiveInteger(
      maxRequestBytes,
      "maxRequestBytes",
      16 * 1024 * 1024,
    );
    this.#maxResponseBytes = positiveInteger(
      maxResponseBytes,
      "maxResponseBytes",
      1024 * 1024 * 1024,
    );
  }

  get receipts() {
    return this.#receipts.map((receipt) => Object.freeze({ ...receipt }));
  }

  get observations() {
    return this.#inner?.observations ?? [];
  }

  async start() {
    if (this.#server !== null || this.#starting) {
      throw new TypeError("effect egress broker is already started");
    }
    this.#starting = true;
    try {
      await unlink(this.#socketPath).catch((error) => {
        if (error?.code !== "ENOENT") throw error;
      });

      let inner = null;
      if (this.#manageInner) {
        // Only the public socket belongs inside the worker's profile bind.
        // The policy socket must not be another route around operation admission.
        this.#innerPrivateDir = await mkdtemp(
          join(dirname(dirname(this.#socketPath)), ".hepta-egress-"),
        );
        this.#innerSocketPath = join(this.#innerPrivateDir, "policy.sock");
        await unlink(this.#innerSocketPath).catch((error) => {
          if (error?.code !== "ENOENT") throw error;
        });
        const options = {
          socketPath: this.#innerSocketPath,
          grantDigest: this.#profileGrantDigest,
          allowedOrigins: this.#allowedOrigins,
          allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
        };
        if (this.#resolver !== undefined) options.resolver = this.#resolver;
        inner = new GrantScopedEgressBroker(options);
        await inner.start();
      } else {
        const metadata = await lstat(this.#innerSocketPath);
        if (!metadata.isSocket() || metadata.isSymbolicLink()) {
          throw new TypeError(
            "effect egress policy endpoint must be a non-symlink Unix socket",
          );
        }
      }

      const server = net.createServer({ allowHalfOpen: true }, (client) => {
        client.on("error", () => {});
        if (this.#contexts.size >= MAX_CONNECTIONS) {
          client.destroy();
          return;
        }
        this.#sockets.add(client);
        client.once("close", () => this.#sockets.delete(client));
        this.#accept(client).catch((error) => {
          if (!client.destroyed) client.destroy(error);
        });
      });
      server.maxConnections = MAX_CONNECTIONS;
      try {
        await new Promise((resolve, reject) => {
          server.once("error", reject);
          server.listen(this.#socketPath, () => {
            server.off("error", reject);
            resolve();
          });
        });
      } catch (error) {
        await inner?.close().catch(() => {});
        throw error;
      }
      this.#inner = inner;
      this.#server = server;
    } catch (error) {
      if (this.#innerPrivateDir !== null) {
        await rm(this.#innerPrivateDir, { recursive: true, force: true });
        this.#innerPrivateDir = null;
      }
      throw error;
    } finally {
      this.#starting = false;
    }
  }

  admitOperation({
    operationId,
    effectGrantDigest,
    destinationOrigin,
    deadlineMs,
  }) {
    if (this.#server === null) {
      throw new TypeError("effect egress broker is not started");
    }
    const next = Object.freeze({
      operationId: stableId(operationId, "operationId"),
      effectGrantDigest: digest(effectGrantDigest, "effectGrantDigest"),
      destinationOrigin: canonicalOrigin(destinationOrigin),
      deadlineMs: positiveInteger(deadlineMs, "deadlineMs"),
      admittedAtMs: Date.now(),
      requestBytes: 0,
      responseBytes: 0,
      connectionCount: 0,
      boundedAbort: false,
    });
    if (!this.#allowedOrigins.includes(next.destinationOrigin)) {
      throw new TypeError(
        "effect destination is outside the profile network grant",
      );
    }
    if (next.deadlineMs <= Date.now()) {
      throw new TypeError("effect network grant has expired");
    }
    if (this.#active !== null) {
      if (
        this.#active.operationId === next.operationId &&
        this.#active.effectGrantDigest === next.effectGrantDigest &&
        this.#active.destinationOrigin === next.destinationOrigin &&
        this.#active.deadlineMs === next.deadlineMs
      ) {
        return;
      }
      throw new TypeError("another browser effect owns the egress gate");
    }
    if (this.#completed.has(next.operationId)) {
      throw new TypeError("completed egress identity cannot be readmitted; reconcile the original operation");
    }
    if (this.#completed.size >= MAX_COMPLETED_OPERATIONS) {
      throw new TypeError("egress operation identity capacity exhausted");
    }
    this.#active = {
      ...next,
      connectionAttempts: 0,
      monotonicDeadline: performance.now() + (next.deadlineMs - Date.now()),
    };
    this.#armExpiry(this.#active);
  }

  completeOperation(operationId, { status = "completed" } = {}) {
    const id = stableId(operationId, "operationId");
    const prior = [...this.#receipts]
      .reverse()
      .find((receipt) => receipt.operationId === id);
    // A delayed settlement belongs to its original operation, never to the
    // currently active replacement. Preserve the first terminal network receipt.
    if (prior) return prior;
    if (this.#active === null) {
      throw new TypeError("effect egress operation is not active");
    }
    if (this.#active.operationId !== id) {
      throw new TypeError("effect egress operation identity mismatch");
    }
    clearTimeout(this.#expiryTimer);
    this.#expiryTimer = null;
    for (const context of [...this.#contexts]) {
      if (context.operationId !== id) continue;
      context.client.destroy();
      context.upstream?.destroy();
    }
    const unsigned = Object.freeze({
      schema: "hepta.browser.egress-operation-receipt.v1",
      operationId: this.#active.operationId,
      profileGrantDigest: this.#profileGrantDigest,
      effectGrantDigest: this.#active.effectGrantDigest,
      destinationOrigin: this.#active.destinationOrigin,
      status: String(status).slice(0, 64),
      admittedAtMs: this.#active.admittedAtMs,
      completedAtMs: Date.now(),
      requestBytes: this.#active.requestBytes,
      responseBytes: this.#active.responseBytes,
      connectionCount: this.#active.connectionCount,
      boundedAbort: this.#active.boundedAbort,
      maxRequestBytes: this.#maxRequestBytes,
      maxResponseBytes: this.#maxResponseBytes,
    });
    const receipt = Object.freeze({
      ...unsigned,
      receiptDigest: receiptDigest(unsigned),
    });
    this.#completed.add(id);
    this.#receipts.push(receipt);
    if (this.#receipts.length > MAX_RECEIPTS) this.#receipts.shift();
    this.#active = null;
    return receipt;
  }

  async close({ status = "profile_closed" } = {}) {
    clearTimeout(this.#expiryTimer);
    this.#expiryTimer = null;
    if (this.#active !== null) {
      this.completeOperation(this.#active.operationId, { status });
    }
    const server = this.#server;
    this.#server = null;
    for (const context of [...this.#contexts]) {
      context.client.destroy();
      context.upstream?.destroy();
    }
    for (const socket of this.#sockets) socket.destroy();
    this.#sockets.clear();
    if (server !== null) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
    const inner = this.#inner;
    this.#inner = null;
    await inner?.close();
    if (this.#innerPrivateDir !== null) {
      await rm(this.#innerPrivateDir, { recursive: true, force: true });
      this.#innerPrivateDir = null;
    }
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }

  #assertActive(active) {
    if (active === null || this.#active !== active || active.boundedAbort) {
      throw new Error("browser network request has no live admitted effect operation");
    }
    if (Date.now() >= active.deadlineMs || performance.now() >= active.monotonicDeadline) {
      throw new Error("browser effect network grant has expired");
    }
  }

  #armExpiry(active) {
    const expire = () => {
      if (this.#active !== active) return;
      const remaining = Math.min(
        active.deadlineMs - Date.now(),
        active.monotonicDeadline - performance.now(),
      );
      if (remaining <= 0) {
        active.boundedAbort = true;
        this.completeOperation(active.operationId, { status: "lease_expired" });
        return;
      }
      this.#expiryTimer = setTimeout(expire, Math.min(Math.ceil(remaining), 2_147_000_000));
      this.#expiryTimer.unref?.();
    };
    expire();
  }

  async #accept(client) {
    const active = this.#active;
    this.#assertActive(active);
    if (active.connectionAttempts >= MAX_CONNECTIONS) {
      throw new Error("effect egress connection budget exhausted");
    }
    active.connectionAttempts += 1;
    // Register even partial-header connections so expiry closes every socket.
    const context = { operationId: active.operationId, client, upstream: null, finished: false };
    this.#contexts.add(context);
    const finish = () => {
      if (context.finished) return;
      context.finished = true;
      this.#contexts.delete(context);
      client.destroy();
      context.upstream?.destroy();
    };
    client.once("close", finish);
    const initial = await this.#readHeader(client);
    this.#assertActive(active);
    const headerEnd = initial.indexOf("\r\n\r\n");
    const origin = requestOriginFromHeader(
      initial.subarray(0, headerEnd + 4).toString("latin1"),
    );
    if (origin !== active.destinationOrigin) {
      throw new Error("browser network request origin drifted from the admitted effect");
    }

    active.connectionCount += 1;
    const upstream = net.createConnection(this.#innerSocketPath);
    context.upstream = upstream;
    this.#sockets.add(upstream);
    upstream.on("error", finish);
    upstream.once("close", () => {
      this.#sockets.delete(upstream);
      finish();
    });
    await new Promise((resolve, reject) => {
      let timer;
      const settle = (error) => {
        clearTimeout(timer);
        upstream.off("connect", connected);
        upstream.off("error", failed);
        upstream.off("close", closed);
        if (error) reject(error); else resolve();
      };
      const connected = () => settle();
      const failed = (error) => settle(error);
      const closed = () => settle(new Error("policy channel closed before forwarding"));
      upstream.once("connect", connected);
      upstream.once("error", failed);
      upstream.once("close", closed);
      timer = setTimeout(() => {
        settle(new Error("policy channel connect deadline exceeded"));
        finish();
      }, HEADER_TIMEOUT_MS);
    });
    this.#assertActive(active);
    if (client.destroyed) {
      finish();
      throw new Error("worker connection closed before forwarding");
    }

    const exceeded = () => {
      active.boundedAbort = true;
      for (const current of this.#contexts) {
        if (current.operationId !== active.operationId) continue;
        current.client.destroy();
        current.upstream?.destroy();
      }
    };
    const requests = new ByteLimitTransform({
      maximum: this.#maxRequestBytes,
      onBytes: (bytes) => {
        this.#assertActive(active);
        active.requestBytes += bytes;
        return active.requestBytes;
      },
      onExceeded: exceeded,
    });
    const responses = new ByteLimitTransform({
      maximum: this.#maxResponseBytes,
      onBytes: (bytes) => {
        this.#assertActive(active);
        active.responseBytes += bytes;
        return active.responseBytes;
      },
      onExceeded: exceeded,
    });
    for (const stream of [client, upstream, requests, responses]) {
      stream.on("error", () => {
        client.destroy();
        upstream.destroy();
      });
    }

    const isConnect = initial.subarray(0, 8).toString("ascii") === "CONNECT ";
    if (isConnect) {
      requests.write(initial);
      client.pipe(requests).pipe(upstream);
    } else {
      const scope = new HttpOperationScopeGuard(
        active.destinationOrigin, () => this.#assertActive(active), this.#maxRequestBytes,
      );
      scope.on("error", finish);
      scope.write(initial);
      client.pipe(scope).pipe(requests).pipe(upstream, { end: false });
    }
    if (isConnect) {
      client.once("end", finish);
      if (client.readableEnded) finish();
    }
    upstream.pipe(responses).pipe(client);
    client.resume();
  }

  #readHeader(client) {
    return new Promise((resolve, reject) => {
      let buffer = Buffer.alloc(0);
      let settled = false;
      let timer;
      const cleanup = () => {
        clearTimeout(timer);
        client.off("data", onData);
        client.off("error", onError);
        client.off("close", onClose);
      };
      const finish = (error, value = null) => {
        if (settled) return;
        settled = true;
        cleanup();
        if (error) reject(error);
        else resolve(value);
      };
      const onData = (chunk) => {
        client.pause();
        buffer = Buffer.concat([buffer, chunk]);
        const headerEnd = buffer.indexOf("\r\n\r\n");
        if (headerEnd >= 0) {
          if (headerEnd + 4 > MAX_HEADER_BYTES) {
            finish(new Error("egress proxy header exceeds byte limit"));
          } else {
            finish(null, buffer);
          }
          return;
        }
        if (buffer.length > MAX_HEADER_BYTES) {
          finish(new Error("egress proxy header exceeds byte limit"));
          return;
        }
        client.resume();
      };
      const onError = (error) => finish(error);
      const onClose = () =>
        finish(new Error("egress proxy connection closed before request header"));
      timer = setTimeout(
        () => finish(new Error("egress proxy request header timed out")),
        HEADER_TIMEOUT_MS,
      );
      client.pause();
      client.on("data", onData);
      client.once("error", onError);
      client.once("close", onClose);
      client.resume();
    });
  }
}
