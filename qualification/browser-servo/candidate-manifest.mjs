#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function parseArgs(argv) {
  const out = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument sequence at ${key ?? "<end>"}`);
    }
    out.set(key.slice(2), value);
  }
  return out;
}

const args = parseArgs(process.argv);
const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const root = realpathSync(resolve(args.get("root") ?? defaultRoot));
const workerPath = realpathSync(resolve(args.get("worker") ?? ""));
const agentdPath = realpathSync(resolve(args.get("agentd") ?? ""));
const protocolPath = realpathSync(resolve(args.get("protocol") ?? ""));
const output = resolve(args.get("output") ?? "candidate-manifest.json");
const expectedSha = args.get("expected-sha");
const expectedTree = args.get("expected-tree");

const cleanEnv = { ...process.env };
delete cleanEnv.GIT_DIR;
delete cleanEnv.GIT_WORK_TREE;
delete cleanEnv.GIT_INDEX_FILE;

function command(program, commandArgs, cwd = root) {
  return execFileSync(program, commandArgs, {
    cwd,
    env: cleanEnv,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  }).trim();
}
function git(...gitArgs) {
  return command("git", ["-C", root, ...gitArgs], root);
}
function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}
function requireCandidate(path, name) {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size === 0) {
    throw new Error(`${name} must be a non-empty regular non-symlink file`);
  }
  if ((stat.mode & 0o111) === 0) throw new Error(`${name} must be executable`);
  return stat;
}

const workerStat = requireCandidate(workerPath, "Servo worker candidate");
const agentdStat = requireCandidate(agentdPath, "Agentd candidate");
const sourceSha = git("rev-parse", "HEAD");
const sourceTree = git("rev-parse", "HEAD^{tree}");
if (expectedSha && sourceSha !== expectedSha) {
  throw new Error(`candidate source SHA drift: expected ${expectedSha}, observed ${sourceSha}`);
}
if (expectedTree && sourceTree !== expectedTree) {
  throw new Error(`candidate source tree drift: expected ${expectedTree}, observed ${sourceTree}`);
}

const lockPaths = [
  "codex-rs/Cargo.lock",
  "apps/hepta-browser/servo-worker/Cargo.lock",
].map((path) => resolve(root, path));
for (const path of lockPaths) {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size === 0) {
    throw new Error(`dependency lock must be a non-empty regular file: ${path}`);
  }
}

const protocol = JSON.parse(readFileSync(protocolPath, "utf8"));
if (protocol.schema !== "hepta.browser.servo-protocol-compatibility.v1") {
  throw new Error("protocol compatibility receipt has an unsupported schema");
}
if (!protocol.protocols.every((entry) =>
  entry.exactVersionAccepted === true &&
  entry.futureVersionRejected === true &&
  entry.unknownCriticalFieldRejected === true
)) {
  throw new Error("protocol compatibility matrix is not fail-closed");
}

const run = {
  repository: process.env.GITHUB_REPOSITORY ?? null,
  workflow: process.env.GITHUB_WORKFLOW ?? null,
  workflowRef: process.env.GITHUB_WORKFLOW_REF ?? null,
  runId: process.env.GITHUB_RUN_ID ?? null,
  runAttempt: process.env.GITHUB_RUN_ATTEMPT ?? null,
  job: process.env.GITHUB_JOB ?? null,
  event: process.env.GITHUB_EVENT_NAME ?? null,
  ref: process.env.GITHUB_REF ?? null,
  actor: process.env.GITHUB_ACTOR ?? null,
};

const manifest = {
  schema: "hepta.browser.servo-candidate-manifest.v2",
  module: "browser.servo",
  source: {
    sha: sourceSha,
    tree: sourceTree,
    commitTimestamp: git("show", "-s", "--format=%cI", "HEAD"),
    exactHead: expectedSha ? sourceSha === expectedSha : true,
    dirtyTracked: git("status", "--porcelain", "--untracked-files=no") !== "",
  },
  build: {
    sourceDateEpoch: git("show", "-s", "--format=%ct", "HEAD"),
    operatingSystem: `${process.platform}-${process.arch}`,
    node: process.version,
    rustc: command("rustc", ["-vV"]),
    cargo: command("cargo", ["-vV"]),
    environment: {
      runnerOs: process.env.RUNNER_OS ?? null,
      runnerArch: process.env.RUNNER_ARCH ?? null,
      imageOs: process.env.ImageOS ?? null,
      imageVersion: process.env.ImageVersion ?? null,
    },
  },
  dependencyLocks: {
    "codex-rs/Cargo.lock": sha256File(lockPaths[0]),
    "apps/hepta-browser/servo-worker/Cargo.lock": sha256File(lockPaths[1]),
  },
  artifacts: {
    agentd: {
      role: "persistent-browser-owner",
      path: agentdPath,
      bytes: agentdStat.size,
      sha256: sha256File(agentdPath),
    },
    servoWorker: {
      role: "browser-servo-worker",
      path: workerPath,
      bytes: workerStat.size,
      sha256: sha256File(workerPath),
    },
  },
  compatibility: {
    receiptSha256: sha256File(protocolPath),
    matrixDigest: protocol.matrixDigest,
    protocols: protocol.protocols,
  },
  signer: {
    identity: process.env.GITHUB_WORKFLOW_REF ?? null,
    oidcExpected: process.env.GITHUB_ACTIONS === "true",
    agentdAttestationBundle: process.env.AGENTD_ATTESTATION_BUNDLE || null,
    workerAttestationBundle: process.env.WORKER_ATTESTATION_BUNDLE || null,
  },
  qualificationRun: run,
  archivedProbe: false,
};
if (manifest.source.dirtyTracked) throw new Error("candidate build mutated tracked source");
manifest.manifestDigest = createHash("sha256")
  .update(JSON.stringify(manifest))
  .digest("hex");
writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${JSON.stringify(manifest)}\n`);
