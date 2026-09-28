#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { mkdir } from "node:fs/promises";
import {
  assertEvidence,
  deploymentSubject,
  safeFailure,
  sha256,
  validateDeploymentSecurityReceipt,
  validateIndependentAcceptance,
  validateIndependentSecurityReview,
  validateOperationalExercise,
  validateProductionApproval,
  validateRealBackendReceipt,
  validateRepositoryQualificationReceipt,
} from "./external-evidence-lib.mjs";

const MAX_EVIDENCE_BYTES = 2 * 1024 * 1024;
const required = name => {
  const value = process.env[name];
  if (!value) {
    const error = new Error(`${name} is required`);
    error.code = "UI_CONTROL_EXTERNAL_INPUT_MISSING";
    throw error;
  }
  return value;
};
const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();
const output = resolve(process.argv[2] ?? "ui-control-production-evidence/external-evidence-bundle.json");
const candidate = Object.freeze({
  commit: git("rev-parse", "HEAD"),
  tree: git("rev-parse", "HEAD^{tree}"),
});
let stage = "initialization";
let backendDeploymentDigest = null;
const evidenceDigests = {};

async function readEvidence(environmentName, digestKey) {
  const path = resolve(required(environmentName));
  const metadata = await stat(path);
  assertEvidence(metadata.isFile(), "UI_CONTROL_EVIDENCE_FILE", `${environmentName} is not a file`);
  assertEvidence(metadata.size > 0 && metadata.size <= MAX_EVIDENCE_BYTES, "UI_CONTROL_EVIDENCE_SIZE", `${environmentName} is empty or too large`);
  const bytes = await readFile(path);
  evidenceDigests[digestKey] = sha256(bytes);
  try {
    return JSON.parse(bytes.toString("utf8"));
  } catch {
    const error = new Error(`${environmentName} contains malformed JSON`);
    error.code = "UI_CONTROL_EVIDENCE_JSON";
    throw error;
  }
}

async function emit(receipt) {
  await mkdir(dirname(output), { recursive: true });
  const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
  await writeFile(output, serialized);
  process.stdout.write(serialized);
}

try {
  stage = "deployment-identity";
  const deployment = deploymentSubject(
    required("HEPTA_UI_CONTROL_BASE_URL"),
    required("HEPTA_UI_CONTROL_DEPLOYMENT_ID"),
  );
  backendDeploymentDigest = deployment.digest;
  const expected = {
    candidateCommit: candidate.commit,
    candidateTree: candidate.tree,
    backendDeploymentDigest,
  };

  if (process.env.UI_CONTROL_REQUIRE_MAIN_ANCESTRY === "true") {
    stage = "main-ancestry";
    const mainRef = process.env.UI_CONTROL_MAIN_REF || "refs/remotes/origin/main";
    try {
      execFileSync("git", ["merge-base", "--is-ancestor", candidate.commit, mainRef], { stdio: "pipe" });
    } catch {
      const error = new Error(`candidate ${candidate.commit} is not reachable from ${mainRef}`);
      error.code = "UI_CONTROL_CANDIDATE_NOT_ON_MAIN";
      throw error;
    }
  }

  stage = "repository-source-head";
  const sourceHead = await readEvidence("UI_CONTROL_SOURCE_HEAD_RECEIPT", "sourceHead");
  const sourceSummary = validateRepositoryQualificationReceipt(sourceHead, "source-head", expected);

  stage = "repository-synthetic-merge";
  const mergeTree = await readEvidence("UI_CONTROL_MERGE_TREE_RECEIPT", "mergeTree");
  const mergeSummary = validateRepositoryQualificationReceipt(mergeTree, "synthetic-merge", expected);

  stage = "deployment-security";
  const deploymentSecurity = await readEvidence("UI_CONTROL_DEPLOYMENT_SECURITY_RECEIPT", "deploymentSecurity");
  const deploymentSummary = validateDeploymentSecurityReceipt(deploymentSecurity, expected);
  assertEvidence(
    deploymentSummary.browserBuildManifestSha256 === sourceSummary.browserBuildManifestSha256,
    "UI_CONTROL_DEPLOYED_BUILD_IDENTITY",
    "deployed asset manifest is not the exact source-head build manifest",
  );

  stage = "real-backend";
  const realBackend = await readEvidence("UI_CONTROL_REAL_BACKEND_RECEIPT", "realBackend");
  validateRealBackendReceipt(realBackend, expected);

  stage = "independent-accessibility-and-operator-acceptance";
  const independentAcceptance = await readEvidence("UI_CONTROL_INDEPENDENT_ACCEPTANCE_RECEIPT", "independentAcceptance");
  validateIndependentAcceptance(independentAcceptance, expected);

  stage = "independent-security-review";
  const independentSecurity = await readEvidence("UI_CONTROL_INDEPENDENT_SECURITY_RECEIPT", "independentSecurity");
  validateIndependentSecurityReview(independentSecurity, expected);

  stage = "operational-exercise";
  const operationalExercise = await readEvidence("UI_CONTROL_OPERATIONAL_EXERCISE_RECEIPT", "operationalExercise");
  validateOperationalExercise(operationalExercise, expected);

  stage = "production-approval";
  const productionApproval = await readEvidence("UI_CONTROL_PRODUCTION_APPROVAL_RECEIPT", "productionApproval");
  const approvalBoundDigests = Object.fromEntries(
    Object.entries(evidenceDigests).filter(([key]) => key !== "productionApproval"),
  );
  validateProductionApproval(productionApproval, expected, approvalBoundDigests);

  await emit({
    schema: "hepta.ui-control.external-evidence-bundle.v1",
    status: "accepted",
    observedAt: new Date().toISOString(),
    candidate,
    syntheticMerge: mergeSummary.evaluated,
    deployment: deployment.subject,
    backendDeploymentDigest,
    evidenceDigests,
    claims: {
      repositorySourceQualified: true,
      repositoryBrowserCompositionQualified: true,
      deterministicMergeQualified: true,
      deployedSecurityObserved: true,
      exactCandidateAssetsObserved: true,
      realBackendSemanticsQualified: true,
      durableCrashRestartQualified: true,
      identityPermissionAndSessionSwitchQualified: true,
      independentAccessibilityAndOperatorAcceptanceSigned: true,
      independentSecurityReviewPassed: true,
      rollbackDisasterRecoveryMonitoringAndRedactionExercised: true,
      productionDeploymentApproved: true,
      releaseAuthorized: true,
    },
  });
} catch (error) {
  await emit({
    schema: "hepta.ui-control.external-evidence-bundle.v1",
    status: "failed",
    observedAt: new Date().toISOString(),
    candidate,
    backendDeploymentDigest,
    evidenceDigests,
    failure: safeFailure(error, stage),
    claims: {
      repositorySourceQualified: false,
      repositoryBrowserCompositionQualified: false,
      deterministicMergeQualified: false,
      deployedSecurityObserved: false,
      exactCandidateAssetsObserved: false,
      realBackendSemanticsQualified: false,
      durableCrashRestartQualified: false,
      identityPermissionAndSessionSwitchQualified: false,
      independentAccessibilityAndOperatorAcceptanceSigned: false,
      independentSecurityReviewPassed: false,
      rollbackDisasterRecoveryMonitoringAndRedactionExercised: false,
      productionDeploymentApproved: false,
      releaseAuthorized: false,
    },
  });
  process.exitCode = 1;
}
