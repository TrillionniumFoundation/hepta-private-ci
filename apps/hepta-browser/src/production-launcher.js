import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  realpathSync,
  rmdirSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

import { LinuxBubblewrapLauncher } from "./worker-driver.js";

const DIGEST = /^[0-9a-f]{64}$/;
const MAX_SECCOMP_PROFILE_BYTES = 1024 * 1024;
const DEFAULT_CGROUP_MEMORY_MAX_BYTES = 8 * 1024 * 1024 * 1024;
const DEFAULT_CGROUP_PIDS_MAX = 256;
const DEFAULT_CGROUP_CPU_QUOTA_MICROS = 200_000;
const DEFAULT_CGROUP_CPU_PERIOD_MICROS = 100_000;

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function expectedDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function verifyRegularNoFollow(path, expected, maximum, name) {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const fd = openSync(path, constants.O_RDONLY | noFollow);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.size < 1 || info.size > maximum) {
      throw new TypeError(`${name} must be a bounded regular file`);
    }
    const bytes = Buffer.allocUnsafe(info.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (count === 0) throw new TypeError(`${name} ended before its declared size`);
      offset += count;
    }
    if (sha256(bytes) !== expected) {
      throw new TypeError(`${name} digest mismatch`);
    }
    return fd;
  } catch (error) {
    closeSync(fd);
    throw error;
  }
}

function canonicalDirectory(path, name) {
  if (!isAbsolute(path)) throw new TypeError(`${name} must be absolute`);
  const resolved = resolve(path);
  const info = lstatSync(resolved);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new TypeError(`${name} must be a non-symlink directory`);
  }
  if (realpathSync(resolved) !== resolved) {
    throw new TypeError(`${name} contains a symlink`);
  }
  return resolved;
}

function safeRemoveCgroup(path) {
  try {
    rmdirSync(path);
  } catch (error) {
    if (error?.code !== "ENOENT" && error?.code !== "ENOTEMPTY" && error?.code !== "EBUSY") {
      throw error;
    }
  }
}

/**
 * Exact-host production launcher layered over the canonical Bubblewrap/prlimit
 * source contract. The selected host must delegate one writable cgroup-v2
 * subtree and provide a reviewed classic-BPF seccomp profile.
 */
export class LinuxProductionLauncher {
  constructor({
    seccompProfilePath,
    seccompProfileDigest,
    cgroupRoot,
    cgroupMemoryMaxBytes = DEFAULT_CGROUP_MEMORY_MAX_BYTES,
    cgroupPidsMax = DEFAULT_CGROUP_PIDS_MAX,
    cgroupCpuQuotaMicros = DEFAULT_CGROUP_CPU_QUOTA_MICROS,
    cgroupCpuPeriodMicros = DEFAULT_CGROUP_CPU_PERIOD_MICROS,
    ...bubblewrapOptions
  }) {
    if (process.platform !== "linux") {
      throw new TypeError("LinuxProductionLauncher requires Linux");
    }
    if (!isAbsolute(seccompProfilePath)) {
      throw new TypeError("seccompProfilePath must be absolute");
    }
    this.seccompProfilePath = resolve(seccompProfilePath);
    this.seccompProfileDigest = expectedDigest(
      seccompProfileDigest,
      "seccompProfileDigest",
    );
    this.cgroupRoot = canonicalDirectory(cgroupRoot, "cgroupRoot");
    this.cgroupLimits = Object.freeze({
      memoryMaxBytes: positiveInteger(
        cgroupMemoryMaxBytes,
        "cgroupMemoryMaxBytes",
      ),
      pidsMax: positiveInteger(cgroupPidsMax, "cgroupPidsMax"),
      cpuQuotaMicros: positiveInteger(
        cgroupCpuQuotaMicros,
        "cgroupCpuQuotaMicros",
      ),
      cpuPeriodMicros: positiveInteger(
        cgroupCpuPeriodMicros,
        "cgroupCpuPeriodMicros",
      ),
    });
    if (this.cgroupLimits.cpuQuotaMicros > this.cgroupLimits.cpuPeriodMicros * 64) {
      throw new TypeError("cgroup CPU quota exceeds the 64-core hard bound");
    }

    this.base = new LinuxBubblewrapLauncher(bubblewrapOptions);
    this.bwrapPath = this.base.bwrapPath;
    this.prlimitPath = this.base.prlimitPath;
    this.resourceLimits = this.base.resourceLimits;
    this.posture = Object.freeze({
      ...this.base.posture,
      seccompFilterConfigured: true,
      cgroupV2Configured: true,
      cgroupMemoryBounded: true,
      cgroupPidsBounded: true,
      cgroupCpuBounded: true,
    });
  }

  async verify() {
    await this.base.verify();
    const controllers = join(this.cgroupRoot, "cgroup.controllers");
    const info = lstatSync(controllers);
    if (!info.isFile() || info.isSymbolicLink()) {
      throw new TypeError("cgroupRoot is not a cgroup-v2 delegated subtree");
    }
    const fd = verifyRegularNoFollow(
      this.seccompProfilePath,
      this.seccompProfileDigest,
      MAX_SECCOMP_PROFILE_BYTES,
      "Browser seccomp profile",
    );
    closeSync(fd);
  }

  argv({ workerPath, profileDir }) {
    return [
      "--seccomp",
      "3",
      ...this.base.argv({ workerPath, profileDir }),
    ];
  }

  spawnSpec({ workerPath, profileDir }) {
    const limits = this.resourceLimits;
    return Object.freeze({
      command: this.prlimitPath,
      args: Object.freeze([
        `--as=${limits.maxAddressSpaceBytes}:${limits.maxAddressSpaceBytes}`,
        `--cpu=${limits.maxCpuSeconds}:${limits.maxCpuSeconds}`,
        `--nofile=${limits.maxOpenFiles}:${limits.maxOpenFiles}`,
        `--nproc=${limits.maxProcesses}:${limits.maxProcesses}`,
        "--",
        this.bwrapPath,
        ...this.argv({ workerPath, profileDir }),
      ]),
    });
  }

  spawn({ workerPath, profileDir }) {
    const cgroupPath = join(
      this.cgroupRoot,
      `hepta-browser-${process.pid}-${randomUUID()}`,
    );
    mkdirSync(cgroupPath, { mode: 0o700 });
    try {
      writeFileSync(
        join(cgroupPath, "memory.max"),
        `${this.cgroupLimits.memoryMaxBytes}\n`,
      );
      writeFileSync(join(cgroupPath, "memory.oom.group"), "1\n");
      writeFileSync(join(cgroupPath, "pids.max"), `${this.cgroupLimits.pidsMax}\n`);
      writeFileSync(
        join(cgroupPath, "cpu.max"),
        `${this.cgroupLimits.cpuQuotaMicros} ${this.cgroupLimits.cpuPeriodMicros}\n`,
      );

      const seccompFd = verifyRegularNoFollow(
        this.seccompProfilePath,
        this.seccompProfileDigest,
        MAX_SECCOMP_PROFILE_BYTES,
        "Browser seccomp profile",
      );
      let child;
      try {
        const spec = this.spawnSpec({ workerPath, profileDir });
        child = spawn(spec.command, [...spec.args], {
          stdio: ["pipe", "pipe", "pipe", seccompFd],
          env: {},
          shell: false,
          windowsHide: true,
        });
      } finally {
        closeSync(seccompFd);
      }
      if (!Number.isSafeInteger(child.pid) || child.pid < 1) {
        child.kill?.("SIGKILL");
        throw new TypeError("production launcher did not return a process identity");
      }
      writeFileSync(join(cgroupPath, "cgroup.procs"), `${child.pid}\n`);
      child.once("exit", () => safeRemoveCgroup(cgroupPath));
      child.once("error", () => safeRemoveCgroup(cgroupPath));
      return child;
    } catch (error) {
      safeRemoveCgroup(cgroupPath);
      throw error;
    }
  }
}

export function seccompProfileDigest(path) {
  return sha256(readFileSync(path));
}
