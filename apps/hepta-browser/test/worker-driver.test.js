import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createHash } from "node:crypto";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";
import {
  WorkerFrameDecoder,
  buildWorkerFrame,
  encodeWorkerFrame,
} from "../src/worker-protocol.js";

const D1 = "1".repeat(64);

function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function fakeLauncher({ holdDispatchResponse = null } = {}) {
  return {
    posture: {
      inheritedPrivateChannel: true,
      externalNetworkDenied: true,
      ambientEnvironmentDenied: true,
      userHomeHidden: true,
      hostFilesystemRestricted: true,
      parentDeathCleanup: true,
    },
    spawn() {
      const child = new EventEmitter();
      child.pid = 4242;
      child.stdin = new PassThrough();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kill = () => true;
      const decoder = new WorkerFrameDecoder();
      let sequence = 1;
      child.stdin.on("data", (chunk) => {
        for (const request of decoder.push(chunk)) {
          let observation;
          switch (request.kind) {
            case "start":
              observation = { started: true };
              break;
            case "observe":
              observation = {
                pageGeneration: 1,
                documentDigest: D1,
                origin: "https://example.com",
              };
              break;
            case "dispatch":
              observation = { terminalObserved: false };
              break;
            case "reconcile":
              observation = {
                terminalObserved: true,
                status: "succeeded",
                outcomeDigest: D1,
              };
              break;
            case "stop":
              observation = { stopped: true };
              break;
            default:
              throw new Error(`unexpected fake worker request ${request.kind}`);
          }
          const encoded = encodeWorkerFrame(
            buildWorkerFrame({
              sessionId: request.sessionId,
              generation: request.generation,
              sequence: sequence++,
              kind: "response",
              requestId: request.requestId,
              payload: { ok: true, observation },
            }),
          );
          if (request.kind === "dispatch" && holdDispatchResponse) {
            holdDispatchResponse.release = () => child.stdout.write(encoded);
            holdDispatchResponse.requestId = request.requestId;
          } else {
            child.stdout.write(encoded);
          }
        }
      });
      return child;
    },
  };
}

async function preparedDriver({ launcher = fakeLauncher() } = {}) {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-driver-"));
  const workerPath = join(root, "worker.bin");
  const workerBytes = Buffer.from("fake-qualified-worker", "utf8");
  await writeFile(workerPath, workerBytes, { mode: 0o700 });
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(workerBytes),
    profileRoot: join(root, "profiles"),
    launcher,
  });
  const started = await driver.start({
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D1,
    generation: 1,
    allowedOrigins: ["https://example.com"],
  });
  return { driver, started };
}

test("artifact-bound subprocess driver uses only the private framed channel", async () => {
  const { driver, started } = await preparedDriver();
  assert.equal(started.processId, "servo.pid.4242");
  const observed = await driver.observe({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
    observationBudget: 1024,
  });
  assert.equal(observed.origin, "https://example.com");
  const dispatched = await driver.dispatch({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    operationId: "operation.1",
  });
  assert.equal(dispatched.terminalObserved, false);
  const terminal = await driver.reconcile({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    generation: 1,
    operationId: "operation.1",
  });
  assert.equal(terminal.status, "succeeded");
  const stopped = await driver.stop({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
  });
  assert.equal(stopped.stopped, true);
});

test("dispatch returns at local pipe write without waiting for worker execution response", async () => {
  const held = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ holdDispatchResponse: held }),
  });
  const timeout = Symbol("timeout");
  const dispatched = await Promise.race([
    driver.dispatch({
      profileId: "profile.1",
      processId: started.processId,
      profileGeneration: 1,
      operationId: "operation.boundary",
    }),
    new Promise((resolve) => setTimeout(() => resolve(timeout), 100)),
  ]);
  assert.notEqual(dispatched, timeout);
  assert.equal(dispatched.terminalObserved, false);
  assert.equal(typeof held.release, "function");

  // Only after the authority/local-dispatch boundary has returned do we allow
  // the worker's execution response to arrive. Reconciliation then observes
  // terminality through a distinct request.
  held.release();
  await new Promise((resolve) => setImmediate(resolve));
  const terminal = await driver.reconcile({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    generation: 1,
    operationId: "operation.boundary",
  });
  assert.equal(terminal.terminalObserved, true);
  assert.equal(terminal.status, "succeeded");
});

test("subprocess driver fails closed on worker artifact digest drift", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-driver-"));
  const workerPath = join(root, "worker.bin");
  await writeFile(workerPath, "not-the-qualified-bytes", { mode: 0o700 });
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: D1,
    profileRoot: join(root, "profiles"),
    launcher: fakeLauncher(),
  });
  await assert.rejects(
    driver.start({ profileId: "profile.1", generation: 1 }),
    /artifact digest mismatch/,
  );
});

test(
  "Linux bubblewrap launcher exposes only the explicit runtime closure",
  { skip: process.platform !== "linux" },
  () => {
    const launcher = new LinuxBubblewrapLauncher({ bwrapPath: "/usr/bin/bwrap" });
    const argv = launcher.argv({
      workerPath: "/opt/hepta/servo-worker",
      profileDir: "/var/lib/hepta/browser/profile-1",
    });
    assert.equal(argv.includes("--unshare-all"), true);
    assert.equal(argv.includes("--share-net"), false);
    assert.equal(argv.includes("--clearenv"), true);
    assert.deepEqual(argv.slice(4, 6), ["--tmpfs", "/"]);
    for (let index = 0; index < argv.length - 2; index += 1) {
      assert.equal(
        argv[index] === "--ro-bind" && argv[index + 1] === "/" && argv[index + 2] === "/",
        false,
      );
    }
    const mountedSources = [];
    for (let index = 0; index < argv.length - 2; index += 1) {
      if (argv[index] === "--ro-bind" || argv[index] === "--ro-bind-try") {
        mountedSources.push(argv[index + 1]);
      }
    }
    assert.equal(mountedSources.includes("/usr"), false);
    assert.equal(mountedSources.some((path) => path.startsWith("/usr/bin")), false);
    assert.equal(mountedSources.some((path) => path.startsWith("/usr/local")), false);
    assert.equal(mountedSources.some((path) => path === "/home" || path.startsWith("/home/")), false);
    assert.equal(mountedSources.some((path) => path === "/root" || path.startsWith("/root/")), false);
    assert.equal(mountedSources.some((path) => path.startsWith("/var/lib")), false);
    assert.equal(mountedSources.some((path) => path.startsWith("/var/run")), false);
    assert.equal(mountedSources.includes("/usr/lib"), true);
    assert.equal(mountedSources.includes("/var/cache/fontconfig"), true);
    assert.equal(argv.at(-1), "/hepta-worker");
    assert.equal(launcher.posture.hostFilesystemRestricted, true);
  },
);

test("subprocess driver rejects launchers that do not enforce the isolation posture", () => {
  assert.throws(
    () =>
      new SubprocessBrowserDriver({
        workerPath: "/worker",
        workerDigest: D1,
        profileRoot: "/profiles",
        launcher: { posture: {}, spawn() {} },
      }),
    /does not enforce/,
  );

  assert.throws(
    () =>
      new SubprocessBrowserDriver({
        workerPath: "/worker",
        workerDigest: D1,
        profileRoot: "/profiles",
        launcher: {
          posture: {
            inheritedPrivateChannel: true,
            externalNetworkDenied: true,
            ambientEnvironmentDenied: true,
            userHomeHidden: true,
            hostFilesystemRestricted: false,
            parentDeathCleanup: true,
          },
          spawn() {},
        },
      }),
    /hostFilesystemRestricted/,
  );
});
