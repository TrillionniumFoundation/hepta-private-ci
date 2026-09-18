import { lookup } from "node:dns/promises";
import http from "node:http";
import net from "node:net";
import { unlink } from "node:fs/promises";

const MAX_DNS_ANSWERS = 16;
const MAX_PROXY_CONNECTIONS = 64;
const CONNECT_TIMEOUT_MS = 10_000;

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
  ["2001:db8::", 32],
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

async function resolvePinned(hostname, { allowPrivateNetworkForTests }) {
  const normalizedHostname =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
  const direct = net.isIP(normalizedHostname);
  const answers = direct
    ? [{ address: normalizedHostname, family: direct }]
    : await lookup(normalizedHostname, { all: true, verbatim: true });
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

async function connectResolved(hostname, port, options) {
  const answers = await resolvePinned(hostname, options);
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
  throw lastError ?? new Error("no resolved egress destination connected");
}

export class GrantScopedEgressBroker {
  #socketPath;
  #allowedOrigins;
  #allowPrivateNetworkForTests;
  #server = null;
  #connections = new Set();
  #observations = [];

  constructor({ socketPath, allowedOrigins, allowPrivateNetworkForTests = false }) {
    if (typeof socketPath !== "string" || socketPath.length === 0) {
      throw new TypeError("egress socketPath must be a non-empty string");
    }
    if (!Array.isArray(allowedOrigins) || allowedOrigins.length > 128) {
      throw new TypeError("egress allowedOrigins must be a bounded array");
    }
    if (typeof allowPrivateNetworkForTests !== "boolean") {
      throw new TypeError("allowPrivateNetworkForTests must be boolean");
    }
    this.#socketPath = socketPath;
    this.#allowedOrigins = new Set(allowedOrigins.map(canonicalOrigin));
    this.#allowPrivateNetworkForTests = allowPrivateNetworkForTests;
  }

  get observations() {
    return this.#observations.map((value) => Object.freeze({ ...value }));
  }

  async start() {
    if (this.#server) throw new TypeError("egress broker is already started");
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
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
    await unlink(this.#socketPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }

  #assertOrigin(origin) {
    const canonical = canonicalOrigin(origin);
    if (!this.#allowedOrigins.has(canonical)) {
      throw new Error("egress origin is outside the profile grant");
    }
    return canonical;
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
    const origin = this.#assertOrigin(target.origin);
    const port = Number(target.port || 80);
    const { socket, address } = await connectResolved(target.hostname, port, {
      allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
    });
    this.#record(origin, target.hostname, port, address, "http");
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
    const origin = this.#assertOrigin(target.origin);
    const port = Number(target.port || 443);
    const { socket: upstream, address } = await connectResolved(target.hostname, port, {
      allowPrivateNetworkForTests: this.#allowPrivateNetworkForTests,
    });
    this.#record(origin, target.hostname, port, address, "connect");
    client.write("HTTP/1.1 200 Connection Established\r\nProxy-Agent: hepta-egress\r\n\r\n");
    if (head?.length) upstream.write(head);
    client.pipe(upstream);
    upstream.pipe(client);
    upstream.on("error", () => client.destroy());
    client.on("error", () => upstream.destroy());
  }

  #record(origin, hostname, port, address, kind) {
    this.#observations.push(Object.freeze({ origin, hostname, port, address, kind }));
    if (this.#observations.length > 256) this.#observations.shift();
  }
}
