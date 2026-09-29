import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  INDEPENDENT_SECURITY_CONTROLS,
  REQUIRED_DEPLOYMENT_SECURITY_CHECKS,
  REQUIRED_OPERATIONAL_EXERCISE_CASES,
  REQUIRED_REAL_BACKEND_CASES,
  deploymentSubject,
  sha256,
} from "../../../qualification/ui-control/external-evidence-lib.mjs";
import { UI_CONTROL_CSRF_SUBSTITUTION_KIND } from "../../../qualification/ui-control/deployment-asset-invariants.mjs";
import {
  UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
} from "../../../qualification/ui-control/deployment-security-invariants.mjs";

const fingerprint = Array.from({ length: 32 }, () => "AA").join(":");

function acceptanceObservations(rawEvidenceDigest) {
  const observation = ({ id, modality, browser, os, flows, assistiveTechnology }) => ({
    id,
    modality,
    browser,
    os,
    flows,
    ...(assistiveTechnology ? { assistiveTechnology } : {}),
    result: "pass",
    rawEvidenceDigest,
  });
  return [
    observation({
      id: "chrome-operator",
      modality: "browser-operator",
      browser: { name: "Chrome", version: "154" },
      os: "Windows",
      flows: ["read-runtime-view", "start-confirmation", "reconcile-confirmation"],
    }),
    observation({
      id: "firefox-operator",
      modality: "browser-operator",
      browser: { name: "Firefox", version: "150" },
      os: "Linux",
      flows: ["read-runtime-view", "stop-confirmation", "stale-confirmation-rejected"],
    }),
    observation({
      id: "safari-operator",
      modality: "browser-operator",
      browser: { name: "Safari", version: "20" },
      os: "macOS",
      flows: ["read-runtime-view", "indeterminate-recovery-by-lookup"],
    }),
    observation({
      id: "chrome-keyboard",
      modality: "keyboard-only",
      browser: { name: "Chrome", version: "154" },
      os: "Windows",
      flows: ["start-confirmation", "reconcile-confirmation", "keyboard-focus-restoration"],
    }),
    observation({
      id: "firefox-keyboard",
      modality: "keyboard-only",
      browser: { name: "Firefox", version: "150" },
      os: "Linux",
      flows: ["stop-confirmation", "stale-confirmation-rejected", "keyboard-focus-restoration"],
    }),
    observation({
      id: "safari-keyboard",
      modality: "keyboard-only",
      browser: { name: "Safari", version: "20" },
      os: "macOS",
      flows: ["read-runtime-view", "indeterminate-recovery-by-lookup", "keyboard-focus-restoration"],
    }),
    observation({
      id: "nvda-chrome",
      modality: "screen-reader",
      browser: { name: "Chrome", version: "154" },
      os: "Windows",
      assistiveTechnology: { name: "NVDA", version: "2026.2" },
      flows: [
        "read-runtime-view",
        "indeterminate-recovery-by-lookup",
        "terminal-storage-failure-visible",
      ],
    }),
    observation({
      id: "voiceover-safari",
      modality: "screen-reader",
      browser: { name: "Safari", version: "20" },
      os: "macOS",
      assistiveTechnology: { name: "VoiceOver", version: "20" },
      flows: [
        "read-runtime-view",
        "indeterminate-recovery-by-lookup",
        "terminal-storage-failure-visible",
      ],
    }),
  ];
}

function operationalCases(manifestDigest, rawEvidenceDigest) {
  const cases = [
    {
      id: "rollback",
      status: "passed",
      rollbackBuildManifestSha256: "6".repeat(64),
      restoredBrowserBuildManifestSha256: manifestDigest,
      mutationFenceObserved: true,
      operationLedgerContinuity: true,
      unresolvedOperations: 0,
      duplicateSideEffects: 0,
      rawEvidenceDigest,
    },
    {
      id: "disaster-recovery",
      status: "passed",
      objectiveRpoSeconds: 300,
      observedRpoSeconds: 12,
      objectiveRtoSeconds: 1800,
      observedRtoSeconds: 420,
      operationLedgerRestored: true,
      auditLinkageRestored: true,
      terminalLookupContinuity: true,
      unresolvedOperations: 0,
      duplicateSideEffects: 0,
      rawEvidenceDigest,
    },
    {
      id: "alert-routing",
      status: "passed",
      alertRuleSha256: "7".repeat(64),
      routeConfigurationSha256: "8".repeat(64),
      objectiveAcknowledgementSeconds: 900,
      observedAcknowledgementSeconds: 42,
      alertTriggered: true,
      routeMatched: true,
      acknowledged: true,
      escalationPolicyVerified: true,
      rawEvidenceDigest,
    },
    {
      id: "log-redaction",
      status: "passed",
      logCorpusSha256: "9".repeat(64),
      secretCanaryCount: 4,
      secretCanaryMatches: 0,
      correlationCanaryCount: 6,
      fullIdentifierMatches: 0,
      redactedCorrelationMatches: 6,
      credentialMatches: 0,
      rawEvidenceDigest,
    },
    {
      id: "credential-rotation",
      status: "passed",
      oldCredentialFingerprintSha256: "a".repeat(64),
      newCredentialFingerprintSha256: "b".repeat(64),
      activeOldCredentials: 0,
      oldCredentialRejectedStatus: 403,
      oldCredentialOperationCreated: false,
      newCredentialAuthenticated: true,
      permissionRevisionAdvanced: true,
      postRotationLookupSucceeded: true,
      rawEvidenceDigest,
    },
    {
      id: "mixed-version-mutation-fence",
      status: "passed",
      oldMutationSessionsRevoked: true,
      cachedHtmlInvalidated: true,
      activeLegacyMutationSessions: 0,
      staleClientMutationStatus: 403,
      staleClientOperationCreated: false,
      freshClientBuildManifestSha256: manifestDigest,
      rawEvidenceDigest,
    },
  ];
  assert.deepEqual(cases.map(item => item.id), [...REQUIRED_OPERATIONAL_EXERCISE_CASES]);
  return cases;
}

test("bundle validation accepts one exact, semantically complete evidence set on main", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const directory = mkdtempSync(join(tmpdir(), "ui-control-external-accepted-"));
  try {
    execFileSync("git", ["init", "-q"], { cwd: directory });
    execFileSync("git", ["config", "user.name", "ui.control test"], { cwd: directory });
    execFileSync("git", ["config", "user.email", "ui-control-test@example.invalid"], { cwd: directory });
    writeFileSync(join(directory, "marker.txt"), "candidate\n");
    execFileSync("git", ["add", "marker.txt"], { cwd: directory });
    execFileSync("git", ["commit", "-q", "-m", "candidate"], { cwd: directory });
    const candidateCommit = execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: directory,
      encoding: "utf8",
    }).trim();
    const candidateTree = execFileSync("git", ["rev-parse", "HEAD^{tree}"], {
      cwd: directory,
      encoding: "utf8",
    }).trim();
    execFileSync("git", ["update-ref", "refs/remotes/origin/main", candidateCommit], { cwd: directory });

    const selected = deploymentSubject("https://control.example.test/console", "release-accepted");
    const observedAt = new Date().toISOString();
    const approvalExpiry = new Date(Date.now() + 24 * 60 * 60_000).toISOString();
    const certificateExpiry = new Date(Date.now() + 365 * 24 * 60 * 60_000).toISOString();
    const manifestDigest = "8".repeat(64);
    const evidenceRaw = "9".repeat(64);
    const writeReceipt = (name, value) => {
      const text = `${JSON.stringify(value, null, 2)}\n`;
      const path = join(directory, name);
      writeFileSync(path, text);
      return { path, digest: sha256(text) };
    };

    const stages = {
      sourceTestsPassed: { state: "passed" },
      browserTestsPassed: { state: "passed" },
      mergeTreePassed: { state: "not-evaluated" },
    };
    const artifacts = {
      dependencyLockSha256: "1".repeat(64),
      browserBuildManifestSha256: manifestDigest,
      statusManifestSha256: "2".repeat(64),
    };
    const sourceReceipt = writeReceipt("source.json", {
      schema: "hepta.ui-control.qualification-receipt.v2",
      candidate: {
        kind: "source-head",
        evaluated: { sha: candidateCommit, tree: candidateTree },
        sourceHead: { sha: candidateCommit, tree: candidateTree },
        base: null,
      },
      verificationStages: stages,
      artifacts,
      claims: {
        repositorySourceQualified: true,
        repositoryBrowserCompositionQualified: true,
        deterministicMergeQualified: false,
      },
    });
    const mergeReceipt = writeReceipt("merge.json", {
      schema: "hepta.ui-control.qualification-receipt.v2",
      candidate: {
        kind: "synthetic-merge",
        evaluated: { sha: "a".repeat(40), tree: "b".repeat(40) },
        sourceHead: { sha: candidateCommit, tree: candidateTree },
        base: { sha: "c".repeat(40), tree: "d".repeat(40) },
      },
      verificationStages: { ...stages, mergeTreePassed: { state: "passed" } },
      artifacts,
      claims: {
        repositorySourceQualified: true,
        repositoryBrowserCompositionQualified: true,
        deterministicMergeQualified: true,
      },
    });
    const deploymentReceipt = writeReceipt("deployment.json", {
      schema: "hepta.ui-control.deployment-security-receipt.v2",
      status: "passed",
      candidateCommit,
      candidateTree,
      backendDeploymentDigest: selected.digest,
      source: {
        sha: candidateCommit,
        tree: candidateTree,
        browserBuildManifestSha256: manifestDigest,
      },
      deployment: { ...selected.subject, observedAt },
      policy: {
        profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
        minimumHstsMaxAgeSeconds: UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
        minimumCertificateLifetimeSeconds: UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
      },
      tls: {
        profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
        protocol: "TLSv1.3",
        cipher: "TLS_AES_256_GCM_SHA384",
        certificateValidTo: certificateExpiry,
        certificateFingerprint256: fingerprint,
      },
      assets: {
        verifiedAssetCount: 19,
        runtimeSubstitutions: [
          { path: "index.html", kind: UI_CONTROL_CSRF_SUBSTITUTION_KIND },
        ],
      },
      checks: [...REQUIRED_DEPLOYMENT_SECURITY_CHECKS],
      claims: { deployedSecurityObserved: true, exactCandidateAssetsObserved: true },
    });
    const backendReceipt = writeReceipt("backend.json", {
      schema: "hepta.ui-control.real-backend-receipt.v2",
      status: "passed",
      candidateCommit,
      candidateTree,
      backendDeploymentDigest: selected.digest,
      backend: {
        ...selected.subject,
        observedAt,
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
    });
    const common = {
      status: "passed",
      candidateCommit,
      candidateTree,
      backendDeploymentDigest: selected.digest,
      executedAt: observedAt,
      rawEvidenceDigest: evidenceRaw,
    };
    const acceptanceReceipt = writeReceipt("acceptance.json", {
      schema: "hepta.ui-control.independent-acceptance-receipt.v2",
      ...common,
      verifier: {
        identity: "Independent verifier",
        organization: "Independent lab",
        independentOfImplementationAuthor: true,
      },
      observations: acceptanceObservations(evidenceRaw),
    });
    const securityReceipt = writeReceipt("security.json", {
      schema: "hepta.ui-control.independent-security-review-receipt.v1",
      ...common,
      reviewer: {
        identity: "Security reviewer",
        organization: "Independent lab",
        independentOfImplementationAuthor: true,
      },
      controls: INDEPENDENT_SECURITY_CONTROLS.map(id => ({
        id,
        status: "passed",
        rawEvidenceDigest: evidenceRaw,
      })),
      findings: { openCritical: 0, openHigh: 0, openMedium: 0, openLow: 1 },
    });
    const operationsReceipt = writeReceipt("operations.json", {
      schema: "hepta.ui-control.operational-exercise-receipt.v1",
      ...common,
      cases: operationalCases(manifestDigest, evidenceRaw),
    });
    const approvalEvidenceDigests = {
      sourceHead: sourceReceipt.digest,
      mergeTree: mergeReceipt.digest,
      deploymentSecurity: deploymentReceipt.digest,
      realBackend: backendReceipt.digest,
      independentAcceptance: acceptanceReceipt.digest,
      independentSecurity: securityReceipt.digest,
      operationalExercise: operationsReceipt.digest,
    };
    const approvalReceipt = writeReceipt("approval.json", {
      schema: "hepta.ui-control.production-approval-receipt.v1",
      status: "approved",
      candidateCommit,
      candidateTree,
      backendDeploymentDigest: selected.digest,
      approvedAt: observedAt,
      expiresAt: approvalExpiry,
      rawEvidenceDigest: evidenceRaw,
      signature: { kind: "sigstore-bundle", digest: evidenceRaw },
      approvals: [
        { role: "deployment-authority", identity: "Deployment authority", approvedAt: observedAt },
        { role: "release-authority", identity: "Release authority", approvedAt: observedAt },
        { role: "security-authority", identity: "Security authority", approvedAt: observedAt },
      ],
      evidenceDigests: approvalEvidenceDigests,
    });

    const output = join(directory, "bundle.json");
    const result = spawnSync(
      process.execPath,
      [resolve(root, "qualification/ui-control/validate-external-evidence.mjs"), output],
      {
        cwd: directory,
        env: {
          ...process.env,
          HEPTA_UI_CONTROL_BASE_URL: "https://control.example.test/console",
          HEPTA_UI_CONTROL_DEPLOYMENT_ID: "release-accepted",
          UI_CONTROL_SOURCE_HEAD_RECEIPT: sourceReceipt.path,
          UI_CONTROL_MERGE_TREE_RECEIPT: mergeReceipt.path,
          UI_CONTROL_DEPLOYMENT_SECURITY_RECEIPT: deploymentReceipt.path,
          UI_CONTROL_REAL_BACKEND_RECEIPT: backendReceipt.path,
          UI_CONTROL_INDEPENDENT_ACCEPTANCE_RECEIPT: acceptanceReceipt.path,
          UI_CONTROL_INDEPENDENT_SECURITY_RECEIPT: securityReceipt.path,
          UI_CONTROL_OPERATIONAL_EXERCISE_RECEIPT: operationsReceipt.path,
          UI_CONTROL_PRODUCTION_APPROVAL_RECEIPT: approvalReceipt.path,
        },
        encoding: "utf8",
      },
    );
    assert.equal(result.status, 0, result.stderr || result.stdout);
    const bundle = JSON.parse(readFileSync(output, "utf8"));
    assert.equal(bundle.status, "accepted");
    assert.equal(bundle.claims.productionDeploymentApproved, true);
    assert.equal(bundle.claims.releaseAuthorized, true);
    assert.equal(bundle.claims.evidenceChronologyBound, true);
    assert.equal(bundle.stageResults["main-ancestry"].acceptedEvidence, true);
    assert.equal(bundle.stageResults["production-approval"].observedOutcome, "passed");
    assert.equal(bundle.stageResults["production-approval"].acceptedEvidence, true);
    assert.deepEqual(bundle.evidenceDigests, {
      ...approvalEvidenceDigests,
      productionApproval: approvalReceipt.digest,
    });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
