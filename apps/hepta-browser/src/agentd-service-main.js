#!/usr/bin/env node

import { isAbsolute } from "node:path";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "./agentd-service.js";
import { AdmissionBoundBrowserDriver } from "./effect-admission.js";
import { FileBrowserOperationJournal } from "./journal.js";
import { OwnedMonotonicBrowserOperationJournal } from "./journal-owner.js";
import { BrowserProfileHost } from "./runtime.js";
import { createFilePersistedEffectReconciler } from "./persisted-reconciler.js";
import {
  LinuxBubblewrapLauncher,
  PooledSubprocessBrowserDriver,
} from "./worker-driver.js";

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
  return value;
}

function requiredDigest(name) {
  const value = required(name);
  if (!/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
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

if (process.platform !== "linux") {
  throw new TypeError("current Agentd Browser service requires the qualified Linux launcher");
}

const channel = new AgentdBrowserChannel({ input: process.stdin, output: process.stdout });
const authority = new ParentFinalUseAuthority(channel);
const maxProfiles = optionalPositiveInteger("HEPTA_BROWSER_MAX_PROFILES", 16);
const reconciliationRoot = process.env.HEPTA_BROWSER_RECONCILIATION_ROOT;
const driver = new AdmissionBoundBrowserDriver({
  driver: new PooledSubprocessBrowserDriver({
    workerPath: requiredAbsolutePath("HEPTA_BROWSER_WORKER_PATH"),
    workerDigest: requiredDigest("HEPTA_BROWSER_WORKER_SHA256"),
    profileRoot: requiredAbsolutePath("HEPTA_BROWSER_PROFILE_ROOT"),
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
    launcher: new LinuxBubblewrapLauncher({
      bwrapPath: process.env.HEPTA_BROWSER_BWRAP_PATH ?? "/usr/bin/bwrap",
      bwrapDigest: requiredDigest("HEPTA_BROWSER_BWRAP_SHA256"),
      prlimitPath: process.env.HEPTA_BROWSER_PRLIMIT_PATH ?? "/usr/bin/prlimit",
      prlimitDigest: requiredDigest("HEPTA_BROWSER_PRLIMIT_SHA256"),
      maxAddressSpaceBytes: optionalPositiveInteger(
        "HEPTA_BROWSER_MAX_ADDRESS_SPACE_BYTES",
        8 * 1024 * 1024 * 1024,
      ),
      maxCpuSeconds: optionalPositiveInteger(
        "HEPTA_BROWSER_MAX_CPU_SECONDS",
        300,
      ),
      maxOpenFiles: optionalPositiveInteger(
        "HEPTA_BROWSER_MAX_OPEN_FILES",
        4096,
      ),
      maxProcesses: optionalPositiveInteger("HEPTA_BROWSER_MAX_PROCESSES", 256),
    }),
  }),
});
const journalPath = requiredAbsolutePath("HEPTA_BROWSER_JOURNAL_PATH");
const journal = new OwnedMonotonicBrowserOperationJournal({
  journal: new FileBrowserOperationJournal(journalPath),
  lockPath:
    process.env.HEPTA_BROWSER_JOURNAL_OWNER_PATH === undefined
      ? `${journalPath}.owner.lock`
      : requiredAbsolutePath("HEPTA_BROWSER_JOURNAL_OWNER_PATH"),
});
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

let serviceFailed = false;
try {
  // Acquire the cross-process single-writer fence before accepting any parent
  // frame. Lazy acquisition remains in every journal method as a defense in
  // depth, but the product service must fail before serving when ownership is
  // unavailable.
  await journal.acquire();
  await service.run();
} catch (error) {
  serviceFailed = true;
  process.stderr.write(
    `hepta-browser Agentd service failed: ${String(error?.message ?? error)}\n`,
  );
  process.exitCode = 1;
} finally {
  try {
    await journal.close();
  } catch (error) {
    if (!serviceFailed) {
      process.stderr.write(
        `hepta-browser journal owner release failed: ${String(error?.message ?? error)}\n`,
      );
      process.exitCode = 1;
    }
  }
}
