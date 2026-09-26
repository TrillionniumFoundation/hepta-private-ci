import assert from "node:assert/strict";
import net from "node:net";
import test from "node:test";
import {
  mkdir,
  mkdtemp,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { EffectScopedNetworkDriver } from "../src/effect-network-driver.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const PROCESS_ID =
  "servo.pid.2147483000.00000000-0000-4000-8000-000000000001";

function listen(server, path) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(path, () => {
      server.off("error", reject);
      resolve();
    });
  });
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

function proxyRequest(socketPath, absoluteUrl) {
  return new Promise((resolve) => {
    const socket = net.createConnection(socketPath);
    const chunks = [];
    socket.on("connect", () => {
      socket.end(
        `GET ${absoluteUrl} HTTP/1.1\r\n` +
          `Host: ${new URL(absoluteUrl).host}\r\n` +
          "Connection: close\r\n\r\n",
      );
    });
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.on("error", () => resolve(Buffer.concat(chunks)));
    socket.on("close", () => resolve(Buffer.concat(chunks)));
  });
}

test(
  "production wrapper inserts an operation gate at the worker-visible socket",
  { skip: process.platform === "win32" },
  async (t) => {
    const root = await mkdtemp(join(tmpdir(), "hepta-effect-network-driver-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const profileRoot = join(root, "profiles");
    await mkdir(profileRoot, { mode: 0o700 });
    const profileDir = join(
      profileRoot,
      "profile.1.1.00000000-0000-4000-8000-000000000001",
    );
    const workerSocket = join(profileDir, ".hepta-egress.sock");
    let policyServer = null;
    let settleDispatch;

    const inner = {
      supportsAbort: true,
      maxActiveProfiles: 4,
      maxOutstandingOperations: 1,
      async start() {
        await mkdir(profileDir, { mode: 0o700 });
        policyServer = net.createServer((socket) => {
          socket.once("data", () => {
            socket.end(
              "HTTP/1.1 200 OK\r\n" +
                "Content-Length: 2\r\n" +
                "Connection: close\r\n\r\n" +
                "ok",
            );
          });
        });
        await listen(policyServer, workerSocket);
        return { started: true, processId: PROCESS_ID };
      },
      async observe() {
        return { observed: true };
      },
      async dispatch() {
        return {
          terminalObserved: false,
          settlement: new Promise((resolve) => {
            settleDispatch = resolve;
          }),
        };
      },
      async reconcile() {
        return {
          terminalObserved: true,
          status: "succeeded",
          outcomeDigest: D3,
        };
      },
      async reconcilePersisted() {
        return { terminalObserved: false };
      },
      async contain() {
        if (policyServer) await close(policyServer);
        return { contained: true };
      },
      async stop() {
        if (policyServer) await close(policyServer);
        return { stopped: true };
      },
    };

    const driver = new EffectScopedNetworkDriver({
      driver: inner,
      profileRoot,
      maxRequestBytes: 4096,
      maxResponseBytes: 4096,
    });
    const origin = "http://effect.test:8080";
    await driver.start({
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      grantDigest: D1,
      allowedOrigins: [origin],
    });

    const before = await proxyRequest(workerSocket, `${origin}/before`);
    assert.equal(before.length, 0);

    const dispatched = await driver.dispatch({
      profileId: "profile.1",
      processId: PROCESS_ID,
      profileGeneration: 1,
      pageGeneration: 0,
      operationId: "operation.1",
      effectGrantDigest: D2,
      destinationOrigin: origin,
      deadlineMs: Date.now() + 10_000,
    });
    const response = await proxyRequest(workerSocket, `${origin}/allowed`);
    assert.match(response.toString("latin1"), /HTTP\/1\.1 200 OK/);
    assert.equal(response.subarray(-2).toString(), "ok");

    settleDispatch({
      terminalObserved: true,
      status: "succeeded",
      outcomeDigest: D3,
    });
    const terminal = await dispatched.settlement;
    assert.equal(terminal.terminalObserved, true);
    assert.equal(
      terminal.egressReceipt.schema,
      "hepta.browser.egress-operation-receipt.v1",
    );
    assert.equal(terminal.egressReceipt.operationId, "operation.1");
    assert.equal(terminal.egressReceipt.effectGrantDigest, D2);
    assert.equal(terminal.egressReceipt.destinationOrigin, origin);
    assert.equal(terminal.egressReceipt.status, "succeeded");
    assert.equal(terminal.egressReceipt.connectionCount, 1);

    const after = await proxyRequest(workerSocket, `${origin}/after`);
    assert.equal(after.length, 0);
    const stopped = await driver.stop({
      profileId: "profile.1",
      processId: PROCESS_ID,
      generation: 1,
    });
    assert.equal(stopped.stopped, true);
  },
);
