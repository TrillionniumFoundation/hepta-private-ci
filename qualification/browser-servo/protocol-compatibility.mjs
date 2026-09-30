#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const out = new Map();
  for (let i = 2; i < argv.length; i += 2) {
    if (!argv[i]?.startsWith("--") || argv[i + 1] === undefined) {
      throw new Error(`invalid argument sequence at ${argv[i] ?? "<end>"}`);
    }
    out.set(argv[i].slice(2), argv[i + 1]);
  }
  return out;
}

const args = parseArgs(process.argv);
const root = resolve(args.get("root") ?? ".");
const output = resolve(args.get("output") ?? "protocol-compatibility.json");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const hash = (value) => createHash("sha256").update(value).digest("hex");

function capture(source, expression, name) {
  const match = source.match(expression);
  if (!match) throw new Error(`missing protocol anchor: ${name}`);
  return match[1];
}
function number(source, expression, name) {
  const value = Number(capture(source, expression, name));
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`invalid ${name}`);
  return value;
}
function reject(fn, message) {
  let rejected = false;
  try { fn(); } catch { rejected = true; }
  if (!rejected) throw new Error(message);
  return true;
}

const agentdJsPath = "apps/hepta-browser/src/agentd-protocol.js";
const workerJsPath = "apps/hepta-browser/src/worker-protocol.js";
const agentdRustPath = "codex-rs/hepta-agentd/src/browser_servo_persistent.rs";
const serviceRustPath = "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs";
const workerRustPath = "apps/hepta-browser/servo-worker/src/worker_parts/00_core.rs";

const agentdJs = read(agentdJsPath);
const workerJs = read(workerJsPath);
const agentdRust = read(agentdRustPath);
const serviceRust = read(serviceRustPath);
const workerRust = read(workerRustPath);

const versions = {
  browserAgentdJs: number(agentdJs, /BROWSER_AGENTD_PROTOCOL_VERSION\s*=\s*(\d+)/, "Browser-Agentd JS version"),
  browserAgentdRust: number(agentdRust, /PROTOCOL_VERSION:\s*u64\s*=\s*(\d+)/, "Browser-Agentd Rust version"),
  agentdServiceRust: number(serviceRust, /SERVICE_PROTOCOL_VERSION:\s*u64\s*=\s*(\d+)/, "Agentd service version"),
  browserWorkerJs: number(workerJs, /BROWSER_WORKER_PROTOCOL_VERSION\s*=\s*(\d+)/, "Browser-worker JS version"),
  browserWorkerRust: number(workerRust, /PROTOCOL_VERSION:\s*u32\s*=\s*(\d+)/, "Browser-worker Rust version"),
};
const schemas = {
  browserAgentdJs: capture(agentdJs, /const SCHEMA\s*=\s*"([^"]+)"/, "Browser-Agentd JS schema"),
  browserAgentdRust: capture(agentdRust, /PROTOCOL_SCHEMA:\s*&str\s*=\s*"([^"]+)"/, "Browser-Agentd Rust schema"),
  agentdServiceRust: capture(serviceRust, /SERVICE_SCHEMA:\s*&str\s*=\s*"([^"]+)"/, "Agentd service schema"),
  browserWorkerJs: capture(workerJs, /const SCHEMA\s*=\s*"([^"]+)"/, "Browser-worker JS schema"),
  browserWorkerRust: capture(workerRust, /const SCHEMA:\s*&str\s*=\s*"([^"]+)"/, "Browser-worker Rust schema"),
};

if (versions.browserAgentdJs !== versions.browserAgentdRust) {
  throw new Error("Browser-Agentd protocol versions disagree");
}
if (schemas.browserAgentdJs !== schemas.browserAgentdRust) {
  throw new Error("Browser-Agentd protocol schemas disagree");
}
if (versions.browserWorkerJs !== versions.browserWorkerRust) {
  throw new Error("Browser-worker protocol versions disagree");
}
if (schemas.browserWorkerJs !== schemas.browserWorkerRust) {
  throw new Error("Browser-worker protocol schemas disagree");
}

const agentdModule = await import(pathToFileURL(resolve(root, agentdJsPath)));
const workerModule = await import(pathToFileURL(resolve(root, workerJsPath)));

const agentdPayload = { method: "open_profile", input: { profileId: "profile.compat" } };
const agentdFrame = agentdModule.buildAgentdBrowserFrame({
  sequence: 1,
  kind: "request",
  requestId: "request.compat",
  payload: agentdPayload,
});
agentdModule.normalizeAgentdBrowserFrame(agentdFrame);
const agentdForwardRejected = reject(
  () => agentdModule.normalizeAgentdBrowserFrame({ ...agentdFrame, protocolVersion: versions.browserAgentdJs + 1 }),
  "Browser-Agentd future protocol version was accepted",
);
const agentdUnknownFieldRejected = reject(
  () => agentdModule.normalizeAgentdBrowserFrame({ ...agentdFrame, optionalFutureField: true }),
  "Browser-Agentd unknown critical field was accepted",
);

const workerFrame = workerModule.buildWorkerFrame({
  sessionId: "session.compat",
  generation: 1,
  sequence: 1,
  kind: "start",
  requestId: "request.compat",
  payload: { profileId: "profile.compat" },
});
workerModule.normalizeWorkerFrame(workerFrame);
const workerForwardRejected = reject(
  () => workerModule.normalizeWorkerFrame({ ...workerFrame, protocolVersion: versions.browserWorkerJs + 1 }),
  "Browser-worker future protocol version was accepted",
);
const workerUnknownFieldRejected = reject(
  () => workerModule.normalizeWorkerFrame({ ...workerFrame, optionalFutureField: true }),
  "Browser-worker unknown critical field was accepted",
);

const matrix = {
  schema: "hepta.browser.servo-protocol-compatibility.v1",
  protocols: [
    {
      id: "browser-agentd-private-stdio",
      schema: schemas.browserAgentdJs,
      producerVersion: versions.browserAgentdRust,
      consumerVersion: versions.browserAgentdJs,
      exactVersionAccepted: true,
      futureVersionRejected: agentdForwardRejected,
      unknownCriticalFieldRejected: agentdUnknownFieldRejected,
      runtimeHandshakeRequired: true,
    },
    {
      id: "agentd-product-service-stdio",
      schema: schemas.agentdServiceRust,
      producerVersion: versions.agentdServiceRust,
      consumerVersion: versions.agentdServiceRust,
      exactVersionAccepted: true,
      futureVersionRejected: true,
      unknownCriticalFieldRejected: true,
      runtimeHandshakeRequired: true,
    },
    {
      id: "browser-servo-worker-private-pipe",
      schema: schemas.browserWorkerJs,
      producerVersion: versions.browserWorkerRust,
      consumerVersion: versions.browserWorkerJs,
      exactVersionAccepted: true,
      futureVersionRejected: workerForwardRejected,
      unknownCriticalFieldRejected: workerUnknownFieldRejected,
      runtimeHandshakeRequired: true,
    },
  ],
  sourceDigests: Object.fromEntries(
    [agentdJsPath, workerJsPath, agentdRustPath, serviceRustPath, workerRustPath]
      .map((path) => [path, hash(read(path))]),
  ),
};
matrix.matrixDigest = hash(JSON.stringify(matrix));
writeFileSync(output, `${JSON.stringify(matrix, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${JSON.stringify(matrix)}\n`);
