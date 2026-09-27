import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";

const output = resolve(process.argv[2] ?? "ui-control-qualification-receipt.json");
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const buildManifest = await readFile(new URL("../dist/build-manifest.json", import.meta.url), "utf8");
const dependencyLock = await readFile(new URL("../package-lock.json", import.meta.url), "utf8");
const statusManifestText = await readFile(
  new URL("../../../qualification/ui-control/UI_CONTROL_MANIFEST.json", import.meta.url),
  "utf8",
);
const statusManifest = JSON.parse(statusManifestText);
const sha256 = value => createHash("sha256").update(value).digest("hex");
const passed = name => process.env[name] === "passed";
const candidateKind = process.env.UI_CONTROL_CANDIDATE_KIND ?? "source-head";
if (!["source-head", "synthetic-merge"].includes(candidateKind)) {
  throw new Error(`unsupported UI_CONTROL_CANDIDATE_KIND: ${candidateKind}`);
}

const evaluatedSha = command("git", "rev-parse", "HEAD");
const evaluatedTree = command("git", "rev-parse", "HEAD^{tree}");
const sourceSha = process.env.UI_CONTROL_SOURCE_SHA || evaluatedSha;
const baseSha = process.env.UI_CONTROL_BASE_SHA || null;
const treeFor = sha => {
  if (!sha) return null;
  try {
    return command("git", "rev-parse", `${sha}^{tree}`);
  } catch {
    return null;
  }
};

const sourceChecksPassed = [
  "UI_CONTROL_DEPENDENCY_LOCK",
  "UI_CONTROL_LINT",
  "UI_CONTROL_UNIT",
  "UI_CONTROL_CONTRACT",
  "UI_CONTROL_BUILD",
  "UI_CONTROL_LANE_B_GUARD",
  "UI_CONTROL_DOCS",
].every(passed);
const browserChecksPassed =
  sourceChecksPassed && passed("UI_CONTROL_E2E") && passed("UI_CONTROL_AXE");
const mergeChecksPassed = candidateKind === "synthetic-merge" && browserChecksPassed;

const receipt = {
  schema: "hepta.ui-control.qualification-receipt.v2",
  candidate: {
    kind: candidateKind,
    evaluated: { sha: evaluatedSha, tree: evaluatedTree },
    sourceHead: { sha: sourceSha, tree: treeFor(sourceSha) },
    base: baseSha ? { sha: baseSha, tree: treeFor(baseSha) } : null,
  },
  runtime: {
    node: process.version,
    npm: command("npm", "--version"),
    platform: process.platform,
    architecture: process.arch,
  },
  checks: {
    dependencyLock: process.env.UI_CONTROL_DEPENDENCY_LOCK ?? "unknown",
    lint: process.env.UI_CONTROL_LINT ?? "unknown",
    unit: process.env.UI_CONTROL_UNIT ?? "unknown",
    contract: process.env.UI_CONTROL_CONTRACT ?? "unknown",
    build: process.env.UI_CONTROL_BUILD ?? "unknown",
    browserE2e: process.env.UI_CONTROL_E2E ?? "unknown",
    axe: process.env.UI_CONTROL_AXE ?? "unknown",
    laneBGuard: process.env.UI_CONTROL_LANE_B_GUARD ?? "unknown",
    documentation: process.env.UI_CONTROL_DOCS ?? "unknown",
  },
  verificationStages: {
    designDefined: {
      state: "passed",
      policy: statusManifest.verificationStages.designDefined,
    },
    codePresent: {
      state: "passed",
      policy: statusManifest.verificationStages.codePresent,
      sourceRoots: statusManifest.sourceRoots,
    },
    sourceTestsPassed: {
      state: sourceChecksPassed ? "passed" : "not-passed",
      policy: statusManifest.verificationStages.sourceTestsPassed,
      boundTo: { sha: evaluatedSha, tree: evaluatedTree },
    },
    browserTestsPassed: {
      state: browserChecksPassed ? "passed" : "not-passed",
      policy: statusManifest.verificationStages.browserTestsPassed,
      browserMatrix: statusManifest.verification.browserMatrix,
      boundTo: { sha: evaluatedSha, tree: evaluatedTree },
    },
    mergeTreePassed: {
      state: mergeChecksPassed ? "passed" : candidateKind === "synthetic-merge" ? "not-passed" : "not-evaluated",
      policy: statusManifest.verificationStages.mergeTreePassed,
      boundTo: candidateKind === "synthetic-merge"
        ? { sha: evaluatedSha, tree: evaluatedTree }
        : null,
    },
    realBackendPassed: {
      state: "not-observed",
      policy: statusManifest.verificationStages.realBackendPassed,
    },
    productionDeploymentApproved: {
      state: "not-authorized",
      policy: statusManifest.verificationStages.productionDeploymentApproved,
    },
  },
  artifacts: {
    dependencyLockSha256: sha256(dependencyLock),
    browserBuildManifestSha256: sha256(buildManifest),
    statusManifestSha256: sha256(statusManifestText),
  },
  claims: {
    repositorySourceQualified: sourceChecksPassed,
    repositoryBrowserCompositionQualified: browserChecksPassed,
    deterministicMergeQualified: mergeChecksPassed,
    deployedBackendQualified: false,
    productionIdentityProviderQualified: false,
    productionCspObserved: false,
    independentAcceptanceSigned: false,
    releaseAuthorized: false,
  },
};
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(receipt, null, 2)}\n`);
console.log(output);