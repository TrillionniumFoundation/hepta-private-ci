import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";

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
const SEMANTIC = {
  controls: [],
  forms: [],
  links: [],
  schema: "hepta.browser.semantic-observation.v1",
  title: "Example",
  truncated: false,
  viewport: { height: 720, width: 1280 },
  visibleText: "hello",
};
const SEMANTIC_DIGEST = createHash("sha256")
  .update(JSON.stringify(SEMANTIC))
  .digest("hex");

function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function startInput(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D1,
    generation: 1,
    allowedOrigins: ["https://example.com"],
    ...overrides,
  };
}

function fakeLauncher({
  holdDispatchResponse = null,
  holdDispatchBoundary = null,
  rejectDispatchBeforeBoundary = false,
  capture = null,
  corruptResponseBinding = false,
} = {}) {
  return {
    async verify() {},
    posture: {
      sourceContractOnly: true,
      inheritedPrivateChannel: true,
      externalNetworkDenied: true,
      ambientEnvironmentDenied: true,
      userHomeHidden: true,
      hostFilesystemRestricted: true,
      parentDeathCleanup: true,
      resourceLimitsConfigured: true,
    },
    spawn(spec) {
      const child = new EventEmitter();
      child.pid = 4242;
      child.stdin = new PassThrough();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.killed = false;
      child.kill = () => {
        child.killed = true;
        queueMicrotask(() => child.emit("exit", null, "SIGKILL"));
        return true;
      };
      if (capture) {
        capture.child = child;
        capture.spec = spec;
      }
      const decoder = new WorkerFrameDecoder();
      let sequence = 1;
      child.stdin.on("data", (chunk) => {
        for (const request of decoder.push(chunk)) {
          let dispatchBoundary = null;
          if (request.kind === "dispatch" && !rejectDispatchBeforeBoundary) {
            dispatchBoundary = encodeWorkerFrame(
              buildWorkerFrame({
                sessionId: request.sessionId,
                generation: request.generation,
                sequence: sequence++,
                kind: "dispatch_boundary",
                requestId: request.requestId,
                payload: {
                  localDispatchCrossed: true,
                  requestKind: request.kind,
                  requestPayloadDigest: request.payloadDigest,
                },
              }),
            );
          }
          let observation;
          switch (request.kind) {
            case "start":
              observation = { started: true };
              break;
            case "observe":
              observation = {
                pageGeneration: 1,
                documentDigest: D1,
                semanticDigest: SEMANTIC_DIGEST,
                semanticObservation: SEMANTIC,
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
              payload:
                request.kind === "dispatch" && rejectDispatchBeforeBoundary
                  ? {
                      ok: false,
                      requestKind: request.kind,
                      requestPayloadDigest: request.payloadDigest,
                      error: "worker page generation drifted before dispatch",
                    }
                  : {
                      ok: true,
                      requestKind: request.kind,
                      requestPayloadDigest: corruptResponseBinding
                        ? D1
                        : request.payloadDigest,
                      observation,
                    },
            }),
          );
          if (request.kind === "dispatch" && holdDispatchBoundary) {
            holdDispatchBoundary.release = () => {
              child.stdout.write(dispatchBoundary);
              child.stdout.write(encoded);
            };
            holdDispatchBoundary.requestId = request.requestId;
          } else {
            if (dispatchBoundary) child.stdout.write(dispatchBoundary);
            if (request.kind === "dispatch" && holdDispatchResponse) {
              holdDispatchResponse.release = () => child.stdout.write(encoded);
              holdDispatchResponse.requestId = request.requestId;
            } else {
              child.stdout.write(encoded);
            }
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
  const started = await driver.start(startInput());
  return { driver, started, root };
}

test("artifact-bound subprocess driver uses only the private framed channel", async () => {
  const { driver, started } = await preparedDriver();
  assert.equal(driver.supportsAbort, true);
  assert.equal(started.processId, "servo.pid.4242");
  assert.match(started.profileOwnerDigest, /^[0-9a-f]{64}$/);
  const observed = await driver.observe({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
    observationBudget: 1024,
  });
  assert.equal(observed.origin, "https://example.com");
  assert.equal(observed.semanticDigest, SEMANTIC_DIGEST);
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

test("host-private metadata binds principal ownership and stderr is drained", async () => {
  const capture = {};
  const { driver, started, root } = await preparedDriver({
    launcher: fakeLauncher({ capture }),
  });
  const profileRoot = join(root, "profiles");
  const rootEntries = await readdir(profileRoot);
  const ownerEntries = rootEntries.filter((name) =>
    name.startsWith(".hepta-profile-owner."),
  );
  assert.equal(ownerEntries.length, 1);
  const ownerPath = join(profileRoot, ownerEntries[0]);
  assert.equal(
    ownerPath.startsWith(`${capture.spec.profileDir}${sep}`),
    false,
    "ownership metadata must not live under the writable profile bind",
  );
  assert.equal(
    capture.spec.workerPath.startsWith(`${capture.spec.profileDir}${sep}`),
    false,
    "verified worker copy must not live under the writable profile bind",
  );
  assert.deepEqual(
    (await readdir(capture.spec.profileDir)).filter((name) =>
      name.startsWith(".hepta-profile-owner."),
    ),
    [],
  );
  const owner = JSON.parse(await readFile(ownerPath, "utf8"));
  assert.deepEqual(owner, {
    schema: "hepta.browser.profile-owner.v1",
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    manifestDigest: D1,
    grantDigest: D1,
  });
  if (process.platform !== "win32") {
    assert.equal((await stat(ownerPath)).mode & 0o077, 0);
  }
  assert.equal(capture.child.stderr.readableFlowing, true);
  await driver.stop({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
  });
});



test("failed spawn removes host-private staging and writable profile bytes", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-start-failure-"));
  const workerPath = join(root, "worker.bin");
  const workerBytes = Buffer.from("fake-qualified-worker", "utf8");
  const profileRoot = join(root, "profiles");
  await writeFile(workerPath, workerBytes, { mode: 0o700 });
  const base = fakeLauncher();
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(workerBytes),
    profileRoot,
    launcher: {
      ...base,
      spawn() {
        throw new Error("synthetic spawn failure");
      },
    },
  });
  await assert.rejects(driver.start(startInput()), /synthetic spawn failure/);
  assert.deepEqual(await readdir(profileRoot), []);
});

test("dispatch returns at worker admission boundary without waiting for worker execution response", async () => {
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

test("pipe write alone does not cross the final-use dispatch boundary", async () => {
  const held = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ holdDispatchBoundary: held }),
  });
  const dispatch = driver.dispatch({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    pageGeneration: 0,
    documentDigest: null,
    operationId: "operation.worker-boundary",
    typedAction: {
      kind: "navigate",
      url: "https://example.com/",
      policyDigest: D1,
      expectedRevision: 1,
    },
  });
  const timeout = Symbol("timeout");
  const beforeBoundary = await Promise.race([
    dispatch,
    new Promise((resolve) => setTimeout(() => resolve(timeout), 25)),
  ]);
  assert.equal(beforeBoundary, timeout);
  assert.equal(typeof held.release, "function");
  held.release();
  const result = await dispatch;
  assert.equal(result.terminalObserved, false);
});

test("worker can reject stale dispatch before boundary without killing the channel", async () => {
  const capture = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({
      rejectDispatchBeforeBoundary: true,
      capture,
    }),
  });
  await assert.rejects(
    driver.dispatch({
      profileId: "profile.1",
      processId: started.processId,
      profileGeneration: 1,
      pageGeneration: 1,
      documentDigest: D1,
      operationId: "operation.stale",
      typedAction: { kind: "click", selector: "button:nth-of-type(1)" },
    }),
    (error) =>
      error?.name === "BrowserWorkerPreDispatchError" &&
      error?.code === "BROWSER_WORKER_PRE_DISPATCH_REJECTED" &&
      /^[0-9a-f]{64}$/.test(error?.outcomeDigest),
  );
  assert.equal(capture.child.killed, false);
  const observed = await driver.observe({
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    observationBudget: 1024,
  });
  assert.equal(observed.origin, "https://example.com");
});

test("abort before worker admission boundary contains the worker before dispatch settles", async () => {
  const held = {};
  const capture = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ holdDispatchBoundary: held, capture }),
  });
  const controller = new AbortController();
  const dispatch = driver.dispatch(
    {
      profileId: "profile.1",
      processId: started.processId,
      profileGeneration: 1,
      operationId: "operation.abort",
    },
    { signal: controller.signal },
  );
  controller.abort(new Error("deadline"));
  await assert.rejects(dispatch, /exited before response|deadline|aborted/);
  assert.equal(capture.child.killed, true);
});

test("worker response must echo exact request kind and payload digest", async () => {
  const capture = {};
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-driver-"));
  const workerPath = join(root, "worker.bin");
  const workerBytes = Buffer.from("fake-qualified-worker", "utf8");
  await writeFile(workerPath, workerBytes, { mode: 0o700 });
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(workerBytes),
    profileRoot: join(root, "profiles"),
    launcher: fakeLauncher({ capture, corruptResponseBinding: true }),
  });
  await assert.rejects(driver.start(startInput()), /did not bind the exact request/);
  assert.equal(capture.child.killed, true);
});

test("subprocess driver persisted recovery fails closed without a trusted observer", async () => {
  const driver = new SubprocessBrowserDriver({
    workerPath: "/worker",
    workerDigest: D1,
    profileRoot: "/profiles",
    launcher: fakeLauncher(),
  });
  const observed = await driver.reconcilePersisted({
    profileId: "profile.1",
    principalId: "principal.1",
    profileGeneration: 1,
    operationId: "operation.persisted",
  });
  assert.deepEqual(observed, {
    terminalObserved: false,
    observationReason: "persisted_reconciler_unavailable",
  });
});

test("subprocess driver delegates persisted recovery only to an explicit trusted observer", async () => {
  let received;
  const driver = new SubprocessBrowserDriver({
    workerPath: "/worker",
    workerDigest: D1,
    profileRoot: "/profiles",
    launcher: fakeLauncher(),
    persistedReconciler: async (input, { signal }) => {
      received = input;
      assert.equal(signal?.aborted, false);
      return {
        terminalObserved: true,
        status: "succeeded",
        outcomeDigest: D1,
      };
    },
  });
  const controller = new AbortController();
  const observed = await driver.reconcilePersisted(
    {
      profileId: "profile.1",
      principalId: "principal.1",
      profileGeneration: 1,
      operationId: "operation.persisted",
    },
    { signal: controller.signal },
  );
  assert.equal(received.operationId, "operation.persisted");
  assert.equal(observed.terminalObserved, true);
  assert.equal(observed.status, "succeeded");
});

test("subprocess driver containment kills the quarantined worker and still permits cleanup", async () => {
  const capture = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ capture }),
  });
  const contained = await driver.contain({
    profileId: "profile.1",
    generation: 1,
    processId: started.processId,
  });
  assert.equal(contained.contained, true);
  assert.equal(capture.child.killed, true);
  const stopped = await driver.stop({
    profileId: "profile.1",
    generation: 1,
  });
  assert.equal(stopped.stopped, true);
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
    driver.start(startInput()),
    /artifact digest mismatch/,
  );
});

test(
  "Linux bubblewrap source contract exposes only the explicit runtime closure",
  { skip: process.platform !== "linux" },
  () => {
    const launcher = new LinuxBubblewrapLauncher({
      bwrapPath: "/usr/bin/bwrap",
      bwrapDigest: D1,
      prlimitPath: "/usr/bin/prlimit",
      prlimitDigest: D1,
    });
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
    assert.equal(mountedSources.includes("/etc/ssl"), false);
    assert.equal(mountedSources.includes("/etc/ssl/certs"), true);
    assert.equal(mountedSources.includes("/usr/share/ca-certificates"), true);
    assert.equal(argv.at(-1), "/hepta-worker");
    assert.equal(launcher.posture.sourceContractOnly, true);
    assert.equal(launcher.posture.hostFilesystemRestricted, true);
    assert.equal(launcher.posture.resourceLimitsConfigured, true);
    assert.deepEqual(launcher.resourceLimits, {
      maxAddressSpaceBytes: 8 * 1024 * 1024 * 1024,
      maxCpuSeconds: 300,
      maxOpenFiles: 4096,
      maxProcesses: 256,
    });
    const spec = launcher.spawnSpec({
      workerPath: "/opt/hepta/servo-worker",
      profileDir: "/var/lib/hepta/browser/profile-1",
    });
    assert.equal(spec.command, "/usr/bin/prlimit");
    assert.equal(spec.args.includes("--as=8589934592:8589934592"), true);
    assert.equal(spec.args.includes("--cpu=300:300"), true);
    assert.equal(spec.args.includes("--nofile=4096:4096"), true);
    assert.equal(spec.args.includes("--nproc=256:256"), true);
  },
);

test("subprocess driver rejects launchers without the complete source isolation contract", () => {
  assert.throws(
    () =>
      new SubprocessBrowserDriver({
        workerPath: "/worker",
        workerDigest: D1,
        profileRoot: "/profiles",
        launcher: { posture: {}, spawn() {} },
      }),
    /source-contract-only/,
  );

  assert.throws(
    () =>
      new SubprocessBrowserDriver({
        workerPath: "/worker",
        workerDigest: D1,
        profileRoot: "/profiles",
        launcher: {
          posture: {
            sourceContractOnly: true,
            inheritedPrivateChannel: true,
            externalNetworkDenied: true,
            ambientEnvironmentDenied: true,
            userHomeHidden: true,
            hostFilesystemRestricted: false,
            parentDeathCleanup: true,
            resourceLimitsConfigured: true,
          },
          spawn() {},
        },
      }),
    /hostFilesystemRestricted/,
  );
});


test("subprocess driver rejects a pre-existing broad profile root", async (t) => {
  if (process.platform === "win32") {
    t.skip("Unix mode bits are not authoritative on Windows");
    return;
  }
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-root-mode-"));
  const workerPath = join(root, "worker.bin");
  const workerBytes = Buffer.from("fake-qualified-worker", "utf8");
  const profileRoot = join(root, "profiles");
  await writeFile(workerPath, workerBytes, { mode: 0o700 });
  await mkdir(profileRoot, { mode: 0o700 });
  await chmod(profileRoot, 0o755);
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(workerBytes),
    profileRoot,
    launcher: fakeLauncher(),
  });
  await assert.rejects(
    driver.start(startInput()),
    /profile root permissions are too broad/,
  );
});


test(
  "Linux bubblewrap launcher binds the exact selected binary digest",
  { skip: process.platform !== "linux" },
  async () => {
    const root = await mkdtemp(join(tmpdir(), "hepta-bwrap-identity-"));
    const bwrapPath = join(root, "bwrap");
    const prlimitPath = join(root, "prlimit");
    const bwrapBytes = Buffer.from("fake-bwrap-exact-bytes", "utf8");
    const prlimitBytes = Buffer.from("fake-prlimit-exact-bytes", "utf8");
    await writeFile(bwrapPath, bwrapBytes, { mode: 0o500 });
    await writeFile(prlimitPath, prlimitBytes, { mode: 0o500 });
    const launcher = new LinuxBubblewrapLauncher({
      bwrapPath,
      bwrapDigest: digest(bwrapBytes),
      prlimitPath,
      prlimitDigest: digest(prlimitBytes),
    });
    await launcher.verify();

    const mismatchedBwrap = new LinuxBubblewrapLauncher({
      bwrapPath,
      bwrapDigest: D1,
      prlimitPath,
      prlimitDigest: digest(prlimitBytes),
    });
    await assert.rejects(mismatchedBwrap.verify(), /Bubblewrap launcher digest mismatch/);
    const mismatchedPrlimit = new LinuxBubblewrapLauncher({
      bwrapPath,
      bwrapDigest: digest(bwrapBytes),
      prlimitPath,
      prlimitDigest: D1,
    });
    await assert.rejects(mismatchedPrlimit.verify(), /prlimit launcher digest mismatch/);
  },
);
