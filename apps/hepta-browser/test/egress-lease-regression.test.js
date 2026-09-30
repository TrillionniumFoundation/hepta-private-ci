import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { EffectScopedEgressBroker } from "../src/effect-egress-gate.js";

const digest = "1".repeat(64);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fixture(t, allowedOrigins = ["https://example.com"]) {
  const root = await mkdtemp(join(tmpdir(), "browser-egress-lease-"));
  const peers = new Set();
  let connections = 0;
  const received = [];
  const policy = net.createServer((socket) => {
    connections += 1;
    peers.add(socket);
    socket.on("error", () => {});
    socket.once("close", () => peers.delete(socket));
    socket.on("data", (chunk) => received.push(Buffer.from(chunk)));
  });
  const upstreamSocketPath = join(root, "policy.sock");
  await new Promise((resolve, reject) => {
    policy.once("error", reject);
    policy.listen(upstreamSocketPath, resolve);
  });
  const socketPath = join(root, "worker.sock");
  const broker = new EffectScopedEgressBroker({
    socketPath, upstreamSocketPath, grantDigest: digest,
    allowedOrigins,
  });
  await broker.start();
  const clients = new Set();
  t.after(async () => {
    for (const socket of clients) socket.destroy();
    await broker.close();
    for (const socket of peers) socket.destroy();
    await new Promise((resolve) => policy.close(resolve));
    await rm(root, { recursive: true, force: true });
  });
  async function connect() {
    const socket = net.createConnection(socketPath);
    clients.add(socket);
    socket.on("error", () => {});
    await new Promise((resolve, reject) => {
      socket.once("connect", resolve);
      socket.once("error", reject);
    });
    return socket;
  }
  return { broker, connect, connections: () => connections, peers, received: () => Buffer.concat(received).toString("latin1") };
}

const operation = (id, deadlineMs) => ({ operationId: id, effectGrantDigest: digest,
  destinationOrigin: "https://example.com", deadlineMs });
const header = "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n";

test("a partial header cannot acquire egress after the operation lease expires", async (t) => {
  const { broker, connect, connections } = await fixture(t);
  broker.admitOperation(operation("operation.expired-header", Date.now() + 60));
  const socket = await connect();
  socket.write("CONNECT example.com:443 HTTP/1.1\r\n");
  await pause(100);
  if (!socket.destroyed) socket.write("Host: example.com:443\r\n\r\n");
  await pause(30);
  assert.equal(connections(), 0, "expired admission must not reach the policy broker");
});

test("operation expiry actively closes an already forwarded tunnel", async (t) => {
  const { broker, connect, connections, peers } = await fixture(t);
  broker.admitOperation(operation("operation.expired-tunnel", Date.now() + 150));
  const socket = await connect();
  socket.write(header);
  await pause(30);
  assert.equal(connections(), 1);
  await pause(200);
  assert.equal(peers.size, 0, "expiry must tear down the upstream tunnel without a new API call");
  assert.equal(socket.destroyed, true);
});

test("a denied connection is contained without an unhandled socket error", async (t) => {
  const { connect, connections } = await fixture(t);
  const socket = await connect();
  socket.write(header);
  await pause(30);
  assert.equal(socket.destroyed, true);
  assert.equal(connections(), 0);
});

test("closing the worker peer tears down the policy peer", async (t) => {
  const { broker, connect, peers } = await fixture(t);
  broker.admitOperation(operation("operation.peer-loss", Date.now() + 5000));
  const socket = await connect();
  socket.write(header);
  await pause(30);
  assert.equal(peers.size, 1);
  socket.destroy();
  await pause(30);
  assert.equal(peers.size, 0);
});

test("a completed operation cannot reopen egress under the same identity", async (t) => {
  const { broker } = await fixture(t);
  const input = operation("operation.replay", Date.now() + 5000);
  broker.admitOperation(input);
  const receipt = broker.completeOperation(input.operationId);
  assert.deepEqual(broker.completeOperation(input.operationId), receipt);
  assert.throws(() => broker.admitOperation(input), /cannot be readmitted/);
});

test("completion contains a partial-header connection before ownership changes", async (t) => {
  const { broker, connect, connections } = await fixture(t);
  broker.admitOperation(operation("operation.old", Date.now() + 5000));
  const socket = await connect();
  socket.write("CONNECT example.com:443 HTTP/1.1\r\n");
  await pause(10);
  broker.completeOperation("operation.old");
  broker.admitOperation(operation("operation.new", Date.now() + 5000));
  await pause(20);
  if (!socket.destroyed) socket.write("Host: example.com:443\r\n\r\n");
  await pause(20);
  assert.equal(socket.destroyed, true);
  assert.equal(connections(), 0);
});

async function httpFixture(t) {
  const result = await fixture(t, ["http://one.test", "http://two.test"]);
  result.broker.admitOperation({ operationId: "operation.http", effectGrantDigest: digest,
    destinationOrigin: "http://one.test", deadlineMs: Date.now() + 5000 });
  return result;
}

const httpRequest = (origin, extra = "", method = "GET") =>
  `${method} ${origin}/ HTTP/1.1\r\nHost: ${new URL(origin).host}\r\n${extra}\r\n`;

test("a second HTTP request on the same socket cannot widen the operation origin", async (t) => {
  const { connect, received } = await httpFixture(t);
  const socket = await connect();
  socket.write(httpRequest("http://one.test"));
  await pause(25);
  assert.match(received(), /GET http:\/\/one.test/);
  socket.write(httpRequest("http://two.test"));
  await pause(25);
  assert.equal(received().includes("two.test"), false);
  assert.equal(socket.destroyed, true);
});

test("coalesced HTTP pipeline headers are independently checked before forwarding", async (t) => {
  const { connect, received } = await httpFixture(t);
  const socket = await connect();
  socket.write(httpRequest("http://one.test") + httpRequest("http://two.test"));
  await pause(30);
  assert.equal(received().includes("two.test"), false);
  assert.equal(socket.destroyed, true);
});

test("HTTP body framing preserves body bytes while gating subsequent requests", async (t) => {
  const { connect, received } = await httpFixture(t);
  const socket = await connect();
  const body = "GET http://two.test/not-a-request";
  const request = httpRequest("http://one.test", `Content-Length: ${Buffer.byteLength(body)}\r\n`, "POST") + body;
  for (const part of [request.slice(0, 11), request.slice(11, -5), request.slice(-5)]) {
    socket.write(part);
    await pause(5);
  }
  socket.write(httpRequest("http://one.test"));
  await pause(30);
  assert.equal(received(), request + httpRequest("http://one.test"));
  assert.equal(socket.destroyed, false);
});

test("chunked request bodies and trailers remain bounded without hiding a second origin", async (t) => {
  const { connect, received } = await httpFixture(t);
  const socket = await connect();
  const first = httpRequest("http://one.test", "Transfer-Encoding: chunked\r\n", "POST") +
    "3\r\nabc\r\n0\r\nX-Trace: safe\r\n\r\n";
  socket.write(first);
  await pause(25);
  assert.equal(received(), first);
  socket.write(httpRequest("http://two.test"));
  await pause(25);
  assert.equal(received(), first);
  assert.equal(socket.destroyed, true);
});

for (const [name, request] of [
  ["Host substitution", "GET http://one.test/ HTTP/1.1\r\nHost: two.test\r\n\r\n"],
  ["ambiguous body length", httpRequest("http://one.test", "Content-Length: 4\r\nTransfer-Encoding: chunked\r\n", "POST")],
  ["protocol upgrade", httpRequest("http://one.test", "Connection: upgrade\r\nUpgrade: websocket\r\n")],
]) {
  test(`HTTP ${name} is rejected before request bytes reach the policy channel`, async (t) => {
    const { connect, received } = await httpFixture(t);
    const socket = await connect();
    socket.write(request);
    await pause(30);
    assert.equal(received(), "");
    assert.equal(socket.destroyed, true);
  });
}

test("late settlement returns its original receipt without closing the next operation", async (t) => {
  const { broker } = await fixture(t);
  broker.admitOperation(operation("operation.old", Date.now() + 5000));
  const first = broker.completeOperation("operation.old", { status: "lease_expired" });
  broker.admitOperation(operation("operation.next", Date.now() + 5000));
  assert.deepEqual(broker.completeOperation("operation.old"), first);
  assert.equal(broker.completeOperation("operation.next").operationId, "operation.next");
});
