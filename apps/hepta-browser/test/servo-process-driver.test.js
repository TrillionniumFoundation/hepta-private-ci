import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createHash } from "node:crypto";

import { LinuxBubblewrapSandbox } from "../src/servo-process-driver.js";

async function fixtureFile(dir, name, content) {
  const path = join(dir, name);
  await writeFile(path, content, { mode: 0o700 });
  return {
    path,
    digest: createHash("sha256").update(content).digest("hex"),
  };
}

test("Linux bubblewrap launch denies external network and exposes only inherited fd 3", async (t) => {
  if (process.platform !== "linux") {
    t.skip("Linux-only sandbox contract");
    return;
  }
  const dir = await mkdtemp(join(tmpdir(), "hepta-servo-sandbox-"));
  const bwrap = await fixtureFile(dir, "bwrap", "fake-bwrap");
  const worker = await fixtureFile(dir, "worker", "fake-worker");
  const profileRoot = join(dir, "profiles");
  const { mkdir } = await import("node:fs/promises");
  await mkdir(profileRoot, { mode: 0o700 });
  const sandbox = new LinuxBubblewrapSandbox({
    bwrapPath: bwrap.path,
    bwrapDigest: bwrap.digest,
    workerPath: worker.path,
    workerDigest: worker.digest,
    profileRoot,
  });
  const spec = await sandbox.prepare({ profileId: "profile.1", generation: 1 });
  assert.equal(spec.args.includes("--unshare-net"), true);
  assert.equal(spec.args.includes("--die-with-parent"), true);
  assert.equal(spec.args.includes("--clearenv"), true);
  assert.equal(spec.args.at(-2), "--control-fd");
  assert.equal(spec.args.at(-1), "3");
  assert.equal(spec.isolation.networkPolicyEnforced, true);
  assert.equal(spec.isolation.profileIsolationEnforced, true);
  assert.match(spec.isolation.sandboxDigest, /^[0-9a-f]{64}$/);
});
