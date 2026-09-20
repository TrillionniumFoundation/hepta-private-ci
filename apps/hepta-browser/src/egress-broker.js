import { createHash } from "node:crypto";
import { lookup as dnsLookupCallback } from "node:dns";
import http from "node:http";
import https from "node:https";
import { BlockList, isIP } from "node:net";

const REQUEST_SCHEMA = "hepta.browser.egress-request.v1";
const RESPONSE_SCHEMA = "hepta.browser.egress-response.v1";
const MAX_REQUEST_FRAME_BYTES = 256 * 1024;
const MAX_RESPONSE_FRAME_BYTES = 12 * 1024 * 1024;
const MAX_RESPONSE_BODY_BYTES = 8 * 1024 * 1024;
const MAX_HEADERS = 256;
const MAX_HEADER_BYTES = 16 * 1024;
const MAX_DNS_ANSWERS = 16;
const DIGEST = /^[0-9a-f]{64}$/;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;

const deniedAddresses = new BlockList();
for (const [address, prefix] of [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
]) deniedAddresses.addSubnet(address, prefix, "ipv4");
for (const [address, prefix] of [
  ["::", 128],
  ["::1", 128],
  ["fc00::", 7],
  ["fe80::", 10],
  ["ff00::", 8],
]) deniedAddresses.addSubnet(address, prefix, "ipv6");

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, i) => key !== wanted[i])) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function canonicalOrigin(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new TypeError("egress origin must be credential-free HTTP(S)");
  }
  return url.origin;
}

function canonicalUrl(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new TypeError("egress URL must be credential-free HTTP(S)");
  }
  return url;
}

function normalizeAddress(value) {
  if (typeof value !== "string" || isIP(value) === 0) {
    throw new TypeError("network address must be an IP literal");
  }
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function safeError(error) {
  return String(error?.message ?? error).replace(/[\r\n\0]/g, " ").slice(0, 512);
}

function boundedHeaderPairs(value, name) {
  if (!Array.isArray(value) || value.length > MAX_HEADERS) {
    throw new TypeError(`${name} must be a bounded header array`);
  }
  let bytes = 0;
  const output = [];
  for (const pair of value) {
    if (!Array.isArray(pair) || pair.length !== 2) {
      throw new TypeError(`${name} entries must be [name,value]`);
    }
    const [headerName, headerValue] = pair;
    if (
      typeof headerName !== "string" ||
      typeof headerValue !== "string" ||
      headerName.length === 0 ||
      /[\r\n\0]/.test(headerName) ||
      /[\r\n\0]/.test(headerValue)
    ) {
      throw new TypeError(`${name} contains an invalid header`);
    }
    bytes += Buffer.byteLength(headerName) + Buffer.byteLength(headerValue);
    if (bytes > MAX_HEADER_BYTES) {
      throw new TypeError(`${name} exceeds the header byte ceiling`);
    }
    output.push([headerName.toLowerCase(), headerValue]);
  }
  return output;
}

function responseHeaders(headers) {
  const output = [];
  let bytes = 0;
  for (const [name, raw] of Object.entries(headers)) {
    if (raw === undefined) continue;
    if (["connection", "transfer-encoding", "keep-alive", "proxy-connection"].includes(name)) {
      continue;
    }
    for (const value of Array.isArray(raw) ? raw : [raw]) {
      const text = String(value);
      bytes += Buffer.byteLength(name) + Buffer.byteLength(text);
      if (output.length >= MAX_HEADERS || bytes > MAX_HEADER_BYTES) {
        throw new TypeError("egress response headers exceed the bound");
      }
      output.push([name.toLowerCase(), text]);
    }
  }
  return output;
}

function encodeFrame(value, maximum = MAX_RESPONSE_FRAME_BYTES) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  if (body.length === 0 || body.length > maximum) {
    throw new TypeError("egress frame exceeds the byte limit");
  }
  const frame = Buffer.allocUnsafe(body.length + 4);
  frame.writeUInt32BE(body.length, 0);
  body.copy(frame, 4);
  return frame;
}

class FrameDecoder {
  #buffer = Buffer.alloc(0);
  #maximum;
  constructor(maximum = MAX_REQUEST_FRAME_BYTES) {
    this.#maximum = maximum;
  }
  push(chunk) {
    this.#buffer = Buffer.concat([this.#buffer, Buffer.from(chunk)]);
    const frames = [];
    for (;;) {
      if (this.#buffer.length < 4) break;
      const length = this.#buffer.readUInt32BE(0);
      if (length === 0 || length > this.#maximum) {
        throw new TypeError("egress frame length is invalid");
      }
      if (this.#buffer.length < length + 4) break;
      const raw = this.#buffer.subarray(4, length + 4);
      this.#buffer = this.#buffer.subarray(length + 4);
      let value;
      try {
        value = JSON.parse(raw.toString("utf8"));
      } catch {
        throw new TypeError("egress frame is not valid JSON");
      }
      frames.push(record(value, "egress frame"));
    }
    return frames;
  }
}

export class GrantScopedEgressBroker {
  #requestStream;
  #responseStream;
  #profileGrantDigest;
  #allowedOrigins;
  #allowedNetworkAddresses;
  #authorities = new Map();
  #expectedRedirects = new Set();
  #decoder = new FrameDecoder();
  #nextSequence = 1;
  #tail = Promise.resolve();
  #closed = false;
  #dnsLookup;
  #maxResponseBytes;

  constructor({
    requestStream,
    responseStream,
    profileGrantDigest,
    allowedOrigins,
    allowedNetworkAddresses = [],
    dnsLookup = dnsLookupCallback,
    maxResponseBytes = MAX_RESPONSE_BODY_BYTES,
  }) {
    if (!requestStream?.on || typeof responseStream?.write !== "function") {
      throw new TypeError("egress broker requires private request/response pipes");
    }
    this.#requestStream = requestStream;
    this.#responseStream = responseStream;
    this.#profileGrantDigest = digest(profileGrantDigest, "profileGrantDigest");
    if (!Array.isArray(allowedOrigins) || allowedOrigins.length > 128) {
      throw new TypeError("allowedOrigins must be bounded");
    }
    this.#allowedOrigins = new Set(allowedOrigins.map(canonicalOrigin));
    if (!Array.isArray(allowedNetworkAddresses) || allowedNetworkAddresses.length > 256) {
      throw new TypeError("allowedNetworkAddresses must be bounded");
    }
    this.#allowedNetworkAddresses = new Set(allowedNetworkAddresses.map(normalizeAddress));
    if (typeof dnsLookup !== "function") throw new TypeError("dnsLookup must be a function");
    this.#dnsLookup = dnsLookup;
    this.#maxResponseBytes = positiveInteger(maxResponseBytes, "maxResponseBytes");
    if (this.#maxResponseBytes > MAX_RESPONSE_BODY_BYTES) {
      throw new TypeError("maxResponseBytes exceeds the broker hard ceiling");
    }

    requestStream.on("data", (chunk) => this.#onBytes(chunk));
    requestStream.on("error", () => this.close());
    requestStream.on("end", () => this.close());
  }

  authorizeEffect(input) {
    record(input, "egress effect");
    const operationId = stableId(input.operationId, "operationId");
    const context = Object.freeze({
      operationId,
      profileGrantDigest: digest(input.profileGrantDigest, "profileGrantDigest"),
      effectGrantDigest: digest(input.effectGrantDigest, "effectGrantDigest"),
      authorityEpoch: positiveInteger(input.authorityEpoch, "authorityEpoch"),
      destinationOrigin: canonicalOrigin(input.destinationOrigin),
      deadlineMs: positiveInteger(input.deadlineMs, "deadlineMs"),
    });
    if (context.profileGrantDigest !== this.#profileGrantDigest) {
      throw new TypeError("egress effect profile grant changed");
    }
    if (!this.#allowedOrigins.has(context.destinationOrigin)) {
      throw new TypeError("egress effect destination is outside the profile grant");
    }
    this.#authorities.set(operationId, context);
    if (this.#authorities.size > 1024) {
      const first = this.#authorities.keys().next().value;
      this.#authorities.delete(first);
    }
  }

  close() {
    if (this.#closed) return;
    this.#closed = true;
    this.#authorities.clear();
    this.#expectedRedirects.clear();
    this.#requestStream.removeAllListeners("data");
    this.#responseStream.end?.();
  }

  #onBytes(chunk) {
    if (this.#closed) return;
    let frames;
    try {
      frames = this.#decoder.push(chunk);
    } catch (error) {
      this.#sendFatal(error);
      return;
    }
    for (const frame of frames) {
      this.#tail = this.#tail
        .then(() => this.#handle(frame))
        .catch((error) => this.#sendError(frame, error));
    }
  }

  async #handle(frame) {
    exactKeys(
      frame,
      [
        "schema",
        "sequence",
        "operationId",
        "profileGrantDigest",
        "effectGrantDigest",
        "authorityEpoch",
        "url",
        "method",
        "headers",
        "isRedirect",
      ],
      "egress request",
    );
    if (frame.schema !== REQUEST_SCHEMA || frame.sequence !== this.#nextSequence) {
      throw new TypeError("egress request schema or sequence is invalid");
    }
    this.#nextSequence += 1;
    const operationId = stableId(frame.operationId, "operationId");
    const authority = this.#authorities.get(operationId);
    if (!authority) throw new TypeError("egress request has no admitted effect identity");
    if (
      digest(frame.profileGrantDigest, "profileGrantDigest") !== authority.profileGrantDigest ||
      digest(frame.effectGrantDigest, "effectGrantDigest") !== authority.effectGrantDigest ||
      positiveInteger(frame.authorityEpoch, "authorityEpoch") !== authority.authorityEpoch
    ) {
      throw new TypeError("egress request drifted from its admitted effect grant");
    }
    if (Date.now() >= authority.deadlineMs) {
      throw new TypeError("egress effect grant has expired");
    }
    if (frame.method !== "GET" && frame.method !== "HEAD") {
      throw new TypeError("current grant-scoped broker permits only bodyless GET/HEAD requests");
    }
    const requestHeaders = boundedHeaderPairs(frame.headers, "request headers");
    const url = canonicalUrl(frame.url);
    if (!this.#allowedOrigins.has(url.origin)) {
      throw new TypeError("egress origin is outside the profile grant");
    }
    const redirectKey = `${operationId}\u0000${url.href}`;
    if (frame.isRedirect === true) {
      if (!this.#expectedRedirects.delete(redirectKey)) {
        throw new TypeError("redirect target was not admitted for this operation");
      }
    } else if (frame.isRedirect !== false) {
      throw new TypeError("isRedirect must be boolean");
    }

    const destination = await this.#resolveDestination(url);
    const observed = await this.#fetch(url, frame.method, requestHeaders, destination, authority);
    if (observed.redirectTarget !== null) {
      this.#expectedRedirects.add(
        `${operationId}\u0000${observed.redirectTarget}`,
      );
      if (this.#expectedRedirects.size > 128) {
        const first = this.#expectedRedirects.values().next().value;
        this.#expectedRedirects.delete(first);
      }
    }
    const receipt = sha256(JSON.stringify({
      profileGrantDigest: authority.profileGrantDigest,
      effectGrantDigest: authority.effectGrantDigest,
      authorityEpoch: authority.authorityEpoch,
      operationId,
      url: url.href,
      address: observed.remoteAddress,
      dnsAnswers: destination.answers,
      tlsServerName: observed.tlsServerName,
      tlsPeerFingerprint256: observed.tlsPeerFingerprint256,
      statusCode: observed.statusCode,
    }));
    this.#write({
      schema: RESPONSE_SCHEMA,
      sequence: frame.sequence,
      ok: true,
      statusCode: observed.statusCode,
      statusMessage: observed.statusMessage,
      headers: observed.headers,
      bodyBase64: observed.body.toString("base64"),
      finalUrl: url.href,
      remoteAddress: observed.remoteAddress,
      dnsAnswers: destination.answers,
      tlsServerName: observed.tlsServerName,
      tlsPeerFingerprint256: observed.tlsPeerFingerprint256,
      egressReceiptDigest: receipt,
    });
  }

  async #resolveDestination(url) {
    const hostname = url.hostname;
    let answers;
    if (isIP(hostname) !== 0) {
      answers = [{ address: hostname, family: isIP(hostname) }];
    } else {
      answers = await new Promise((resolve, reject) => {
        this.#dnsLookup(hostname, { all: true, verbatim: true }, (error, values) => {
          if (error) reject(error);
          else resolve(values);
        });
      });
    }
    if (!Array.isArray(answers) || answers.length === 0 || answers.length > MAX_DNS_ANSWERS) {
      throw new TypeError("DNS result is empty or exceeds the bound");
    }
    const normalized = answers.map(({ address, family }) => ({
      address: normalizeAddress(address),
      family: Number(family),
    }));
    const permitted = normalized.filter(({ address, family }) => {
      if (this.#allowedNetworkAddresses.has(address)) return true;
      const familyName = family === 6 ? "ipv6" : "ipv4";
      return !deniedAddresses.check(address, familyName);
    });
    if (permitted.length === 0) {
      throw new TypeError("DNS resolved only to network addresses outside the grant");
    }
    const selected = permitted[0];
    return {
      selected,
      answers: normalized.map(({ address }) => address),
    };
  }

  async #validateRedirect(base, location) {
    const target = canonicalUrl(new URL(location, base).href);
    if (!this.#allowedOrigins.has(target.origin)) {
      throw new TypeError("redirect escaped the profile origin grant");
    }
    await this.#resolveDestination(target);
    return target.href;
  }

  #fetch(url, method, headerPairs, destination, authority) {
    const requestHeaders = {};
    for (const [name, value] of headerPairs) {
      if (name === "host" || name === "connection" || name === "proxy-connection") continue;
      const prior = requestHeaders[name];
      requestHeaders[name] = prior === undefined ? value : `${prior}, ${value}`;
    }
    const remaining = authority.deadlineMs - Date.now();
    const timeoutMs = Math.max(1, Math.min(30_000, remaining));
    const selected = destination.selected;
    const client = url.protocol === "https:" ? https : http;

    return new Promise((resolve, reject) => {
      let settled = false;
      const done = (fn, value) => {
        if (settled) return;
        settled = true;
        fn(value);
      };
      const req = client.request(url, {
        method,
        headers: requestHeaders,
        agent: false,
        rejectUnauthorized: true,
        servername: url.protocol === "https:" && isIP(url.hostname) === 0 ? url.hostname : undefined,
        lookup: (_hostname, _options, callback) => {
          callback(null, selected.address, selected.family);
        },
      }, async (res) => {
        try {
          const remoteAddress = normalizeAddress(res.socket.remoteAddress?.replace(/^::ffff:/, "") ?? "");
          if (remoteAddress !== selected.address.replace(/^::ffff:/, "")) {
            throw new TypeError("connected peer address drifted from the admitted DNS answer");
          }
          let tlsServerName = null;
          let tlsPeerFingerprint256 = null;
          if (url.protocol === "https:") {
            if (res.socket.authorized !== true) {
              throw new TypeError("TLS peer was not authorized");
            }
            tlsServerName = isIP(url.hostname) === 0 ? url.hostname : url.hostname;
            const peer = res.socket.getPeerCertificate?.();
            tlsPeerFingerprint256 =
              typeof peer?.fingerprint256 === "string"
                ? peer.fingerprint256.replace(/:/g, "").toLowerCase()
                : null;
            if (tlsPeerFingerprint256 === null || !DIGEST.test(tlsPeerFingerprint256)) {
              throw new TypeError("TLS peer certificate fingerprint is unavailable");
            }
          }
          const chunks = [];
          let total = 0;
          for await (const chunk of res) {
            const bytes = Buffer.from(chunk);
            total += bytes.length;
            if (total > this.#maxResponseBytes) {
              req.destroy();
              throw new TypeError("egress response body exceeds the byte ceiling");
            }
            chunks.push(bytes);
          }
          let redirectTarget = null;
          if (
            res.statusCode >= 300 &&
            res.statusCode < 400 &&
            typeof res.headers.location === "string"
          ) {
            redirectTarget = await this.#validateRedirect(url, res.headers.location);
          }
          done(resolve, {
            statusCode: res.statusCode,
            statusMessage: String(res.statusMessage ?? ""),
            headers: responseHeaders(res.headers),
            body: method === "HEAD" ? Buffer.alloc(0) : Buffer.concat(chunks),
            remoteAddress,
            tlsServerName,
            tlsPeerFingerprint256,
            redirectTarget,
          });
        } catch (error) {
          done(reject, error);
        }
      });
      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error("egress request timed out"));
      });
      req.once("error", (error) => done(reject, error));
      req.end();
    });
  }

  #sendError(frame, error) {
    const sequence = Number.isSafeInteger(frame?.sequence) ? frame.sequence : 0;
    try {
      this.#write({
        schema: RESPONSE_SCHEMA,
        sequence,
        ok: false,
        error: safeError(error),
      });
    } catch {
      this.close();
    }
  }

  #sendFatal(error) {
    try {
      this.#write({
        schema: RESPONSE_SCHEMA,
        sequence: 0,
        ok: false,
        error: safeError(error),
      });
    } finally {
      this.close();
    }
  }

  #write(value) {
    if (this.#closed) throw new Error("egress broker is closed");
    this.#responseStream.write(encodeFrame(value));
  }
}

export const egressBrokerLimits = Object.freeze({
  maxRequestFrameBytes: MAX_REQUEST_FRAME_BYTES,
  maxResponseFrameBytes: MAX_RESPONSE_FRAME_BYTES,
  maxResponseBodyBytes: MAX_RESPONSE_BODY_BYTES,
});
