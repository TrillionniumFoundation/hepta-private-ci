#!/usr/bin/env node

import { isAbsolute } from "node:path";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "./agentd-service.js";
import { FileBrowserOperationJournal } from "./journal.js";
import { BrowserProfileHost } from "./runtime.js";
import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
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

if (process.platform !== "linux") {
  throw new TypeError("current Agentd Browser service requires the qualified Linux launcher");
}

const channel = new AgentdBrowserChannel({ input: process.stdin, output: process.stdout });
const authority = new ParentFinalUseAuthority(channel);
const driver = new SubprocessBrowserDriver({
  workerPath: requiredAbsolutePath("HEPTA_BROWSER_WORKER_PATH"),
  workerDigest: requiredDigest("HEPTA_BROWSER_WORKER_SHA256"),
  profileRoot: requiredAbsolutePath("HEPTA_BROWSER_PROFILE_ROOT"),
  launcher: new LinuxBubblewrapLauncher({
    bwrapPath: process.env.HEPTA_BROWSER_BWRAP_PATH ?? "/usr/bin/bwrap",
  }),
});
const journal = new FileBrowserOperationJournal(
  requiredAbsolutePath("HEPTA_BROWSER_JOURNAL_PATH"),
);
const host = new BrowserProfileHost({
  driver,
  authority,
  journal,
  driverCallTimeoutMs: optionalPositiveInteger("HEPTA_BROWSER_DRIVER_TIMEOUT_MS", 30_000),
});
const service = new BrowserAgentdService({ host, channel, authority });

try {
  await service.run();
} catch (error) {
  process.stderr.write(`hepta-browser Agentd service failed: ${String(error?.message ?? error)}\n`);
  process.exitCode = 1;
}
