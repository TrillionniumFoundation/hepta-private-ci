import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { LinuxProductionLauncher } from "../src/production-launcher.js";

function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function waitForExit(child) {
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-production-launcher-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const cgroupRoot = join(root, "cgroup");
  const profileDir = join(root, "profile");
  await mkdir(cgroupRoot, { mode: 0o700 });
  await mkdir(profileDir, { mode: 0o700 });
  await writeFile(join(cgroupRoot, "cgroup.controllers"), "cpu memory pids\n");

  const bwrapPath = join(root, "bwrap");
  const prlimitPath = join(root, "prlimit");
  const workerPath = join(root, "worker");
  const seccompProfilePath = join(root, "seccomp.bpf");
  const bwrapBytes = Buffer.from("fake-bwrap\n");
  const prlimitBytes = Buffer.from("#!/bin/sh\nsleep 5\n");
  const workerBytes = Buffer.from("fake-worker\n");
  const seccompBytes = Buffer.from("reviewed-classic-bpf-filter\n");
  await writeFile(bwrapPath, bwrapBytes, { mode: 0o500 });
  await writeFile(prlimitPath, prlimitBytes, { mode: 0o500 });
  await writeFile(workerPath, workerBytes, { mode: 0o500 });
  await writeFile(seccompProfilePath, seccompBytes, { mode: 0o400 });
  await chmod(prlimitPath, 0o500);

  const launcher = new LinuxProductionLauncher({
    bwrapPath,
    bwrapDigest: digest(bwrapBytes),
    prlimitPath,
    prlimitDigest: digest(prlimitBytes),
    seccompProfilePath,
    seccompProfileDigest: digest(seccompBytes),
    cgroupRoot,
    cgroupMemoryMaxBytes: 1024 * 1024 * 1024,
    cgroupPidsMax: 64,
    cgroupCpuQuotaMicros: 100_000,
    cgroupCpuPeriodMicros: 100_000,
  });
  return { launcher, cgroupRoot, profileDir, workerPath };
}

test(
  "production launcher binds reviewed seccomp and exact cgroup-v2 ceilings",
  { skip: process.platform !== "linux" },
  async (t) => {
    const { launcher, cgroupRoot, profileDir, workerPath } = await fixture(t);
    await launcher.verify();
    assert.equal(launcher.posture.seccompFilterConfigured, true);
    assert.equal(launcher.posture.cgroupV2Configured, true);
    assert.deepEqual(launcher.argv({ workerPath, profileDir }).slice(0, 2), [
      "--seccomp",
      "3",
    ]);

    const child = launcher.spawn({ workerPath, profileDir });
    const directories = (await readdir(cgroupRoot)).filter((name) =>
      name.startsWith("hepta-browser-"),
    );
    assert.equal(directories.length, 1);
    const cgroup = join(cgroupRoot, directories[0]);
    assert.equal(await readFile(join(cgroup, "memory.max"), "utf8"), "1073741824\n");
    assert.equal(await readFile(join(cgroup, "memory.oom.group"), "utf8"), "1\n");
    assert.equal(await readFile(join(cgroup, "pids.max"), "utf8"), "64\n");
    assert.equal(await readFile(join(cgroup, "cpu.max"), "utf8"), "100000 100000\n");
    assert.equal(await readFile(join(cgroup, "cgroup.procs"), "utf8"), `${child.pid}\n`);

    child.kill("SIGTERM");
    await waitForExit(child);
  },
);

test(
  "production launcher rejects digest drift before process creation",
  { skip: process.platform !== "linux" },
  async (t) => {
    const { launcher } = await fixture(t);
    launcher.seccompProfileDigest = "f".repeat(64);
    await assert.rejects(launcher.verify(), /seccomp profile digest mismatch/);
  },
);
