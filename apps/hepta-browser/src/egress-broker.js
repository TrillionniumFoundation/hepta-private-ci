import { createHash } from "node:crypto";
import { lookup } from "node:dns/promises";
import http from "node:http";
import net from "node:net";
import { unlink } from "node:fs/promises";

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

async function connectPinned(answers, port) {
  let lastError;
  for (const answer of answers) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({
          host: answer.address,
          port,
          family: answer.family,
        });
        const timer = setTimeout(() => {
          socket.destroy(new Error("egress connection timed out"));
        }, CONNECT_TIMEOUT_MS);
        socket.once("connect", () => {
          clearTimeout(timer);
          resolve({ socket, address: answer.address });
        });
        socket.once("error", (error) => {
          clearTimeout(timer);
          reject(error);
        });
      });
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error("no pinned egress destination connected");
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
  if (offset + sessionIdBytes > body.length) throw new Error("TLS ClientHello session id is truncated");
  offset += sessionIdBytes;
  if (offset + 2 > body.length) throw new Error("TLS ClientHello cipher suites are truncated");
  const cipherBytes = body.readUInt16BE(offset);
  offset += 2;
  if (cipherBytes < 2 || cipherBytes % 2 !== 0 || offset + cipherBytes > body.length) {
    throw new Error("TLS ClientHello cipher suite vector is invalid");
  }
  offset += cipherBytes;
  if (offset >= body.length) throw new Error("TLS ClientHello compression vector is missing");
  const compressionBytes = body[offset++];
  if (compressionBytes < 1 || offset + compressionBytes > body.length) {
    throw new Error("TLS ClientHello compression vector is invalid");
  }
  offset += compressionBytes;
  if (offset === body.length) return null;
  if (offset + 2 > body.length) throw new Error("TLS ClientHello extensions are truncated");
  const extensionsBytes = body.readUInt16BE(offset);
  offset += 2;
  if (offset + extensionsBytes !== body.length) {
    throw new Error("TLS ClientHello extensions length is invalid");
  }
  const extensionsEnd = offset + extensionsBytes;
  let serverName = null;
  while (offset < extensionsEnd) {
    if (offset + 4 > extensionsEnd) throw new Error("TLS extension header is truncated");
    const type = body.readUInt16BE(offset);
    const length = body.readUInt16BE(offset + 2);
    offset += 4;
    if (offset + length > extensionsEnd) throw new Error("TLS extension body is truncated");
    if (type === 0) {
      if (length < 5) throw new Error("TLS server_name extension is invalid");
      const extensionEnd = offset + length;
      const listBytes = body.readUInt16BE(offset);
      offset += 2;
      if (offset + listBytes !== extensionEnd) {
        throw new Error("TLS server_name list length is invalid");
      }
      while (offset < extensionEnd) {
        if (offset + 3 > extensionEnd) throw new Error("TLS server_name entry is truncated");
        const nameType = body[offset++];
        const nameBytes = body.readUInt16BE(offset);
        offset += 2;
        if (nameBytes < 1 || offset + nameBytes > extensionEnd) {
          throw new Error("TLS server_name value is invalid");
        }
        const value = body.subarray(offset, offset + nameBytes);
        offset += nameBytes;
        if (nameType === 0) {
          if (serverName !== null) throw new Error("TLS ClientHello contains duplicate host_name entries");
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
    if (handshake[0] !== 1) throw new Error("HTTPS CONNECT must begin with TLS ClientHello");
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
  const target = hostname.startsWith("[") && hostname.endsWith("]")
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
    const onClose = () => fail(new Error("HTTPS CONNECT closed before a bounded TLS ClientHello"));
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

  constructor({
    socketPath,
    grantDigest,
    allowedOrigins,
    allowPrivateNetworkForTests = false,
    resolver = lookup,
  }) {
    if (typeof socketPath !== "string" || socketPath.length === 0) {
      throw new TypeError("egress socketPath must be a non-empty string");
    }
    if (typeof grantDigest !== "string" || !DIGEST.test(grantDigest) || /^0+$/.test(grantDigest)) {
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
    this.#socketPath = socketPath;
    this.#grantDigest = grantDigest;
    this.#allowedOrigins = new Set(allowedOrigins.map(canonicalOrigin));
    this.#allowPrivateNetworkForTests = allowPrivateNetworkForTests;
    this.#resolver = resolver;
  }

  get observations() {
    return this.#observations.map((value) => Object.freeze({ ...value }));
  }

  async start() {
    if (this.#server) throw new TypeError("egress broker is already started");
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });

    // Freeze exact DNS/IP answers for this profile network-grant generation.
    // Requests never re-resolve these names, preventing DNS rebinding after admission.
    const bindings = new Map();
    for (const origin of this.#allowedOrigins) {
      const target = new URL(origin);
      const answers = await resolvePinned(target.hostname, {
        allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
        resolver: this.#resolver,
      });
      bindings.set(origin, Object.freeze({
        origin,
        hostname: target.hostname,
        port: Number(target.port || (target.protocol === "https:" ? 443 : 80)),
        answers: Object.freeze(answers.map((answer) => Object.freeze({ ...answer }))),
        bindingDigest: bindingDigest(this.#grantDigest, origin, answers),
      }));
    }
    this.#bindings = bindings;

    const server = http.createServer((request, response) => {
      this.#handleHttp(request, response).catch(() => {
        if (!response.headersSent) response.writeHead(502);
        response.end();
      });
    });
    server.maxConnections = MAX_PROXY_CONNECTIONS;
    server.on("connection", (socket) => {
      this.#connections.add(socket);
      socket.once("close", () => this.#connections.delete(socket));
    });
    server.on("connect", (request, client, head) => {
      this.#handleConnect(request, client, head).catch(() => {
        if (!client.destroyed) {
          client.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
        }
      });
    });
    server.on("clientError", (_error, socket) => {
      socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
    });
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(this.#socketPath, () => {
        server.off("error", reject);
        resolve();
      });
    });
    this.#server = server;
  }

  async close() {
    const server = this.#server;
    this.#server = null;
    if (server) {
      for (const socket of this.#connections) socket.destroy();
      this.#connections.clear();
      await new Promise((resolve) => server.close(() => resolve()));
    }
    this.#bindings = new Map();
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }

  #assertOrigin(origin) {
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
    const { socket, address } = await connectPinned(binding.answers, port);
    this.#record(binding, target.hostname, port, address, "http");
    const headers = stripHopByHop(request.headers);
    headers.host = target.host;
    const upstream = http.request({
      method: request.method,
      host: address,
      family: net.isIP(address),
      port,
      path: `${target.pathname}${target.search}`,
      headers,
      createConnection: () => socket,
    });
    upstream.on("response", (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, stripHopByHop(upstreamResponse.headers));
      upstreamResponse.pipe(response);
    });
    upstream.on("error", () => {
      if (!response.headersSent) response.writeHead(502);
      response.end();
    });
    request.pipe(upstream);
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

    try {
      // CONNECT authority alone does not bind a TLS virtual host. Require the
      // bounded ClientHello to name the granted destination before any upstream
      // TCP connection can exist.
      const hello = await readBoundTlsClientHello(client, head, target.hostname);
      const { socket: upstream, address } = await connectPinned(binding.answers, port);
      this.#record(binding, target.hostname, port, address, "connect");
      upstream.write(hello);
      client.pipe(upstream);
      upstream.pipe(client);
      upstream.on("error", () => client.destroy());
      client.on("error", () => upstream.destroy());
      client.resume();
    } catch (error) {
      client.destroy();
      throw error;
    }
  }

  #record(binding, hostname, port, address, kind) {
    this.#observations.push(Object.freeze({
      grantDigest: this.#grantDigest,
      networkBindingDigest: binding.bindingDigest,
      origin: binding.origin,
      hostname,
      port,
      address,
      kind,
    }));
    if (this.#observations.length > 256) this.#observations.shift();
  }
}
