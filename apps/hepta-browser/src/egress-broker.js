import { createHash } from "node:crypto";
import { lookup } from "node:dns/promises";
import http from "node:http";
import net from "node:net";
import { lstat, unlink } from "node:fs/promises";
import { Transform } from "node:stream";
import { setMaxListeners } from "node:events";

const MAX_DNS_ANSWERS = 16;
const MAX_PROXY_CONNECTIONS = 64;
const CONNECT_TIMEOUT_MS = 10_000;
const TLS_CLIENT_HELLO_TIMEOUT_MS = 5_000;
const MAX_TLS_CLIENT_HELLO_BYTES = 65_536;
const MAX_TLS_RECORD_BYTES = 18_432;
const DIGEST = /^[0-9a-f]{64}$/;

const blocked = new net.BlockList();
for (const [network, prefix] of [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
]) blocked.addSubnet(network, prefix, "ipv4");
for (const [network, prefix] of [
  ["::", 128],
  ["::1", 128],
  ["::ffff:0:0", 96],
  ["64:ff9b::", 96],
  ["fc00::", 7],
  ["fe80::", 10],
  ["ff00::", 8],
  ["2001::", 32],
  ["2001:2::", 48],
  ["2001:10::", 28],
  ["2001:20::", 28],
  ["2001:db8::", 32],
  ["2002::", 16],
]) blocked.addSubnet(network, prefix, "ipv6");

function canonicalOrigin(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new TypeError("egress origin must use HTTP or HTTPS");
  }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new TypeError("egress origin must not contain credentials, path, query, or fragment");
  }
  return url.origin;
}

function privateAddress(address, family) {
  const kind = family === 6 || net.isIP(address) === 6 ? "ipv6" : "ipv4";
  return blocked.check(address, kind);
}

async function resolvePinned(hostname, { allowPrivateNetworkForTests, resolver = lookup }) {
  const normalizedHostname =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
  const direct = net.isIP(normalizedHostname);
  const answers = direct
    ? [{ address: normalizedHostname, family: direct }]
    : await resolver(normalizedHostname, { all: true, verbatim: true });
  if (answers.length === 0 || answers.length > MAX_DNS_ANSWERS) {
    throw new Error("DNS answer count is outside the egress bound");
  }
  const normalized = [];
  for (const answer of answers) {
    if (net.isIP(answer.address) === 0) {
      throw new Error("DNS returned a non-IP address");
    }
    if (!allowPrivateNetworkForTests && privateAddress(answer.address, answer.family)) {
      throw new Error("resolved destination is not globally routable");
    }
    normalized.push({ address: answer.address, family: answer.family });
  }
  normalized.sort((left, right) =>
    left.family - right.family || left.address.localeCompare(right.address)
  );
  return normalized;
}

function stripHopByHop(headers) {
  const output = { ...headers };
  for (const key of [
    "proxy-authorization",
    "proxy-authenticate",
    "proxy-connection",
    "connection",
    "keep-alive",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
  ]) delete output[key];
  return output;
}

async function connectPinned(answers, port, { signal, track }) {
  let lastError;
  for (const answer of answers) {
    signal.throwIfAborted();
    try {
      return await new Promise((resolve, reject) => {
        const socket = track(net.createConnection({
          host: answer.address, port, family: answer.family,
        }));
        let settled = false;
        const cleanup = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", abort);
          socket.off("connect", connected);
          socket.off("error", failed);
          socket.off("close", closed);
        };
        const failed = (error) => {
          if (settled) return;
          settled = true;
          cleanup();
          socket.destroy();
          reject(error);
        };
        const abort = () => failed(signal.reason ?? new Error("egress closed"));
        const closed = () => failed(new Error("egress closed during connect"));
        const connected = () => {
          if (signal.aborted) return abort();
          settled = true;
          cleanup();
          resolve({ socket, address: answer.address });
        };
        const timer = setTimeout(() => failed(new Error("egress connection timed out")),
          CONNECT_TIMEOUT_MS);
        socket.once("connect", connected);
        socket.once("error", failed);
        socket.once("close", closed);
        signal.addEventListener("abort", abort, { once: true });
        if (signal.aborted) abort();
      });
    } catch (error) {
      signal.throwIfAborted();
      lastError = error;
    }
  }
  throw lastError ?? new Error("no pinned egress destination connected");
}

function boundedTransfer(maximum, assertLive) {
  let bytes = 0;
  return new Transform({
    transform(chunk, _encoding, callback) {
      try {
        assertLive();
        bytes += chunk.length;
        if (bytes > maximum) throw new Error("egress transfer byte budget exhausted");
        callback(null, chunk);
      } catch (error) { callback(error); }
    },
  });
}

function boundedResolve(promise, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => finish(signal.reason ?? new Error("egress closed during DNS"));
    const timer = setTimeout(() => finish(new Error("egress DNS deadline exceeded")),
      CONNECT_TIMEOUT_MS);
    let done = false;
    function finish(error, value) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      if (error) reject(error); else resolve(value);
    }
    signal.addEventListener("abort", abort, { once: true });
    Promise.resolve(promise).then(value => finish(null, value), finish);
    if (signal.aborted) abort();
  });
}

function bindingDigest(grantDigest, origin, answers) {
  return createHash("sha256")
    .update(JSON.stringify({ grantDigest, origin, answers }))
    .digest("hex");
}

function readUInt24(buffer, offset) {
  return (buffer[offset] << 16) | (buffer[offset + 1] << 8) | buffer[offset + 2];
}

function parseClientHelloServerName(body) {
  let offset = 0;
  if (body.length < 35) throw new Error("TLS ClientHello is truncated");
  offset += 2 + 32;
  const sessionIdBytes = body[offset++];
  if (offset + sessionIdBytes > body.length) {
    throw new Error("TLS ClientHello session id is truncated");
  }
  offset += sessionIdBytes;
  if (offset + 2 > body.length) {
    throw new Error("TLS ClientHello cipher suites are truncated");
  }
  const cipherBytes = body.readUInt16BE(offset);
  offset += 2;
  if (cipherBytes < 2 || cipherBytes % 2 !== 0 || offset + cipherBytes > body.length) {
    throw new Error("TLS ClientHello cipher suite vector is invalid");
  }
  offset += cipherBytes;
  if (offset >= body.length) {
    throw new Error("TLS ClientHello compression vector is missing");
  }
  const compressionBytes = body[offset++];
  if (compressionBytes < 1 || offset + compressionBytes > body.length) {
    throw new Error("TLS ClientHello compression vector is invalid");
  }
  offset += compressionBytes;
  if (offset === body.length) return null;
  if (offset + 2 > body.length) {
    throw new Error("TLS ClientHello extensions are truncated");
  }
  const extensionsBytes = body.readUInt16BE(offset);
  offset += 2;
  if (offset + extensionsBytes !== body.length) {
    throw new Error("TLS ClientHello extensions length is invalid");
  }
  const extensionsEnd = offset + extensionsBytes;
  let serverName = null;
  while (offset < extensionsEnd) {
    if (offset + 4 > extensionsEnd) {
      throw new Error("TLS extension header is truncated");
    }
    const type = body.readUInt16BE(offset);
    const length = body.readUInt16BE(offset + 2);
    offset += 4;
    if (offset + length > extensionsEnd) {
      throw new Error("TLS extension body is truncated");
    }
    if (type === 0) {
      if (length < 5) throw new Error("TLS server_name extension is invalid");
      const extensionEnd = offset + length;
      const listBytes = body.readUInt16BE(offset);
      offset += 2;
      if (offset + listBytes !== extensionEnd) {
        throw new Error("TLS server_name list length is invalid");
      }
      while (offset < extensionEnd) {
        if (offset + 3 > extensionEnd) {
          throw new Error("TLS server_name entry is truncated");
        }
        const nameType = body[offset++];
        const nameBytes = body.readUInt16BE(offset);
        offset += 2;
        if (nameBytes < 1 || offset + nameBytes > extensionEnd) {
          throw new Error("TLS server_name value is invalid");
        }
        const value = body.subarray(offset, offset + nameBytes);
        offset += nameBytes;
        if (nameType === 0) {
          if (serverName !== null) {
            throw new Error("TLS ClientHello contains duplicate host_name entries");
          }
          if ([...value].some((byte) => byte < 0x21 || byte > 0x7e)) {
            throw new Error("TLS host_name must be visible ASCII");
          }
          serverName = value.toString("ascii");
        }
      }
    } else {
      offset += length;
    }
  }
  return serverName;
}

function parseTlsClientHelloServerName(bytes) {
  let recordOffset = 0;
  let handshake = Buffer.alloc(0);
  while (recordOffset + 5 <= bytes.length) {
    const contentType = bytes[recordOffset];
    const recordBytes = bytes.readUInt16BE(recordOffset + 3);
    if (recordBytes < 1 || recordBytes > MAX_TLS_RECORD_BYTES) {
      throw new Error("TLS record length is outside the egress bound");
    }
    if (recordOffset + 5 + recordBytes > bytes.length) return undefined;
    if (contentType !== 22) {
      throw new Error("HTTPS CONNECT must begin with a TLS handshake record");
    }
    handshake = Buffer.concat([
      handshake,
      bytes.subarray(recordOffset + 5, recordOffset + 5 + recordBytes),
    ]);
    if (handshake.length > MAX_TLS_CLIENT_HELLO_BYTES) {
      throw new Error("TLS ClientHello exceeds the egress bound");
    }
    recordOffset += 5 + recordBytes;
    if (handshake.length < 4) continue;
    if (handshake[0] !== 1) {
      throw new Error("HTTPS CONNECT must begin with TLS ClientHello");
    }
    const helloBytes = readUInt24(handshake, 1);
    if (helloBytes < 35 || helloBytes + 4 > MAX_TLS_CLIENT_HELLO_BYTES) {
      throw new Error("TLS ClientHello length is outside the egress bound");
    }
    if (handshake.length < helloBytes + 4) continue;
    return parseClientHelloServerName(handshake.subarray(4, helloBytes + 4));
  }
  if (bytes.length > MAX_TLS_CLIENT_HELLO_BYTES) {
    throw new Error("TLS ClientHello exceeds the egress bound");
  }
  return undefined;
}

function canonicalTlsServerName(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 253) {
    throw new Error("TLS server name is outside the egress bound");
  }
  if (!/^[A-Za-z0-9.-]+$/.test(value)) {
    throw new Error("TLS server name contains invalid characters");
  }
  const url = new URL(`https://${value}/`);
  return url.hostname.toLowerCase();
}

function requireTlsDestinationBinding(hostname, serverName) {
  const target =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
  const targetIp = net.isIP(target);
  if (targetIp !== 0) {
    if (serverName === null) return;
    if (canonicalTlsServerName(serverName) !== target.toLowerCase()) {
      throw new Error("TLS ClientHello server name does not match the granted IP destination");
    }
    return;
  }
  if (serverName === null) {
    throw new Error("TLS ClientHello SNI is required for a granted DNS destination");
  }
  if (canonicalTlsServerName(serverName) !== canonicalTlsServerName(target)) {
    throw new Error("TLS ClientHello SNI does not match the granted DNS destination");
  }
}

function readBoundTlsClientHello(client, head, hostname) {
  return new Promise((resolve, reject) => {
    let bytes = head?.length ? Buffer.from(head) : Buffer.alloc(0);
    let settled = false;
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      client.off("data", onData);
      client.off("error", onError);
      client.off("close", onClose);
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const inspect = () => {
      if (bytes.length > MAX_TLS_CLIENT_HELLO_BYTES) {
        fail(new Error("TLS ClientHello exceeds the egress bound"));
        return true;
      }
      let serverName;
      try {
        serverName = parseTlsClientHelloServerName(bytes);
      } catch (error) {
        fail(error);
        return true;
      }
      if (serverName === undefined) return false;
      try {
        requireTlsDestinationBinding(hostname, serverName);
      } catch (error) {
        fail(error);
        return true;
      }
      settled = true;
      cleanup();
      client.pause();
      resolve(bytes);
      return true;
    };
    const onData = (chunk) => {
      client.pause();
      bytes = Buffer.concat([bytes, chunk]);
      if (!inspect()) client.resume();
    };
    const onError = (error) => fail(error);
    const onClose = () =>
      fail(new Error("HTTPS CONNECT closed before a bounded TLS ClientHello"));
    client.pause();
    client.on("data", onData);
    client.once("error", onError);
    client.once("close", onClose);
    timer = setTimeout(
      () => fail(new Error("TLS ClientHello timed out")),
      TLS_CLIENT_HELLO_TIMEOUT_MS,
    );
    if (!inspect()) client.resume();
  });
}

export class GrantScopedEgressBroker {
  #socketPath;
  #grantDigest;
  #allowedOrigins;
  #allowPrivateNetworkForTests;
  #resolver;
  #bindings = new Map();
  #server = null;
  #connections = new Set();
  #observations = [];
  #state = "new";
  #abort = new AbortController();
  #startTask = null;
  #closeTask = null;
  #pending = new Set();
  #socketIdentity = null;
  #maxRequestBytes;
  #maxResponseBytes;
  #transferTimeoutMs;

  constructor({
    socketPath,
    grantDigest,
    allowedOrigins,
    allowPrivateNetworkForTests = false,
    resolver = lookup,
    maxRequestBytes = 1 * 1024 * 1024,
    maxResponseBytes = 32 * 1024 * 1024,
    transferTimeoutMs = 120_000,
  }) {
    if (typeof socketPath !== "string" || socketPath.length === 0) {
      throw new TypeError("egress socketPath must be a non-empty string");
    }
    if (
      typeof grantDigest !== "string" ||
      !DIGEST.test(grantDigest) ||
      /^0+$/.test(grantDigest)
    ) {
      throw new TypeError("egress grantDigest must be a non-zero lowercase SHA-256 digest");
    }
    if (!Array.isArray(allowedOrigins) || allowedOrigins.length > 128) {
      throw new TypeError("egress allowedOrigins must be a bounded array");
    }
    if (typeof allowPrivateNetworkForTests !== "boolean") {
      throw new TypeError("allowPrivateNetworkForTests must be boolean");
    }
    if (typeof resolver !== "function") {
      throw new TypeError("egress resolver must be a function");
    }
    if (resolver !== lookup && allowPrivateNetworkForTests !== true) {
      throw new TypeError("custom egress resolver is test-only");
    }
    for (const [name, value, ceiling] of [
      ["maxRequestBytes", maxRequestBytes, 16 * 1024 * 1024],
      ["maxResponseBytes", maxResponseBytes, 256 * 1024 * 1024],
      ["transferTimeoutMs", transferTimeoutMs, 120_000],
    ]) {
      if (!Number.isSafeInteger(value) || value < 1 || value > ceiling) {
        throw new TypeError(`${name} is outside the egress hard bound`);
      }
    }
    this.#maxRequestBytes = maxRequestBytes;
    this.#maxResponseBytes = maxResponseBytes;
    this.#transferTimeoutMs = transferTimeoutMs;
    setMaxListeners(MAX_PROXY_CONNECTIONS * 4, this.#abort.signal);
    if (Buffer.byteLength(socketPath) > 107) {
      throw new TypeError("egress socket path exceeds Linux sockaddr_un bound; select a shorter private profile root");
    }
    this.#socketPath = socketPath;
    this.#grantDigest = grantDigest;
    this.#allowedOrigins = new Set(allowedOrigins.map(canonicalOrigin));
    this.#allowPrivateNetworkForTests = allowPrivateNetworkForTests;
    this.#resolver = resolver;
  }

  get observations() {
    return this.#observations.map((value) => Object.freeze({ ...value }));
  }

  #trackConnection(socket) {
    if (this.#state === "closing" || this.#state === "closed") {
      socket.destroy();
      throw new Error("egress broker is closed");
    }
    if (this.#connections.size >= MAX_PROXY_CONNECTIONS * 2) {
      socket.destroy();
      throw new Error("egress connection capacity exhausted");
    }
    this.#connections.add(socket);
    // Keep an error listener even before a connect promise or pipe is attached.
    socket.on("error", () => {});
    socket.once("close", () => this.#connections.delete(socket));
    return socket;
  }

  #live(client = null) {
    this.#abort.signal.throwIfAborted();
    if (this.#state !== "running" || client?.destroyed) {
      throw new Error("egress broker or request has closed");
    }
  }

  #handle(task, failure) {
    const pending = Promise.resolve().then(task).catch(failure);
    this.#pending.add(pending);
    void pending.finally(() => this.#pending.delete(pending)).catch(() => {});
  }

  start() {
    if (this.#state !== "new") return Promise.reject(new TypeError("egress broker is already started or closed"));
    this.#state = "starting";
    this.#startTask = this.#start();
    return this.#startTask;
  }

  async #start() {
    try {
      await unlink(this.#socketPath).catch(error => {
        if (error?.code !== "ENOENT") throw error;
      });
      const bindings = new Map();
      for (const origin of this.#allowedOrigins) {
        this.#abort.signal.throwIfAborted();
        const target = new URL(origin);
        const answers = await boundedResolve(resolvePinned(target.hostname, {
          allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
          resolver: this.#resolver,
        }), this.#abort.signal);
        this.#abort.signal.throwIfAborted();
        bindings.set(origin, Object.freeze({
          origin, hostname: target.hostname,
          port: Number(target.port || (target.protocol === "https:" ? 443 : 80)),
          answers: Object.freeze(answers.map(answer => Object.freeze({ ...answer }))),
          bindingDigest: bindingDigest(this.#grantDigest, origin, answers),
        }));
      }
      this.#bindings = bindings;
      const server = http.createServer({
        maxHeaderSize: 65_536, headersTimeout: 5_000,
        requestTimeout: this.#transferTimeoutMs,
      }, (request, response) => {
        this.#handle(() => this.#handleHttp(request, response), () => {
          if (response.destroyed) return;
          if (!response.headersSent) response.writeHead(502);
          response.end();
        });
      });
      this.#server = server;
      server.maxConnections = MAX_PROXY_CONNECTIONS;
      server.on("connection", socket => {
        try { this.#trackConnection(socket); } catch { socket.destroy(); }
      });
      server.on("connect", (request, client, head) => {
        this.#handle(() => this.#handleConnect(request, client, head), () => {
          if (!client.destroyed) client.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
        });
      });
      server.on("upgrade", (_request, socket) => socket.destroy());
      server.on("clientError", (_error, socket) => socket.destroy());
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(this.#socketPath, () => {
          server.off("error", reject);
          resolve();
        });
      });
      this.#socketIdentity = await lstat(this.#socketPath);
      this.#abort.signal.throwIfAborted();
      this.#state = "running";
    } catch (error) {
      // close() owns cleanup; never resurrect a cancelled startup.
      if (this.#state === "starting") this.#state = "failed";
      throw error;
    }
  }

  close() {
    if (this.#closeTask !== null) return this.#closeTask;
    this.#state = "closing";
    this.#abort.abort(new Error("egress broker closed"));
    // Abort pending connects immediately, including sockets not yet connected.
    for (const socket of this.#connections) socket.destroy();
    const closing = this.#close();
    this.#closeTask = closing;
    void closing.catch(() => { if (this.#closeTask === closing) this.#closeTask = null; });
    return closing;
  }

  async #close() {
    await this.#startTask?.catch(() => {});
    const server = this.#server;
    const gone = [...this.#connections].map(socket => new Promise(resolve => {
      if (socket.closed) return resolve();
      socket.once("close", resolve);
      socket.destroy();
    }));
    if (server) await new Promise((resolve, reject) => server.close(error => {
      if (error && error.code !== "ERR_SERVER_NOT_RUNNING") reject(error); else resolve();
    }));
    this.#server = null;
    await Promise.allSettled([...this.#pending]);
    await Promise.all(gone);
    this.#bindings.clear();
    this.#connections.clear();
    // A wrapper may have moved our socket and installed its own at this name.
    // Never unlink a replacement endpoint owned by a different generation.
    try {
      const current = await lstat(this.#socketPath);
      if (this.#socketIdentity && current.dev === this.#socketIdentity.dev &&
          current.ino === this.#socketIdentity.ino) await unlink(this.#socketPath);
    } catch (error) { if (error?.code !== "ENOENT") throw error; }
    this.#state = "closed";
  }

  #assertOrigin(origin) {
    this.#live();
    const canonical = canonicalOrigin(origin);
    const binding = this.#bindings.get(canonical);
    if (!this.#allowedOrigins.has(canonical) || !binding) {
      throw new Error("egress origin is outside the profile grant");
    }
    return binding;
  }

  async #handleHttp(request, response) {
    let target;
    try {
      target = new URL(request.url);
    } catch {
      response.writeHead(400);
      response.end();
      return;
    }
    if (target.protocol !== "http:") {
      response.writeHead(405);
      response.end();
      return;
    }
    const binding = this.#assertOrigin(target.origin);
    const port = Number(target.port || 80);
    if (port !== binding.port || target.hostname !== binding.hostname) {
      throw new Error("HTTP destination drifted from the frozen profile network grant");
    }
    if (target.username || target.password) throw new Error("HTTP credentials are forbidden");
    const connected = await connectPinned(binding.answers, port, {
      signal: this.#abort.signal, track: socket => this.#trackConnection(socket),
    });
    const socket = connected.socket;
    try { this.#live(request.socket); } catch (error) { socket.destroy(); throw error; }
    this.#record(binding, target.hostname, port, connected.address, "http");
    const headers = stripHopByHop(request.headers);
    headers.host = target.host;
    headers.connection = "close";
    // A dedicated agent MUST consume the already checked pinned socket. Do not
    // let the default agent create a second, unowned outbound connection.
    const agent = new http.Agent({ keepAlive: false, maxSockets: 1 });
    agent.createConnection = () => socket;
    const upstream = http.request({ method: request.method, host: connected.address,
      port, path: `${target.pathname}${target.search}`, headers, agent,
      maxHeaderSize: 65_536 });
    const requestBound = boundedTransfer(this.#maxRequestBytes, () => this.#live(request.socket));
    const responseBound = boundedTransfer(this.#maxResponseBytes, () => this.#live(request.socket));
    const cleanup = () => {
      clearTimeout(timer);
      requestBound.destroy(); responseBound.destroy(); upstream.destroy(); agent.destroy();
    };
    const fail = () => { response.destroy(); cleanup(); };
    const timer = setTimeout(fail, this.#transferTimeoutMs);
    requestBound.on("error", fail);
    responseBound.on("error", fail);
    request.on("aborted", fail);
    response.once("close", cleanup);
    upstream.on("response", upstreamResponse => {
      try { this.#live(request.socket); } catch { fail(); return; }
      response.writeHead(upstreamResponse.statusCode ?? 502, stripHopByHop(upstreamResponse.headers));
      upstreamResponse.on("error", fail);
      upstreamResponse.pipe(responseBound).pipe(response);
    });
    upstream.on("error", () => {
      if (!response.destroyed) {
        if (!response.headersSent) response.writeHead(502);
        response.end();
      }
      cleanup();
    });
    request.pipe(requestBound).pipe(upstream);
  }

  async #handleConnect(request, client, head) {
    const authority = request.url;
    if (typeof authority !== "string" || authority.length === 0 || authority.length > 4096) {
      throw new Error("CONNECT authority is invalid");
    }
    const target = new URL(`https://${authority}`);
    if (target.username || target.password || target.pathname !== "/" || target.search || target.hash) {
      throw new Error("CONNECT authority contains forbidden URL components");
    }
    const binding = this.#assertOrigin(target.origin);
    const port = Number(target.port || 443);
    if (port !== binding.port || target.hostname !== binding.hostname) {
      throw new Error("CONNECT destination drifted from the frozen profile network grant");
    }
    client.write("HTTP/1.1 200 Connection Established\r\nProxy-Agent: hepta-egress\r\n\r\n");

    let upstream = null;
    let timer = null;
    try {
      const hello = await readBoundTlsClientHello(client, head, target.hostname);
      this.#live(client);
      const connected = await connectPinned(binding.answers, port, {
        signal: this.#abort.signal, track: socket => this.#trackConnection(socket),
      });
      upstream = connected.socket;
      this.#live(client);
      if (hello.length > this.#maxRequestBytes) throw new Error("TLS hello exceeds request budget");
      this.#record(binding, target.hostname, port, connected.address, "connect");
      const requestBound = boundedTransfer(this.#maxRequestBytes - hello.length, () => this.#live(client));
      const responseBound = boundedTransfer(this.#maxResponseBytes, () => this.#live(client));
      const end = () => {
        clearTimeout(timer);
        requestBound.destroy(); responseBound.destroy();
        client.destroy(); upstream.destroy();
      };
      timer = setTimeout(end, this.#transferTimeoutMs);
      client.once("close", end); upstream.once("close", end);
      client.once("error", end); upstream.once("error", end);
      requestBound.once("error", end); responseBound.once("error", end);
      upstream.write(hello);
      client.pipe(requestBound).pipe(upstream);
      upstream.pipe(responseBound).pipe(client);
      client.resume();
    } catch (error) {
      clearTimeout(timer);
      upstream?.destroy();
      client.destroy();
      throw error;
    }
  }

  #record(binding, hostname, port, address, kind) {
    this.#observations.push(
      Object.freeze({
        grantDigest: this.#grantDigest,
        networkBindingDigest: binding.bindingDigest,
        origin: binding.origin,
        hostname,
        port,
        address,
        kind,
      }),
    );
    if (this.#observations.length > 256) this.#observations.shift();
  }
}
