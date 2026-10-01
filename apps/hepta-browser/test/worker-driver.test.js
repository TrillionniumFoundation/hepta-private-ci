import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createHash } from "node:crypto";
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  realpath,
  symlink,
  writeFile,
} from "node:fs/promises";
import { spawn } from "node:child_process";
import { once } from "node:events";
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

function fakeLauncher({
  holdDispatchResponse = null,
  payloadForResponse,
  onSpawn,
  onRequest,
  holdKinds = [],
} = {}) {
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
      onSpawn?.(child);
      const decoder = new WorkerFrameDecoder();
      let sequence = 1;
      child.stdin.on("data", (chunk) => {
        for (const request of decoder.push(chunk)) {
          onRequest?.(request);
          if (holdKinds.includes(request.kind)) continue;
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
              payload: payloadForResponse?.(request, observation) ?? {
                ok: true,
                observation,
              },
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

async function preparedDriver({
  launcher = fakeLauncher(),
  startTimeoutMs = 5_000,
} = {}) {
  const root = await realpath(
    await mkdtemp(join(tmpdir(), "hepta-worker-driver-")),
  );
  const workerPath = join(root, "worker.bin");
  const workerBytes = Buffer.from("fake-qualified-worker", "utf8");
  await writeFile(workerPath, workerBytes, { mode: 0o700 });
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(workerBytes),
    profileRoot: join(root, "profiles"),
    launcher,
  });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), startTimeoutMs);
  try {
    const started = await driver.start(
      {
        profileId: "profile.1",
        principalId: "principal.1",
        manifestDigest: D1,
        grantDigest: D1,
        generation: 1,
        allowedOrigins: ["https://example.com"],
      },
      { signal: controller.signal },
    );
    return { driver, started };
  } catch (error) {
    await driver.shutdown();
    throw error;
  } finally {
    clearTimeout(timer);
  }
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
  const root = await realpath(
    await mkdtemp(join(tmpdir(), "hepta-worker-driver-")),
  );
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
    const launcher = new LinuxBubblewrapLauncher({
      bwrapPath: "/usr/bin/bwrap",
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
        argv[index] === "--ro-bind" &&
          argv[index + 1] === "/" &&
          argv[index + 2] === "/",
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
    assert.equal(
      mountedSources.some((path) => path.startsWith("/usr/bin")),
      false,
    );
    assert.equal(
      mountedSources.some((path) => path.startsWith("/usr/local")),
      false,
    );
    assert.equal(
      mountedSources.some(
        (path) => path === "/home" || path.startsWith("/home/"),
      ),
      false,
    );
    assert.equal(
      mountedSources.some(
        (path) => path === "/root" || path.startsWith("/root/"),
      ),
      false,
    );
    assert.equal(
      mountedSources.some((path) => path.startsWith("/var/lib")),
      false,
    );
    assert.equal(
      mountedSources.some((path) => path.startsWith("/var/run")),
      false,
    );
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

test("malformed worker observations close the channel without throwing from the stream handler", async () => {
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({
      payloadForResponse: (request, observation) => ({
        ok: true,
        observation: request.kind === "observe" ? null : observation,
      }),
    }),
  });
  const request = {
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
  };
  await assert.rejects(
    driver.observe(request),
    /worker observation must be an object/,
  );
  await assert.rejects(driver.observe(request), /channel is closed/);
});

test("private pipe errors reject pending requests and permanently close the channel", async () => {
  for (const streamName of ["stdin", "stdout", "stderr"]) {
    let child;
    const { driver, started } = await preparedDriver({
      launcher: fakeLauncher({
        onSpawn: (spawned) => {
          child = spawned;
        },
        holdKinds: ["observe"],
      }),
    });
    const request = {
      profileId: "profile.1",
      processId: started.processId,
      generation: 1,
    };
    const pending = driver.observe(request);
    child[streamName].emit("error", new Error("broken private pipe"));
    await assert.rejects(pending, /broken private pipe/);
    await assert.rejects(driver.observe(request), /channel is closed/);
  }
});

test("complete stdout EOF rejects pending requests instead of waiting for process exit", async () => {
  let child;
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({
      onSpawn: (spawned) => {
        child = spawned;
      },
      holdKinds: ["observe"],
    }),
  });
  const pending = driver.observe({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
  });
  child.stdout.end();
  await assert.rejects(pending, /response channel ended/);
});

test("stdout destruction rejects pending requests even when no end event arrives", async () => {
  let child;
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({
      onSpawn: (spawned) => {
        child = spawned;
      },
      holdKinds: ["observe"],
    }),
  });
  const pending = driver.observe({
    profileId: "profile.1",
    processId: started.processId,
    generation: 1,
  });
  child.stdout.destroy();
  await assert.rejects(pending, /response channel closed/);
});

test("unanswered dispatch responses cannot grow the pending request table without bound", async () => {
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({ holdDispatchResponse: {} }),
  });
  const request = {
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
  };
  for (let index = 0; index < 1024; index += 1) {
    await driver.dispatch({
      ...request,
      operationId: `operation.pending.${index}`,
    });
  }
  await assert.rejects(
    driver.dispatch({ ...request, operationId: "operation.pending.overflow" }),
    /pending-request capacity exhausted/,
  );
  // stop still tears down the worker through its cleanup path when its request
  // cannot be admitted, releasing every retained response promise.
  await assert.rejects(
    driver.stop(request),
    /pending-request capacity exhausted/,
  );
});

test("rejected duplicate requests do not consume outgoing protocol sequence numbers", async () => {
  const sequences = [];
  const held = {};
  const { driver, started } = await preparedDriver({
    launcher: fakeLauncher({
      holdDispatchResponse: held,
      onRequest: (request) => sequences.push(request.sequence),
    }),
  });
  const request = {
    profileId: "profile.1",
    processId: started.processId,
    profileGeneration: 1,
    operationId: "operation.duplicate",
  };
  await driver.dispatch(request);
  await assert.rejects(driver.dispatch(request), /identity is already live/);
  held.release();
  await driver.reconcile(request);
  assert.deepEqual(sequences, [1, 2, 3]);
});

test("concurrent starts cannot leak a second worker before artifact verification finishes", async () => {
  const root = await realpath(
    await mkdtemp(join(tmpdir(), "hepta-worker-start-")),
  );
  const workerPath = join(root, "worker.bin");
  const bytes = Buffer.from("qualified-worker");
  await writeFile(workerPath, bytes, { mode: 0o700 });
  let spawned = 0;
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(bytes),
    profileRoot: join(root, "profiles"),
    launcher: fakeLauncher({
      onSpawn: () => {
        spawned += 1;
      },
    }),
  });
  const request = { profileId: "profile.1", generation: 1 };
  const first = driver.start(request);
  await assert.rejects(
    driver.start({ profileId: "profile.2", generation: 1 }),
    /already started or starting/,
  );
  assert.equal((await first).started, true);
  assert.equal(spawned, 1);
  await driver.stop(request);
});

test(
  "a launcher spawn failure has its asynchronous child error handled before PID validation",
  { skip: process.platform !== "linux" },
  async () => {
    const root = await realpath(
      await mkdtemp(join(tmpdir(), "hepta-worker-spawn-error-")),
    );
    const workerPath = join(root, "worker.bin");
    const bytes = Buffer.from("qualified-worker");
    await writeFile(workerPath, bytes, { mode: 0o700 });
    const driver = new SubprocessBrowserDriver({
      workerPath,
      workerDigest: digest(bytes),
      profileRoot: join(root, "profiles"),
      launcher: new LinuxBubblewrapLauncher({
        bwrapPath: join(root, "missing-bwrap"),
      }),
    });
    await assert.rejects(
      driver.start({ profileId: "profile.1", generation: 1 }),
      /worker pid|ENOENT/,
    );
    await new Promise((resolve) => setImmediate(resolve));
    await assert.rejects(
      driver.observe({ profileId: "profile.1", generation: 1 }),
      /not started/,
    );
  },
);

test(
  "startup refuses a shared profile root before exposing a verified executable",
  { skip: process.platform === "win32" },
  async () => {
    const root = await realpath(
      await mkdtemp(join(tmpdir(), "hepta-worker-shared-root-")),
    );
    const workerPath = join(root, "worker.bin");
    const bytes = Buffer.from("qualified-worker");
    await writeFile(workerPath, bytes, { mode: 0o700 });
    const profileRoot = join(root, "profiles");
    await mkdir(profileRoot, { mode: 0o700 });
    await chmod(profileRoot, 0o777);
    let spawned = false;
    const driver = new SubprocessBrowserDriver({
      workerPath,
      workerDigest: digest(bytes),
      profileRoot,
      launcher: fakeLauncher({
        onSpawn: () => {
          spawned = true;
        },
      }),
    });
    await assert.rejects(
      driver.start({ profileId: "profile.1", generation: 1 }),
      /permissions or owner are unsafe/,
    );
    assert.equal(spawned, false);
  },
);

test(
  "startup refuses symlink roots and unsafe ancestor directories",
  { skip: process.platform === "win32" },
  async () => {
    const root = await realpath(
      await mkdtemp(join(tmpdir(), "hepta-worker-root-chain-")),
    );
    const workerPath = join(root, "worker.bin");
    const bytes = Buffer.from("qualified-worker");
    await writeFile(workerPath, bytes, { mode: 0o700 });
    const privateRoot = join(root, "private");
    await mkdir(privateRoot, { mode: 0o700 });
    const linkedRoot = join(root, "linked");
    await symlink(privateRoot, linkedRoot, "dir");
    const sharedParent = join(root, "shared");
    await mkdir(sharedParent, { mode: 0o700 });
    await chmod(sharedParent, 0o777);
    for (const profileRoot of [
      linkedRoot,
      join(linkedRoot, "nested"),
      join(sharedParent, "profiles"),
    ]) {
      const driver = new SubprocessBrowserDriver({
        workerPath,
        workerDigest: digest(bytes),
        profileRoot,
        launcher: fakeLauncher(),
      });
      await assert.rejects(
        driver.start({ profileId: "profile.1", generation: 1 }),
        /symlink|permissions or owner are unsafe/,
      );
    }
    await assert.rejects(lstat(join(privateRoot, "nested")), {
      code: "ENOENT",
    });
    await assert.rejects(lstat(join(sharedParent, "profiles")), {
      code: "ENOENT",
    });
  },
);

test("shutdown during artifact verification prevents late worker startup", async () => {
  const root = await realpath(
    await mkdtemp(join(tmpdir(), "hepta-worker-start-shutdown-")),
  );
  const workerPath = join(root, "worker.bin");
  const bytes = Buffer.from("qualified-worker");
  await writeFile(workerPath, bytes, { mode: 0o700 });
  let spawned = false;
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: digest(bytes),
    profileRoot: join(root, "profiles"),
    launcher: fakeLauncher({
      onSpawn: () => {
        spawned = true;
      },
    }),
  });
  const starting = driver.start({ profileId: "profile.1", generation: 1 });
  await driver.shutdown();
  await assert.rejects(starting, { name: "AbortError" });
  assert.equal(spawned, false);
});

test("fixture startup aborts and kills a worker that never acknowledges start", async () => {
  const kills = [];
  await assert.rejects(
    preparedDriver({
      startTimeoutMs: 20,
      launcher: fakeLauncher({
        holdKinds: ["start"],
        onSpawn: (child) => {
          child.kill = (signal) => {
            kills.push(signal);
            return true;
          };
        },
      }),
    }),
    { name: "AbortError" },
  );
  assert.equal(kills.includes("SIGKILL"), true);
});

test(
  "shutdown kills a real pipe-connected worker that remains alive after stdin EOF",
  { timeout: 10_000 },
  async (t) => {
    let child;
    t.after(() => child?.kill("SIGKILL"));
    const posture = fakeLauncher().posture;
    const protocolUrl = new URL("../src/worker-protocol.js", import.meta.url)
      .href;
    const workerSource = `
    const { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame } = await import(process.argv[1]);
    const decoder = new WorkerFrameDecoder();
    let sequence = 1;
    process.stdin.on("data", chunk => {
      for (const request of decoder.push(chunk)) {
        process.stdout.write(encodeWorkerFrame(buildWorkerFrame({
          sessionId: request.sessionId, generation: request.generation,
          sequence: sequence++, kind: "response", requestId: request.requestId,
          payload: { ok: true, observation: { started: true } },
        })));
      }
    });
    setInterval(() => {}, 1000);
  `;
    const { driver } = await preparedDriver({
      launcher: {
        posture,
        spawn() {
          child = spawn(
            process.execPath,
            ["--input-type=module", "-e", workerSource, protocolUrl],
            { stdio: ["pipe", "pipe", "pipe"], env: {} },
          );
          return child;
        },
      },
    });
    let timer;
    const exited = Promise.race([
      once(child, "exit"),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("worker remained alive after shutdown")),
          2_000,
        );
      }),
    ]);
    try {
      await driver.shutdown();
      const [, signal] = await exited;
      assert.equal(signal, "SIGKILL");
      await driver.shutdown();
    } finally {
      clearTimeout(timer);
      child.kill("SIGKILL");
    }
  },
);
