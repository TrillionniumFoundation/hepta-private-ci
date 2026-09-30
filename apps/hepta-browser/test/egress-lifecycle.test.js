import assert from "node:assert/strict";
import test from "node:test";
import http from "node:http";
import net from "node:net";
import { once } from "node:events";
import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { GrantScopedEgressBroker } from "../src/egress-broker.js";
const D = "1".repeat(64);
async function root(t) {
  const path = await mkdtemp(join(tmpdir(), "eg-life-"));
  t.after(() => rm(path, { recursive: true, force: true }));
  return join(path, "egress.sock");
}
function read(socketPath, url) {
  const client = net.createConnection(socketPath);
  let data = Buffer.alloc(0);
  client.on("data", chunk => { data = Buffer.concat([data, chunk]); });
  client.on("error", () => {});
  client.once("connect", () => client.write(`GET ${url} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n`));
  const closed = new Promise(resolve => client.once("close", () => resolve(data)));
  return { client, closed };
}
test("close during DNS never resurrects a listener after late resolution", { timeout: 3000 }, async t => {
  const path = await root(t);
  let resolveDns, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const broker = new GrantScopedEgressBroker({ socketPath: path, grantDigest: D, allowedOrigins: ["http://example.com"],
    allowPrivateNetworkForTests: true, resolver: () => { entered(); return new Promise(resolve => { resolveDns = resolve; }); } });
  const starting = broker.start();
  const rejected = assert.rejects(starting, /closed/);
  await ready;
  await broker.close(); await rejected;
  resolveDns([{ address: "127.0.0.1", family: 4 }]);
  await new Promise(resolve => setTimeout(resolve, 20));
  await assert.rejects(stat(path), { code: "ENOENT" });
  await assert.rejects(broker.start(), /already|state|started/);
});
test("close waits for active upstream and downstream sockets to disappear", { timeout: 5000 }, async t => {
  const path = await root(t);
  const sockets = new Set();
  let accepted;
  const ready = new Promise(resolve => { accepted = resolve; });
  const server = http.createServer((_request, response) => { response.writeHead(200); response.write("partial"); accepted(); });
  server.on("connection", socket => { sockets.add(socket); socket.on("error", () => {}); socket.once("close", () => sockets.delete(socket)); });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => { for (const socket of sockets) socket.destroy(); server.close(); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  const broker = new GrantScopedEgressBroker({ socketPath: path, grantDigest: D, allowedOrigins: [origin], allowPrivateNetworkForTests: true });
  await broker.start(); t.after(() => broker.close());
  const request = read(path, `${origin}/pending`);
  await ready;
  const peerClosed = [...sockets].map(socket => new Promise(resolve => socket.once("close", resolve)));
  await Promise.all([broker.close(), request.closed, ...peerClosed]);
  assert.equal(sockets.size, 0);
  assert.equal(request.client.closed, true);
});
test("HTTP response budget aborts actual oversized upstream response", { timeout: 5000 }, async t => {
  const path = await root(t);
  const server = http.createServer((_req, res) => res.end("x".repeat(64 * 1024)));
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  const broker = new GrantScopedEgressBroker({ socketPath: path, grantDigest: D, allowedOrigins: [origin], allowPrivateNetworkForTests: true,
    maxResponseBytes: 32 });
  await broker.start(); t.after(() => broker.close());
  const response = await read(path, `${origin}/large`).closed;
  assert.equal(response.includes(Buffer.from("x".repeat(33))), false);
  await broker.close();
});
