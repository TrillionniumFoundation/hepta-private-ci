import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  INDEPENDENT_SECURITY_CONTROLS,
  REQUIRED_DEPLOYMENT_SECURITY_CHECKS,
  REQUIRED_REAL_BACKEND_CASES,
  deploymentSubject,
  safeFailure,
  validateAuthorityEvidence,
  validateChaosEvidence,
  validateDeploymentSecurityReceipt,
  validateIndependentAcceptance,
  validateIndependentAcceptanceMatrix,
  validateIndependentSecurityReview,
  validateOperationalExercise,
  validateOperationalExerciseWithRolloutFence,
  validateProductionApproval,
  validateRealBackendReceipt,
  validateRepositoryQualificationReceipt,
} from "../../../qualification/ui-control/external-evidence-lib.mjs";
import { UI_CONTROL_CSRF_SUBSTITUTION_KIND } from "../../../qualification/ui-control/deployment-asset-invariants.mjs";
import {
  UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
} from "../../../qualification/ui-control/deployment-security-invariants.mjs";

const commit = "a".repeat(40);
const tree = "b".repeat(40);
const digest = "c".repeat(64);
const raw = "d".repeat(64);
const now = Date.parse("2026-09-28T00:00:00Z");
const executedAt = "2026-09-27T00:00:00Z";
const expected = { candidateCommit: commit, candidateTree: tree, backendDeploymentDigest: digest };
const fingerprint = Array.from({ length: 32 }, () => "AA").join(":");

function chaosEvidence() {
  return {
    schema: "hepta.ui-control.agentd-chaos-evidence.v2",
    candidateCommit: commit,
    candidateTree: tree,
    backendDeploymentDigest: digest,
    executedAt,
    executor: "independent chaos runner",
    cases: [
      {
        id: "crash-before-admission-commit",
        status: "passed",
        operationId: "op-1",
        semanticDigest: "1".repeat(64),
        durableRecordDigest: null,
        agentdInstanceDigest: "2".repeat(64),
        observedRecordCount: 0,
        observedSideEffectCount: 0,
        terminalStatus: null,
        rawEvidenceDigest: raw,
      },
      {
        id: "crash-after-admission-before-dispatch",
        status: "passed",
        operationId: "op-2",
        semanticDigest: "3".repeat(64),
        durableRecordDigest: "4".repeat(64),
        agentdInstanceDigest: "5".repeat(64),
        observedRecordCount: 1,
        observedSideEffectCount: 0,
        terminalStatus: null,
        rawEvidenceDigest: raw,
      },
      {
        id: "crash-after-dispatch-before-terminal-observation",
        status: "passed",
        operationId: "op-3",
        semanticDigest: "6".repeat(64),
        durableRecordDigest: "7".repeat(64),
        agentdInstanceDigest: "8".repeat(64),
        observedRecordCount: 1,
        observedSideEffectCount: 1,
        terminalStatus: null,
        rawEvidenceDigest: raw,
      },
      {
        id: "restart-reconciles-terminal-state",
        status: "passed",
        operationId: "op-3",
        semanticDigest: "6".repeat(64),
        durableRecordDigest: "7".repeat(64),
        agentdInstanceDigest: "9".repeat(64),
        observedRecordCount: 1,
        observedSideEffectCount: 1,
        terminalStatus: "succeeded",
        rawEvidenceDigest: raw,
      },
    ],
    rawEvidenceDigest: raw,
  };
}

function deploymentReceipt() {
  return {
    schema: "hepta.ui-control.deployment-security-receipt.v2",
    status: "passed",
    candidateCommit: commit,
    candidateTree: tree,
    backendDeploymentDigest: digest,
    deployment: { observedAt: executedAt },
    source: { browserBuildManifestSha256: "2".repeat(64) },
    policy: {
      profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
      minimumHstsMaxAgeSeconds: UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
      minimumCertificateLifetimeSeconds: UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
    },
    tls: {
      profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
      protocol: "TLSv1.3",
      cipher: "TLS_AES_256_GCM_SHA384",
      certificateValidTo: "2027-09-27T00:00:00Z",
      certificateFingerprint256: fingerprint,
    },
    assets: {
      verifiedAssetCount: 17,
      runtimeSubstitutions: [{ path: "index.html", kind: UI_CONTROL_CSRF_SUBSTITUTION_KIND }],
    },
    checks: [...REQUIRED_DEPLOYMENT_SECURITY_CHECKS],
    claims: { deployedSecurityObserved: true, exactCandidateAssetsObserved: true },
  };
}

function backendReceipt() {
  return {
    schema: "hepta.ui-control.real-backend-receipt.v2",
    status: "passed",
    candidateCommit: commit,
    candidateTree: tree,
    backendDeploymentDigest: digest,
    backend: {
      observedAt: executedAt,
      primaryIdentity: "operator-primary",
      secondaryIdentity: "operator-secondary",
      runtimeGeneration: 7,
      runtimeRevision: 12,
    },
    cases: [...REQUIRED_REAL_BACKEND_CASES],
    terminalObservations: {
      duplicateOperation: "succeeded",
      responseLossOperation: "succeeded",
    },
    operationBindings: {
      duplicateOperation: {
        operationIdSha256: "6".repeat(64),
        semanticDigest: "7".repeat(64),
        auditTraceIdSha256: "8".repeat(64),
      },
      responseLossOperation: {
        operationIdSha256: "9".repeat(64),
        semanticDigest: "a".repeat(64),
        auditTraceIdSha256: "b".repeat(64),
      },
    },
    evidence: {
      chaosEvidenceSha256: "3".repeat(64),
      chaosRawEvidenceDigest: "4".repeat(64),
      authorityEvidenceSha256: "5".repeat(64),
    },
    claims: {
      realBackendSemanticsQualified: true,
      durableIdempotencyQualified: true,
      crashRestartQualified: true,
      permissionRevisionAndRevocationQualified: true,
      sessionSwitchQualified: true,
    },
  };
}

function statusOnlyAcceptanceReceipt() {
  return {
    schema: "hepta.ui-control.independent-acceptance-receipt.v2",
    status: "passed",
    ...expected,
    executedAt,
    rawEvidenceDigest: raw,
    verifier: {
      identity: "Verifier",
      organization: "Independent Lab",
      independentOfImplementationAuthor: true,
    },
    observations: [
      {
        id: "chrome-keyboard",
        modality: "keyboard-only",
        browser: { name: "Chrome", version: "154" },
        os: "Windows",
        result: "pass",
        rawEvidenceDigest: raw,
      },
      {
        id: "firefox-operator",
        modality: "browser-operator",
        browser: { name: "Firefox", version: "150" },
        os: "Linux",
        result: "pass",
        rawEvidenceDigest: raw,
      },
      {
        id: "safari-operator",
        modality: "browser-operator",
        browser: { name: "Safari", version: "20" },
        os: "macOS",
        result: "pass",
        rawEvidenceDigest: raw,
      },
      {
        id: "nvda",
        modality: "screen-reader",
        browser: { name: "Chrome", version: "154" },
        os: "Windows",
        assistiveTechnology: { name: "NVDA", version: "2026.2" },
        result: "pass",
        rawEvidenceDigest: raw,
      },
      {
        id: "voiceover",
        modality: "screen-reader",
        browser: { name: "Safari", version: "20" },
        os: "macOS",
        assistiveTechnology: { name: "VoiceOver", version: "20" },
        result: "pass",
        rawEvidenceDigest: raw,
      },
    ],
  };
}

function statusOnlyOperationalReceipt() {
  return {
    schema: "hepta.ui-control.operational-exercise-receipt.v1",
    status: "passed",
    ...expected,
    executedAt,
    rawEvidenceDigest: raw,
    cases: ["rollback", "disaster-recovery", "alert-routing", "log-redaction", "credential-rotation"]
      .map(id => ({ id, status: "passed", rawEvidenceDigest: raw })),
  };
}

test("deployment identity is stable and path-sensitive", () => {
  const first = deploymentSubject("https://control.example.test/console/", "release-17");
  const second = deploymentSubject("https://control.example.test/console", "release-17");
  const other = deploymentSubject("https://control.example.test/other", "release-17");
  assert.equal(first.digest, second.digest);
  assert.notEqual(first.digest, other.digest);
  assert.equal(first.subject.basePath, "/console");
});

test("chaos evidence binds restart recovery to the exact durable operation and a new Agentd instance", () => {
  const summary = validateChaosEvidence(chaosEvidence(), expected, { now });
  assert.equal(summary.caseCount, 4);
  assert.equal(summary.recoveryBinding.semanticDigest, "6".repeat(64));
  assert.equal(summary.recoveryBinding.durableRecordDigest, "7".repeat(64));

  const wrong = chaosEvidence();
  wrong.cases[0].observedRecordCount = 1;
  assert.throws(() => validateChaosEvidence(wrong, expected, { now }), /wrong durable record count/u);

  const reusedIndependent = chaosEvidence();
  reusedIndependent.cases[1].operationId = reusedIndependent.cases[0].operationId;
  assert.throws(() => validateChaosEvidence(reusedIndependent, expected, { now }), /independent crash stages/u);

  const changedRecoveryOperation = chaosEvidence();
  changedRecoveryOperation.cases[3].operationId = "op-4";
  assert.throws(() => validateChaosEvidence(changedRecoveryOperation, expected, { now }), /exact operation interrupted after dispatch/u);

  const changedRecoveryRecord = chaosEvidence();
  changedRecoveryRecord.cases[3].durableRecordDigest = "a".repeat(64);
  assert.throws(() => validateChaosEvidence(changedRecoveryRecord, expected, { now }), /same durable operation record/u);

  const noRestart = chaosEvidence();
  noRestart.cases[3].agentdInstanceDigest = noRestart.cases[2].agentdInstanceDigest;
  assert.throws(() => validateChaosEvidence(noRestart, expected, { now }), /Agentd instance boundary/u);
});

test("authority evidence closes permission-revision and revocation semantics", () => {
  const receipt = {
    schema: "hepta.ui-control.authority-evidence-receipt.v1",
    status: "passed",
    ...expected,
    executedAt,
    rawEvidenceDigest: raw,
    executor: "identity qualification runner",
    cases: [
      {
        id: "permission-revision-change-observed",
        status: "passed",
        beforePermissionRevision: 4,
        afterPermissionRevision: 5,
        rawEvidenceDigest: raw,
      },
      {
        id: "permission-revocation-fences-mutation",
        status: "passed",
        postRevocationStatus: 403,
        operationCreated: false,
        rawEvidenceDigest: raw,
      },
      {
        id: "session-switch-requires-new-generation",
        status: "passed",
        beforeSessionIdDigest: "1".repeat(64),
        afterSessionIdDigest: "2".repeat(64),
        beforeConnectionGeneration: 10,
        afterConnectionGeneration: 11,
        rawEvidenceDigest: raw,
      },
    ],
  };
  assert.doesNotThrow(() => validateAuthorityEvidence(receipt, expected, { now }));
  receipt.cases = receipt.cases.filter(item => item.id !== "permission-revocation-fences-mutation");
  assert.throws(() => validateAuthorityEvidence(receipt, expected, { now }), /missing authority cases/u);
});

test("canonical evidence-library names cannot select weaker acceptance or operations validation", () => {
  assert.equal(validateIndependentAcceptance, validateIndependentAcceptanceMatrix);
  assert.equal(validateOperationalExercise, validateOperationalExerciseWithRolloutFence);

  assert.throws(
    () => validateIndependentAcceptance(statusOnlyAcceptanceReceipt(), expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_OBSERVATIONS",
  );
  assert.throws(
    () => validateOperationalExercise(statusOnlyOperationalReceipt(), expected, { now }),
    error => error?.code === "UI_CONTROL_OPERATIONS_CASES",
  );
});

test("security and signed production approval remain separate exact-subject gates", () => {
  const security = {
    schema: "hepta.ui-control.independent-security-review-receipt.v1",
    status: "passed",
    ...expected,
    executedAt,
    rawEvidenceDigest: raw,
    reviewer: {
      identity: "Security Reviewer",
      organization: "Independent Lab",
      independentOfImplementationAuthor: true,
    },
    controls: INDEPENDENT_SECURITY_CONTROLS.map(id => ({
      id,
      status: "passed",
      rawEvidenceDigest: raw,
    })),
    findings: { openCritical: 0, openHigh: 0, openMedium: 1, openLow: 2 },
  };
  assert.doesNotThrow(() => validateIndependentSecurityReview(security, expected, { now }));

  const failedControl = structuredClone(security);
  failedControl.controls.find(item => item.id === "browser-token-non-persistence").status = "failed";
  assert.throws(
    () => validateIndependentSecurityReview(failedControl, expected, { now }),
    /browser-token-non-persistence/u,
  );

  const scopeOnly = structuredClone(security);
  delete scopeOnly.controls;
  scopeOnly.scope = [...INDEPENDENT_SECURITY_CONTROLS];
  assert.throws(
    () => validateIndependentSecurityReview(scopeOnly, expected, { now }),
    /exactly the required control observations/u,
  );

  const evidenceDigests = {
    sourceHead: "1".repeat(64),
    mergeTree: "2".repeat(64),
    deploymentSecurity: "3".repeat(64),
    realBackend: "4".repeat(64),
    independentAcceptance: "5".repeat(64),
    independentSecurity: "6".repeat(64),
    operationalExercise: "7".repeat(64),
  };
  const approval = {
    schema: "hepta.ui-control.production-approval-receipt.v1",
    status: "approved",
    ...expected,
    approvedAt: executedAt,
    expiresAt: "2026-10-28T00:00:00Z",
    rawEvidenceDigest: raw,
    signature: { kind: "sigstore-bundle", digest: raw },
    approvals: [
      { role: "deployment-authority", identity: "Deployment owner" },
      { role: "release-authority", identity: "Release owner" },
      { role: "security-authority", identity: "Security owner" },
    ],
    evidenceDigests: { ...evidenceDigests },
  };
  assert.doesNotThrow(() => validateProductionApproval(approval, expected, evidenceDigests, { now }));
  approval.evidenceDigests.realBackend = "0".repeat(64);
  assert.throws(() => validateProductionApproval(approval, expected, evidenceDigests, { now }), /realBackend/u);
});

test("failure projection strips control characters and bounds output", () => {
  const projected = safeFailure(
    Object.assign(new Error("bad\nsecret\u0000text"), { code: "UI_CONTROL_TEST" }),
    "probe",
  );
  assert.equal(projected.code, "UI_CONTROL_TEST");
  assert.equal(projected.stage, "probe");
  assert.ok(!projected.message.includes("\n"));
  assert.ok(!projected.message.includes("\u0000"));
});

test("repository, deployment, and real-backend receipts remain exact-subject gates", () => {
  const source = {
    schema: "hepta.ui-control.qualification-receipt.v2",
    candidate: {
      kind: "source-head",
      evaluated: { sha: commit, tree },
      sourceHead: { sha: commit, tree },
      base: null,
    },
    verificationStages: {
      sourceTestsPassed: { state: "passed" },
      browserTestsPassed: { state: "passed" },
      mergeTreePassed: { state: "not-evaluated" },
    },
    artifacts: {
      dependencyLockSha256: "1".repeat(64),
      browserBuildManifestSha256: "2".repeat(64),
      statusManifestSha256: "3".repeat(64),
    },
    claims: {
      repositorySourceQualified: true,
      repositoryBrowserCompositionQualified: true,
      deterministicMergeQualified: false,
    },
  };
  assert.equal(
    validateRepositoryQualificationReceipt(source, "source-head", expected).browserBuildManifestSha256,
    "2".repeat(64),
  );

  const merge = structuredClone(source);
  merge.candidate.kind = "synthetic-merge";
  merge.candidate.evaluated = { sha: "e".repeat(40), tree: "f".repeat(40) };
  merge.candidate.base = { sha: "1".repeat(40), tree: "2".repeat(40) };
  merge.verificationStages.mergeTreePassed.state = "passed";
  merge.claims.deterministicMergeQualified = true;
  assert.doesNotThrow(() => validateRepositoryQualificationReceipt(merge, "synthetic-merge", expected));

  const deployment = deploymentReceipt();
  assert.equal(
    validateDeploymentSecurityReceipt(deployment, expected, { now }).policyProfile,
    UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  );

  const legacyPolicy = deploymentReceipt();
  delete legacyPolicy.policy;
  assert.throws(
    () => validateDeploymentSecurityReceipt(legacyPolicy, expected, { now }),
    /security-policy profile/u,
  );

  const weakTls = deploymentReceipt();
  weakTls.tls.protocol = "TLSv1.2";
  weakTls.tls.cipher = "ECDHE-RSA-AES256-SHA";
  assert.throws(
    () => validateDeploymentSecurityReceipt(weakTls, expected, { now }),
    /AEAD encryption/u,
  );

  deployment.checks = deployment.checks.slice(1);
  assert.throws(
    () => validateDeploymentSecurityReceipt(deployment, expected, { now }),
    /deployment checks/u,
  );

  const backend = backendReceipt();
  assert.doesNotThrow(() => validateRealBackendReceipt(backend, expected, { now }));

  const missingBinding = backendReceipt();
  delete missingBinding.operationBindings.duplicateOperation;
  assert.throws(
    () => validateRealBackendReceipt(missingBinding, expected, { now }),
    /operation binding is missing/u,
  );

  const reusedAudit = backendReceipt();
  reusedAudit.operationBindings.responseLossOperation.auditTraceIdSha256 =
    reusedAudit.operationBindings.duplicateOperation.auditTraceIdSha256;
  assert.throws(
    () => validateRealBackendReceipt(reusedAudit, expected, { now }),
    /reused one audit trace identity/u,
  );

  backend.cases = backend.cases.slice(1);
  assert.throws(
    () => validateRealBackendReceipt(backend, expected, { now }),
    /real-backend cases/u,
  );
});

test("all external qualification command modules parse under the supported Node runtime", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  for (const relativePath of [
    "qualification/ui-control/deployment-security.mjs",
    "qualification/ui-control/real-backend-contract.mjs",
    "qualification/ui-control/validate-external-evidence.mjs",
  ]) {
    execFileSync(process.execPath, ["--check", `${root}${relativePath}`], { stdio: "pipe" });
  }
});

test("external evidence schemas remain valid JSON contracts", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  for (const name of [
    "AGENTD_CHAOS_EVIDENCE_SCHEMA.json",
    "AUTHORITY_EVIDENCE_SCHEMA.json",
    "INDEPENDENT_ACCEPTANCE_SCHEMA.json",
    "INDEPENDENT_SECURITY_REVIEW_SCHEMA.json",
    "OPERATIONAL_EXERCISE_SCHEMA.json",
    "PRODUCTION_APPROVAL_SCHEMA.json",
    "EXTERNAL_EVIDENCE_BUNDLE_SCHEMA.json",
  ]) {
    const schema = JSON.parse(readFileSync(resolve(root, "qualification/ui-control", name), "utf8"));
    assert.equal(typeof schema.$id, "string");
    assert.equal(schema.type, "object");
  }
});
