#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import {
  assertEvidence,
  deploymentSubject,
  safeFailure,
  sha256,
  validateAssuranceChain,
  validateDeploymentSecurityReceipt,
  validateIndependentAcceptance,
  validateIndependentSecurityReview,
  validateOperationalExercise,
  validateProductionApproval,
  validateRealBackendReceipt,
  validateRepositoryQualificationReceipt,
} from "./external-evidence-lib.mjs";
import { createExternalEvidenceStageLedger } from "./external-evidence-stage-ledger.mjs";

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
const ledger = createExternalEvidenceStageLedger();
let stage = "deployment-identity";
let backendDeploymentDigest = null;
const evidenceDigests = {};

async function readEvidence(environmentName, digestKey) {
  const path = resolve(required(environmentName));
  const metadata = await stat(path);
  assertEvidence(metadata.isFile(), "UI_CONTROL_EVIDENCE_FILE", `${environmentName} is not a file`);
  assertEvidence(metadata.size > 0 && metadata.size <= MAX_EVIDENCE_BYTES, "UI_CONTROL_EVIDENCE_SIZE", `${environmentName} is empty or too large`);
  const bytes = await readFile(path);
  const digest = sha256(bytes);
  evidenceDigests[digestKey] = digest;
  ledger.attachEvidence(stage, digest);
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
  ledger.begin(stage);
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
  ledger.accept(stage);

  stage = "main-ancestry";
  ledger.begin(stage);
  const mainRef = "refs/remotes/origin/main";
  try {
    execFileSync("git", ["merge-base", "--is-ancestor", candidate.commit, mainRef], { stdio: "pipe" });
  } catch {
    const error = new Error(`candidate ${candidate.commit} is not reachable from ${mainRef}`);
    error.code = "UI_CONTROL_CANDIDATE_NOT_ON_MAIN";
    throw error;
  }
  ledger.accept(stage);

  stage = "repository-source-head";
  ledger.begin(stage);
  const sourceHead = await readEvidence("UI_CONTROL_SOURCE_HEAD_RECEIPT", "sourceHead");
  const sourceSummary = validateRepositoryQualificationReceipt(sourceHead, "source-head", expected);
  ledger.accept(stage);

  stage = "repository-synthetic-merge";
  ledger.begin(stage);
  const mergeTree = await readEvidence("UI_CONTROL_MERGE_TREE_RECEIPT", "mergeTree");
  const mergeSummary = validateRepositoryQualificationReceipt(mergeTree, "synthetic-merge", expected);
  ledger.accept(stage);

  stage = "deployment-security";
  ledger.begin(stage);
  const deploymentSecurity = await readEvidence("UI_CONTROL_DEPLOYMENT_SECURITY_RECEIPT", "deploymentSecurity");
  const deploymentSummary = validateDeploymentSecurityReceipt(deploymentSecurity, expected);
  assertEvidence(
    deploymentSummary.browserBuildManifestSha256 === sourceSummary.browserBuildManifestSha256,
    "UI_CONTROL_DEPLOYED_BUILD_IDENTITY",
    "deployed asset manifest is not the exact source-head build manifest",
  );
  ledger.accept(stage);

  stage = "real-backend";
  ledger.begin(stage);
  const realBackend = await readEvidence("UI_CONTROL_REAL_BACKEND_RECEIPT", "realBackend");
  validateRealBackendReceipt(realBackend, expected);
  ledger.accept(stage);

  stage = "independent-accessibility-and-operator-acceptance";
  ledger.begin(stage);
  const independentAcceptance = await readEvidence("UI_CONTROL_INDEPENDENT_ACCEPTANCE_RECEIPT", "independentAcceptance");
  validateIndependentAcceptance(independentAcceptance, expected);
  ledger.accept(stage);

  stage = "independent-security-review";
  ledger.begin(stage);
  const independentSecurity = await readEvidence("UI_CONTROL_INDEPENDENT_SECURITY_RECEIPT", "independentSecurity");
  validateIndependentSecurityReview(independentSecurity, expected);
  ledger.accept(stage);

  stage = "operational-exercise";
  ledger.begin(stage);
  const operationalExercise = await readEvidence("UI_CONTROL_OPERATIONAL_EXERCISE_RECEIPT", "operationalExercise");
  validateOperationalExercise(operationalExercise, expected);
  ledger.accept(stage);

  stage = "production-approval";
  ledger.begin(stage);
  const productionApproval = await readEvidence("UI_CONTROL_PRODUCTION_APPROVAL_RECEIPT", "productionApproval");
  const approvalBoundDigests = Object.fromEntries(
    Object.entries(evidenceDigests).filter(([key]) => key !== "productionApproval"),
  );
  validateProductionApproval(productionApproval, expected, approvalBoundDigests);
  const assuranceChain = validateAssuranceChain({
    deploymentSecurityReceipt: deploymentSecurity,
    realBackendReceipt: realBackend,
    independentAcceptanceReceipt: independentAcceptance,
    independentSecurityReceipt: independentSecurity,
    operationalExerciseReceipt: operationalExercise,
    productionApprovalReceipt: productionApproval,
  });
  ledger.accept(stage);
  const claims = {
    ...ledger.claims(),
    independentAssurancePrincipals: assuranceChain.reviewerSeparationVerified,
    evidenceChronologyBound: assuranceChain.evidenceChronologyBound,
  };
  assertEvidence(
    claims.productionDeploymentApproved === true && claims.releaseAuthorized === true,
    "UI_CONTROL_RELEASE_PREREQUISITES",
    "production approval cannot authorize release until every prerequisite stage is accepted",
  );

  await emit({
    schema: "hepta.ui-control.external-evidence-bundle.v1",
    status: "accepted",
    observedAt: new Date().toISOString(),
    candidate,
    syntheticMerge: mergeSummary.evaluated,
    deployment: deployment.subject,
    backendDeploymentDigest,
    evidenceDigests,
    stageResults: ledger.snapshot(),
    assuranceChain,
    claims,
  });
} catch (error) {
  const failure = safeFailure(error, stage);
  ledger.fail(stage, failure.code);
  await emit({
    schema: "hepta.ui-control.external-evidence-bundle.v1",
    status: "failed",
    observedAt: new Date().toISOString(),
    candidate,
    backendDeploymentDigest,
    evidenceDigests,
    stageResults: ledger.snapshot(),
    failure,
    claims: ledger.claims(),
  });
  process.exitCode = 1;
}
