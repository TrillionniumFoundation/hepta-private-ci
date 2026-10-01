#!/usr/bin/env node

import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2])
  throw new Error("usage: real-worker-smoke.js WORKER_BINARY");
const bytes = await readFile(workerPath);
const workerDigest = createHash("sha256").update(bytes).digest("hex");
const root = await mkdtemp(join(tmpdir(), "hepta-servo-worker-smoke-"));
const driver = new SubprocessBrowserDriver({
  workerPath,
  workerDigest,
  profileRoot: join(root, "profiles"),
  launcher: new LinuxBubblewrapLauncher({ bwrapPath: "/usr/bin/bwrap" }),
});
const digest = "1".repeat(64);
let processId = null;

try {
  const started = await driver.start(
    {
      profileId: "profile.smoke",
      principalId: "principal.smoke",
      manifestDigest: digest,
      grantDigest: digest,
      generation: 1,
      allowedOrigins: [],
    },
    { signal: AbortSignal.timeout(30_000) },
  );
  processId = started.processId;
  if (
    typeof started.processId !== "string" ||
    !started.processId.startsWith("servo.pid.")
  ) {
    throw new Error("worker did not return a process identity");
  }
  const stopped = await driver.stop(
    {
      profileId: "profile.smoke",
      processId: started.processId,
      generation: 1,
    },
    { signal: AbortSignal.timeout(10_000) },
  );
  processId = null;
  if (stopped.stopped !== true)
    throw new Error("worker did not stop terminally");
  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.real-worker-smoke.v1",
      workerSha256: workerDigest,
      currentPinWorkerBooted: true,
      privateProtocolRoundTrip: true,
      sandboxedStartStop: true,
    }) + "\n",
  );
} finally {
  if (processId !== null) {
    await driver
      .stop(
        { profileId: "profile.smoke", processId, generation: 1 },
        { signal: AbortSignal.timeout(10_000) },
      )
      .catch(() => {});
  }
  await rm(root, { recursive: true, force: true });
}
