#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { lstat, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, posix, relative, resolve, sep } from "node:path";
import {
  UI_CONTROL_BROWSER_BUILD_SCHEMA,
  assertRuntimeSubstitutionManifest,
} from "./deployment-asset-invariants.mjs";
import {
  assertEvidence,
  safeFailure,
  sha256,
} from "./external-evidence-primitives.mjs";
import { validateRepositoryQualificationReceipt } from "./external-evidence-repository.mjs";

const MAX_FILES = 512;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_TOTAL_BYTES = 64 * 1024 * 1024;
const SAFE_PATH_COMPONENT = /^[A-Za-z0-9._-]+$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const manifestPath = process.argv[2] ? resolve(process.argv[2]) : null;
const sourceReceiptPath = process.argv[3] ? resolve(process.argv[3]) : null;
const output = process.argv[4] ? resolve(process.argv[4]) : null;
const source = {
  sha: command("git", "rev-parse", "HEAD"),
  tree: command("git", "rev-parse", "HEAD^{tree}"),
};
let stage = "initialization";

async function emit(observation) {
  const serialized = `${JSON.stringify(observation, null, 2)}\n`;
  if (output) await writeFile(output, serialized);
  process.stdout.write(serialized);
}

function assertSafeRelativePath(value) {
  assertEvidence(
    typeof value === "string" && value.length > 0 && value.length <= 240,
    "UI_CONTROL_BUILD_PATH",
    "browser build path must be a bounded non-empty string",
  );
  assertEvidence(
    !value.includes("\\") &&
      !value.startsWith("/") &&
      posix.normalize(value) === value &&
      value.split("/").every(component =>
        component !== "." && component !== ".." && SAFE_PATH_COMPONENT.test(component)),
    "UI_CONTROL_BUILD_PATH",
    `unsafe browser build path: ${value}`,
  );
  return value;
}

function containedPath(root, relativePath) {
  const absolute = resolve(root, relativePath);
  const fromRoot = relative(root, absolute);
  assertEvidence(
    fromRoot !== "" && fromRoot !== ".." && !fromRoot.startsWith(`..${sep}`),
    "UI_CONTROL_BUILD_PATH_ESCAPE",
    `${relativePath}: browser build path escapes its artifact root`,
  );
  return absolute;
}

async function collectFiles(root, directory = root, observed = []) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = resolve(directory, entry.name);
    const relativePath = relative(root, absolute).split(sep).join("/");
    assertSafeRelativePath(relativePath);
    assertEvidence(!entry.isSymbolicLink(), "UI_CONTROL_BUILD_SYMLINK", `${relativePath}: symbolic links are forbidden`);
    if (entry.isDirectory()) {
      await collectFiles(root, absolute, observed);
    } else {
      assertEvidence(entry.isFile(), "UI_CONTROL_BUILD_FILE_TYPE", `${relativePath}: only regular files are allowed`);
      if (relativePath !== "build-manifest.json") observed.push(relativePath);
    }
    assertEvidence(observed.length <= MAX_FILES, "UI_CONTROL_BUILD_FILE_COUNT", "browser build contains too many files");
  }
  return observed;
}

try {
  assertEvidence(manifestPath, "UI_CONTROL_BUILD_MANIFEST_INPUT", "candidate build manifest path is required");
  assertEvidence(sourceReceiptPath, "UI_CONTROL_SOURCE_RECEIPT_INPUT", "source-head receipt path is required");

  stage = "source-receipt";
  const sourceReceipt = JSON.parse(await readFile(sourceReceiptPath, "utf8"));
  const sourceSummary = validateRepositoryQualificationReceipt(sourceReceipt, "source-head", {
    candidateCommit: source.sha,
    candidateTree: source.tree,
  });

  stage = "manifest";
  const manifestText = await readFile(manifestPath, "utf8");
  const manifestDigest = sha256(manifestText);
  assertEvidence(
    manifestDigest === sourceSummary.browserBuildManifestSha256,
    "UI_CONTROL_BUILD_MANIFEST_RECEIPT_MISMATCH",
    "candidate build manifest does not match the accepted exact-head receipt",
  );
  const manifest = JSON.parse(manifestText);
  assertEvidence(
    manifest?.schema === UI_CONTROL_BROWSER_BUILD_SCHEMA,
    "UI_CONTROL_BUILD_MANIFEST_SCHEMA",
    "unsupported browser build manifest schema",
  );
  assertRuntimeSubstitutionManifest(manifest.runtimeSubstitutions);
  assertEvidence(
    manifest.files && typeof manifest.files === "object" && !Array.isArray(manifest.files),
    "UI_CONTROL_BUILD_FILES",
    "browser build manifest files must be an object",
  );
  const manifestPaths = Object.keys(manifest.files);
  assertEvidence(
    manifestPaths.length > 1 && manifestPaths.length <= MAX_FILES,
    "UI_CONTROL_BUILD_FILE_COUNT",
    "browser build manifest must contain a bounded non-trivial file set",
  );
  assertEvidence(manifestPaths.includes("index.html"), "UI_CONTROL_BUILD_INDEX", "browser build manifest is missing index.html");
  assertEvidence(
    JSON.stringify(manifestPaths) === JSON.stringify([...manifestPaths].sort()),
    "UI_CONTROL_BUILD_FILE_ORDER",
    "browser build manifest paths must be sorted deterministically",
  );

  stage = "artifact-file-set";
  const buildRoot = dirname(manifestPath);
  const actualPaths = (await collectFiles(buildRoot)).sort();
  assertEvidence(
    JSON.stringify(actualPaths) === JSON.stringify([...manifestPaths].sort()),
    "UI_CONTROL_BUILD_FILE_SET",
    "candidate build artifact file set does not exactly match its manifest",
  );

  stage = "artifact-bytes";
  let totalBytes = 0;
  for (const relativePath of manifestPaths) {
    assertSafeRelativePath(relativePath);
    const metadata = manifest.files[relativePath];
    assertEvidence(
      metadata && typeof metadata === "object" && !Array.isArray(metadata) &&
        Object.keys(metadata).length === 2 &&
        Object.hasOwn(metadata, "bytes") &&
        Object.hasOwn(metadata, "sha256"),
      "UI_CONTROL_BUILD_FILE_METADATA",
      `${relativePath}: invalid browser build metadata`,
    );
    assertEvidence(
      Number.isSafeInteger(metadata.bytes) && metadata.bytes > 0 && metadata.bytes <= MAX_FILE_BYTES,
      "UI_CONTROL_BUILD_FILE_SIZE",
      `${relativePath}: invalid browser build byte count`,
    );
    assertEvidence(SHA256.test(metadata.sha256), "UI_CONTROL_BUILD_FILE_DIGEST", `${relativePath}: invalid SHA-256 digest`);
    const absolute = containedPath(buildRoot, relativePath);
    const stat = await lstat(absolute);
    assertEvidence(stat.isFile() && !stat.isSymbolicLink(), "UI_CONTROL_BUILD_FILE_TYPE", `${relativePath}: only regular files are allowed`);
    const bytes = await readFile(absolute);
    assertEvidence(
      bytes.byteLength === metadata.bytes && sha256(bytes) === metadata.sha256,
      "UI_CONTROL_BUILD_FILE_DRIFT",
      `${relativePath}: candidate build bytes do not match the manifest`,
    );
    totalBytes += bytes.byteLength;
    assertEvidence(totalBytes <= MAX_TOTAL_BYTES, "UI_CONTROL_BUILD_TOTAL_SIZE", "browser build exceeds the total byte budget");
  }

  await emit({
    schema: "hepta.ui-control.candidate-build-observation.v1",
    status: "passed",
    observedAt: new Date().toISOString(),
    candidate: { commit: source.sha, tree: source.tree },
    browserBuildManifestSha256: manifestDigest,
    verifiedFileCount: manifestPaths.length,
    verifiedTotalBytes: totalBytes,
    claims: {
      exactCandidateBuildObserved: true,
      protectedSecretsEligible: true,
      productionDeploymentApproved: false,
      releaseAuthorized: false,
    },
  });
} catch (error) {
  await emit({
    schema: "hepta.ui-control.candidate-build-observation.v1",
    status: "failed",
    observedAt: new Date().toISOString(),
    candidate: { commit: source.sha, tree: source.tree },
    failure: safeFailure(error, stage),
    claims: {
      exactCandidateBuildObserved: false,
      protectedSecretsEligible: false,
      productionDeploymentApproved: false,
      releaseAuthorized: false,
    },
  });
  process.exitCode = 1;
}
