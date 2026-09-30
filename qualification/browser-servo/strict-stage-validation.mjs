#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  lstatSync,
  readFileSync,
  realpathSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";

function parseArgs(argv) {
  const args = new Map();
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`invalid argument sequence at ${key ?? "<end>"}`);
    }
    args.set(key.slice(2), value);
  }
  return args;
}

const args = parseArgs(process.argv);
const root = realpathSync(resolve(args.get("root") ?? "."));
const expectedSha = args.get("expected-sha");
const expectedTree = args.get("expected-tree");
const output = resolve(args.get("output") ?? "stage-validation.json");
const execute = (args.get("execute") ?? "false") === "true";
const minimumTests = Number(args.get("minimum-tests") ?? "1");

if (!Number.isSafeInteger(minimumTests) || minimumTests < 1) {
  throw new Error("minimum-tests must be a positive safe integer");
}

const cleanEnv = { ...process.env };
delete cleanEnv.GIT_DIR;
delete cleanEnv.GIT_WORK_TREE;
delete cleanEnv.GIT_INDEX_FILE;

function git(...gitArgs) {
  return execFileSync("git", ["-C", root, ...gitArgs], {
    encoding: "utf8",
    env: cleanEnv,
    maxBuffer: 16 * 1024 * 1024,
  }).trim();
}

function run(command, commandArgs, cwd = root) {
  execFileSync(command, commandArgs, {
    cwd,
    env: cleanEnv,
    stdio: "inherit",
    maxBuffer: 64 * 1024 * 1024,
  });
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function requireRegularFile(path, name) {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`${name} must be a regular non-symlink file: ${path}`);
  }
}

if (git("rev-parse", "--is-inside-work-tree") !== "true") {
  throw new Error("staged root is not a Git worktree");
}
const topLevel = realpathSync(git("rev-parse", "--show-toplevel"));
if (topLevel !== root) {
  throw new Error(`staged Git top-level drift: expected ${root}, observed ${topLevel}`);
}
const sourceSha = git("rev-parse", "HEAD");
const sourceTree = git("rev-parse", "HEAD^{tree}");
if (expectedSha && sourceSha !== expectedSha) {
  throw new Error(`staged source SHA drift: expected ${expectedSha}, observed ${sourceSha}`);
}
if (expectedTree && sourceTree !== expectedTree) {
  throw new Error(`staged source tree drift: expected ${expectedTree}, observed ${sourceTree}`);
}

const packagePath = join(root, "apps/hepta-browser/package.json");
requireRegularFile(packagePath, "Browser package manifest");
const packageJson = JSON.parse(readFileSync(packagePath, "utf8"));
const requiredScripts = [
  "test",
  "check",
  "verify:qualification",
  "verify:registry",
  "worker:check",
  "worker:test",
];
for (const name of requiredScripts) {
  if (typeof packageJson.scripts?.[name] !== "string" || packageJson.scripts[name].trim() === "") {
    throw new Error(`Browser package script is missing: ${name}`);
  }
}

const testDirectory = join(root, "apps/hepta-browser/test");
const tests = readdirSync(testDirectory)
  .filter((name) => name.endsWith(".test.js"))
  .sort()
  .map((name) => join(testDirectory, name));
if (tests.length < minimumTests) {
  throw new Error(`staged Browser test discovery found ${tests.length}; expected at least ${minimumTests}`);
}
for (const testFile of tests) requireRegularFile(testFile, "Browser test");

if (execute) {
  run("npm", ["--prefix", "apps/hepta-browser", "run", "check"]);
  run("npm", ["--prefix", "apps/hepta-browser", "run", "worker:check"]);
  run("npm", ["--prefix", "apps/hepta-browser", "run", "worker:test"]);
}

const dirtyTracked = git("status", "--porcelain", "--untracked-files=no");
if (dirtyTracked !== "") {
  throw new Error(`staged workspace mutated tracked source:\n${dirtyTracked}`);
}

const receipt = {
  schema: "hepta.browser.servo-staged-workspace-receipt.v1",
  sourceSha,
  sourceTree,
  root,
  gitDirectory: git("rev-parse", "--absolute-git-dir"),
  packageManifestSha256: sha256(packagePath),
  requiredScripts: Object.fromEntries(
    requiredScripts.map((name) => [name, packageJson.scripts[name]]),
  ),
  discoveredTests: tests.map((path) => path.slice(root.length + 1)),
  testCount: tests.length,
  commandsExecuted: execute,
  strict: true,
};
writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
process.stdout.write(`${JSON.stringify(receipt)}\n`);
