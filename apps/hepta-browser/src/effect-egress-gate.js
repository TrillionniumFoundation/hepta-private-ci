import { createHash } from "node:crypto";
import net from "node:net";
import { lstat, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import { Transform } from "node:stream";

import { GrantScopedEgressBroker } from "./egress-broker.js";

const DEFAULT_MAX_REQUEST_BYTES = 1 * 1024 * 1024;
const DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
const MAX_HEADER_BYTES = 64 * 1024;
const HEADER_TIMEOUT_MS = 5_000;
const MAX_RECEIPTS = 256;
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
    const aggregate = this.#onBytes(chunk.length);
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
    this.#innerSocketPath =
      upstreamSocketPath ??
      join(dirname(socketPath), ".hepta-egress-policy.sock");
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
    if (this.#server !== null) {
      throw new TypeError("effect egress broker is already started");
    }
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });

    let inner = null;
    if (this.#manageInner) {
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

    const server = net.createServer((client) => {
      this.#sockets.add(client);
      client.once("close", () => this.#sockets.delete(client));
      this.#accept(client).catch((error) => {
        if (!client.destroyed) client.destroy(error);
      });
    });
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
    this.#active = { ...next };
  }

  completeOperation(operationId, { status = "completed" } = {}) {
    const id = stableId(operationId, "operationId");
    const prior = [...this.#receipts]
      .reverse()
      .find((receipt) => receipt.operationId === id);
    if (this.#active === null) {
      if (prior) return prior;
      throw new TypeError("effect egress operation is not active");
    }
    if (this.#active.operationId !== id) {
      throw new TypeError("effect egress operation identity mismatch");
    }
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
    this.#receipts.push(receipt);
    if (this.#receipts.length > MAX_RECEIPTS) this.#receipts.shift();
    this.#active = null;
    return receipt;
  }

  async close() {
    if (this.#active !== null) {
      this.completeOperation(this.#active.operationId, {
        status: "profile_closed",
      });
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
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }

  async #accept(client) {
    const active = this.#active;
    if (active === null) {
      throw new Error("browser network request has no admitted effect operation");
    }
    if (Date.now() >= active.deadlineMs) {
      throw new Error("browser effect network grant has expired");
    }
    const initial = await this.#readHeader(client);
    if (this.#active !== active) {
      throw new Error("browser effect egress ownership changed during admission");
    }
    const headerEnd = initial.indexOf("\r\n\r\n");
    const origin = requestOriginFromHeader(
      initial.subarray(0, headerEnd + 4).toString("latin1"),
    );
    if (origin !== active.destinationOrigin) {
      throw new Error(
        "browser network request origin drifted from the admitted effect",
      );
    }

    active.connectionCount += 1;
    const context = {
      operationId: active.operationId,
      client,
      upstream: null,
      finished: false,
    };
    this.#contexts.add(context);
    const finish = () => {
      if (context.finished) return;
      context.finished = true;
      this.#contexts.delete(context);
    };
    client.once("close", finish);

    const upstream = net.createConnection(this.#innerSocketPath);
    context.upstream = upstream;
    this.#sockets.add(upstream);
    upstream.once("close", () => {
      this.#sockets.delete(upstream);
      finish();
    });
    await new Promise((resolve, reject) => {
      upstream.once("connect", resolve);
      upstream.once("error", reject);
    });
    if (this.#active !== active) {
      upstream.destroy();
      throw new Error("browser effect egress ownership changed before forwarding");
    }

    const exceeded = () => {
      active.boundedAbort = true;
      client.destroy();
      upstream.destroy();
    };
    const requests = new ByteLimitTransform({
      maximum: this.#maxRequestBytes,
      onBytes: (bytes) => {
        active.requestBytes += bytes;
        return active.requestBytes;
      },
      onExceeded: exceeded,
    });
    const responses = new ByteLimitTransform({
      maximum: this.#maxResponseBytes,
      onBytes: (bytes) => {
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

    requests.write(initial);
    client.pipe(requests).pipe(upstream);
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
        if (buffer.length > MAX_HEADER_BYTES) {
          finish(new Error("egress proxy header exceeds byte limit"));
          return;
        }
        if (buffer.indexOf("\r\n\r\n") >= 0) {
          finish(null, buffer);
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
