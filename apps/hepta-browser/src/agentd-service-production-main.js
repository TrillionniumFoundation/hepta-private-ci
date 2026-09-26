#!/usr/bin/env node

import { constants } from "node:fs";
import { open, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve } from "node:path";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "./agentd-service.js";
import { FileBrowserOperationJournal } from "./journal.js";
import { createFilePersistedEffectReconciler } from "./persisted-reconciler.js";
import { LinuxProductionLauncher } from "./production-launcher.js";
import { BrowserProfileHost } from "./runtime.js";
import { PooledSubprocessBrowserDriver } from "./worker-driver.js";

const MAX_POLICY_BYTES = 65_536;
const POLICY_SCHEMA = "hepta.browser.linux-isolation-policy.v1";
const POLICY_KEYS = [
  "cgroupCpuPeriodMicros",
  "cgroupCpuQuotaMicros",
  "cgroupMemoryMaxBytes",
  "cgroupPidsMax",
  "cgroupRoot",
  "schema",
  "seccompProfilePath",
  "seccompProfileSha256",
];

function required(name) {
  const value = process.env[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${name} is required`);
  }
  return value;
}

function requiredAbsolutePath(name) {
  const value = required(name);
  if (!isAbsolute(value)) throw new TypeError(`${name} must be absolute`);
  return resolve(value);
}

function requiredDigest(name) {
  const value = required(name);
  if (!/^[0-9a-f]{64}$/.test(value) || /^0+$/.test(value)) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function optionalPositiveInteger(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function requiredPositiveInteger(name) {
  const value = Number(required(name));
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function exactKeys(record, expected, name) {
  const keys = Object.keys(record).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function absolutePath(value, name) {
  if (typeof value !== "string" || !isAbsolute(value)) {
    throw new TypeError(`${name} must be an absolute path`);
  }
  return resolve(value);
}

async function readIsolationPolicy(profileRoot) {
  const policyPath = join(dirname(profileRoot), "isolation-policy.json");
  const canonicalParent = await realpath(dirname(policyPath));
  if (canonicalParent !== dirname(policyPath)) {
    throw new TypeError("Browser isolation policy parent contains a symlink");
  }
  const parentInfo = await stat(canonicalParent);
  if (!parentInfo.isDirectory()) {
    throw new TypeError("Browser isolation policy parent must be a directory");
  }
  if (process.platform !== "win32" && (parentInfo.mode & 0o077) !== 0) {
    throw new TypeError("Browser isolation policy parent permissions are too broad");
  }

  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(policyPath, constants.O_RDONLY | noFollow);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size < 1 || info.size > MAX_POLICY_BYTES) {
      throw new TypeError("Browser isolation policy must be a bounded regular file");
    }
    if (process.platform !== "win32" && (info.mode & 0o077) !== 0) {
      throw new TypeError("Browser isolation policy permissions are too broad");
    }
    const raw = await handle.readFile({ encoding: "utf8" });
    const policy = JSON.parse(raw);
    if (policy === null || typeof policy !== "object" || Array.isArray(policy)) {
      throw new TypeError("Browser isolation policy must be an object");
    }
    exactKeys(policy, POLICY_KEYS, "Browser isolation policy");
    if (policy.schema !== POLICY_SCHEMA) {
      throw new TypeError("Browser isolation policy schema is unsupported");
    }
    if (
      typeof policy.seccompProfileSha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(policy.seccompProfileSha256) ||
      /^0+$/.test(policy.seccompProfileSha256)
    ) {
      throw new TypeError("seccompProfileSha256 must be a non-zero digest");
    }
    return Object.freeze({
      cgroupRoot: absolutePath(policy.cgroupRoot, "cgroupRoot"),
      seccompProfilePath: absolutePath(
        policy.seccompProfilePath,
        "seccompProfilePath",
      ),
      seccompProfileDigest: policy.seccompProfileSha256,
      cgroupMemoryMaxBytes: positiveInteger(
        policy.cgroupMemoryMaxBytes,
        "cgroupMemoryMaxBytes",
      ),
      cgroupPidsMax: positiveInteger(policy.cgroupPidsMax, "cgroupPidsMax"),
      cgroupCpuQuotaMicros: positiveInteger(
        policy.cgroupCpuQuotaMicros,
        "cgroupCpuQuotaMicros",
      ),
      cgroupCpuPeriodMicros: positiveInteger(
        policy.cgroupCpuPeriodMicros,
        "cgroupCpuPeriodMicros",
      ),
    });
  } finally {
    await handle.close();
  }
}

if (process.platform !== "linux") {
  throw new TypeError("production Agentd Browser service requires Linux");
}

const profileRoot = requiredAbsolutePath("HEPTA_BROWSER_PROFILE_ROOT");
const policy = await readIsolationPolicy(profileRoot);
const channel = new AgentdBrowserChannel({ input: process.stdin, output: process.stdout });
const authority = new ParentFinalUseAuthority(channel);
const maxProfiles = optionalPositiveInteger("HEPTA_BROWSER_MAX_PROFILES", 16);
const reconciliationRoot = process.env.HEPTA_BROWSER_RECONCILIATION_ROOT;
const driver = new PooledSubprocessBrowserDriver({
  workerPath: requiredAbsolutePath("HEPTA_BROWSER_WORKER_PATH"),
  workerDigest: requiredDigest("HEPTA_BROWSER_WORKER_SHA256"),
  profileRoot,
  maxProfiles,
  persistedReconciler:
    reconciliationRoot === undefined
      ? null
      : createFilePersistedEffectReconciler(
          requiredAbsolutePath("HEPTA_BROWSER_RECONCILIATION_ROOT"),
          {
            observerId: required("HEPTA_BROWSER_RECONCILIATION_OBSERVER_ID"),
            verifyingKeyHex: requiredDigest(
              "HEPTA_BROWSER_RECONCILIATION_VERIFYING_KEY",
            ),
            minimumObserverGeneration: requiredPositiveInteger(
              "HEPTA_BROWSER_RECONCILIATION_MIN_OBSERVER_GENERATION",
            ),
            minimumObservedAtUnixMs: requiredPositiveInteger(
              "HEPTA_BROWSER_RECONCILIATION_MIN_OBSERVED_AT_UNIX_MS",
            ),
            currentFrontierDigest: requiredDigest(
              "HEPTA_BROWSER_RECONCILIATION_CURRENT_FRONTIER_DIGEST",
            ),
            maxFutureSkewMs: optionalPositiveInteger(
              "HEPTA_BROWSER_RECONCILIATION_MAX_FUTURE_SKEW_MS",
              60_000,
            ),
          },
        ),
  launcher: new LinuxProductionLauncher({
    bwrapPath: process.env.HEPTA_BROWSER_BWRAP_PATH ?? "/usr/bin/bwrap",
    bwrapDigest: requiredDigest("HEPTA_BROWSER_BWRAP_SHA256"),
    prlimitPath: process.env.HEPTA_BROWSER_PRLIMIT_PATH ?? "/usr/bin/prlimit",
    prlimitDigest: requiredDigest("HEPTA_BROWSER_PRLIMIT_SHA256"),
    maxAddressSpaceBytes: optionalPositiveInteger(
      "HEPTA_BROWSER_MAX_ADDRESS_SPACE_BYTES",
      8 * 1024 * 1024 * 1024,
    ),
    maxCpuSeconds: optionalPositiveInteger("HEPTA_BROWSER_MAX_CPU_SECONDS", 300),
    maxOpenFiles: optionalPositiveInteger("HEPTA_BROWSER_MAX_OPEN_FILES", 4096),
    maxProcesses: optionalPositiveInteger("HEPTA_BROWSER_MAX_PROCESSES", 256),
    ...policy,
  }),
});
const journal = new FileBrowserOperationJournal(
  requiredAbsolutePath("HEPTA_BROWSER_JOURNAL_PATH"),
);
const host = new BrowserProfileHost({
  driver,
  authority,
  journal,
  driverCallTimeoutMs: optionalPositiveInteger(
    "HEPTA_BROWSER_DRIVER_TIMEOUT_MS",
    30_000,
  ),
  maxActiveProfiles: maxProfiles,
});
const service = new BrowserAgentdService({ host, channel, authority });

try {
  await service.run();
} catch (error) {
  process.stderr.write(
    `hepta-browser production service failed: ${String(error?.message ?? error)}\n`,
  );
  process.exitCode = 1;
}
