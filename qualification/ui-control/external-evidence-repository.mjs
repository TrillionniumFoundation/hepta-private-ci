import {
  SHA1,
  SHA256,
  TERMINAL,
  assertEvidence,
  boundedText,
  exactSha,
  parseTimestamp,
} from "./external-evidence-primitives.mjs";
import { UI_CONTROL_CSRF_SUBSTITUTION_KIND } from "./deployment-asset-invariants.mjs";
import {
  UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
  assertTlsPolicy,
} from "./deployment-security-invariants.mjs";

export const REQUIRED_DEPLOYMENT_SECURITY_CHECKS = Object.freeze([
  "tls-1.2-or-newer-and-valid-certificate",
  "csp",
  "hsts",
  "no-store",
  "browser-isolation-headers",
  "bounded-csrf-bootstrap-substitution",
  "exact-deployed-asset-manifest",
  "csrf-before-connect",
  "cors-preflight-rejection",
  "cross-origin-rejection",
  "authenticated-connect",
  "secure-httponly-samesite-host-only-cookie",
  "authenticated-view",
  "mutation-csrf-precheck",
  "authenticated-close",
]);

export const REQUIRED_REAL_BACKEND_CASES = Object.freeze([
  "crash-restart-evidence",
  "permission-revision-and-revocation-evidence",
  "two-authenticated-identities",
  "concurrent-identical-operation",
  "changed-payload-conflict",
  "rejected-before-admission-no-record",
  "cross-identity-lookup-denied",
  "cross-identity-operation-rebind-conflict",
  "first-operation-terminal-lookup",
  "fresh-snapshot-before-next-mutation",
  "accepted-response-loss-lookup",
  "response-loss-terminal-lookup",
  "post-qualification-snapshot-continuity",
  "session-revocation",
  "session-switch-principal-continuity",
  "secondary-session-close",
]);

function assertExactStringSet(values, required, code, label) {
  assertEvidence(Array.isArray(values), code, `${label} must be an array`);
  assertEvidence(values.length === required.length, code, `${label} must contain exactly the required entries`);
  const observed = new Set();
  for (const value of values) {
    assertEvidence(typeof value === "string" && required.includes(value), code, `${label} contains an unexpected entry: ${String(value)}`);
    assertEvidence(!observed.has(value), code, `${label} contains a duplicate entry: ${value}`);
    observed.add(value);
  }
  assertEvidence(required.every(value => observed.has(value)), code, `${label} is incomplete`);
  return observed;
}

function validateOperationBinding(binding, label) {
  assertEvidence(
    binding && typeof binding === "object" && !Array.isArray(binding),
    "UI_CONTROL_BACKEND_OPERATION_BINDING",
    `${label} operation binding is missing`,
  );
  exactSha(binding.operationIdSha256, `${label}.operationIdSha256`, SHA256);
  exactSha(binding.semanticDigest, `${label}.semanticDigest`, SHA256);
  exactSha(binding.auditTraceIdSha256, `${label}.auditTraceIdSha256`, SHA256);
  return Object.freeze({
    operationIdSha256: binding.operationIdSha256,
    semanticDigest: binding.semanticDigest,
    auditTraceIdSha256: binding.auditTraceIdSha256,
  });
}

export function validateRepositoryQualificationReceipt(receipt, kind, expected) {
  assertEvidence(receipt && typeof receipt === "object" && !Array.isArray(receipt), "UI_CONTROL_QUALIFICATION_RECEIPT", "repository qualification receipt must be an object");
  assertEvidence(receipt.schema === "hepta.ui-control.qualification-receipt.v2", "UI_CONTROL_QUALIFICATION_SCHEMA", "unsupported repository qualification receipt schema");
  assertEvidence(["source-head", "synthetic-merge"].includes(kind), "UI_CONTROL_QUALIFICATION_KIND", `unsupported repository qualification kind: ${kind}`);
  assertEvidence(receipt.candidate?.kind === kind, "UI_CONTROL_QUALIFICATION_KIND", `expected ${kind} qualification receipt`);
  exactSha(receipt.candidate?.sourceHead?.sha, "candidate.sourceHead.sha", SHA1);
  exactSha(receipt.candidate?.sourceHead?.tree, "candidate.sourceHead.tree", SHA1);
  exactSha(receipt.candidate?.evaluated?.sha, "candidate.evaluated.sha", SHA1);
  exactSha(receipt.candidate?.evaluated?.tree, "candidate.evaluated.tree", SHA1);
  assertEvidence(receipt.candidate.sourceHead.sha === expected.candidateCommit, "UI_CONTROL_QUALIFICATION_COMMIT", `${kind} receipt is bound to another source commit`);
  assertEvidence(receipt.candidate.sourceHead.tree === expected.candidateTree, "UI_CONTROL_QUALIFICATION_TREE", `${kind} receipt is bound to another source tree`);
  if (kind === "source-head") {
    assertEvidence(receipt.candidate.evaluated.sha === expected.candidateCommit, "UI_CONTROL_SOURCE_RECEIPT_COMMIT", "source-head evaluated another commit");
    assertEvidence(receipt.candidate.evaluated.tree === expected.candidateTree, "UI_CONTROL_SOURCE_RECEIPT_TREE", "source-head evaluated another tree");
  } else {
    exactSha(receipt.candidate?.base?.sha, "candidate.base.sha", SHA1);
    exactSha(receipt.candidate?.base?.tree, "candidate.base.tree", SHA1);
    assertEvidence(receipt.candidate.evaluated.sha !== expected.candidateCommit, "UI_CONTROL_MERGE_RECEIPT_COMMIT", "synthetic-merge receipt did not evaluate a merge commit");
  }
  assertEvidence(receipt.verificationStages?.sourceTestsPassed?.state === "passed", "UI_CONTROL_QUALIFICATION_SOURCE", `${kind} source tests were not accepted`);
  assertEvidence(receipt.verificationStages?.browserTestsPassed?.state === "passed", "UI_CONTROL_QUALIFICATION_BROWSER", `${kind} browser tests were not accepted`);
  assertEvidence(receipt.claims?.repositorySourceQualified === true, "UI_CONTROL_QUALIFICATION_SOURCE_CLAIM", `${kind} source claim is not accepted`);
  assertEvidence(receipt.claims?.repositoryBrowserCompositionQualified === true, "UI_CONTROL_QUALIFICATION_BROWSER_CLAIM", `${kind} browser claim is not accepted`);
  if (kind === "synthetic-merge") {
    assertEvidence(receipt.verificationStages?.mergeTreePassed?.state === "passed", "UI_CONTROL_QUALIFICATION_MERGE", "synthetic merge was not accepted");
    assertEvidence(receipt.claims?.deterministicMergeQualified === true, "UI_CONTROL_QUALIFICATION_MERGE_CLAIM", "deterministic merge claim is not accepted");
  }
  exactSha(receipt.artifacts?.browserBuildManifestSha256, "artifacts.browserBuildManifestSha256", SHA256);
  exactSha(receipt.artifacts?.dependencyLockSha256, "artifacts.dependencyLockSha256", SHA256);
  exactSha(receipt.artifacts?.statusManifestSha256, "artifacts.statusManifestSha256", SHA256);
  return Object.freeze({
    evaluated: Object.freeze({ ...receipt.candidate.evaluated }),
    base: receipt.candidate.base ? Object.freeze({ ...receipt.candidate.base }) : null,
    browserBuildManifestSha256: receipt.artifacts.browserBuildManifestSha256,
  });
}

export function validateDeploymentSecurityReceipt(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  assertEvidence(receipt && typeof receipt === "object" && !Array.isArray(receipt), "UI_CONTROL_DEPLOYMENT_RECEIPT", "deployment-security receipt must be an object");
  assertEvidence(receipt.schema === "hepta.ui-control.deployment-security-receipt.v2", "UI_CONTROL_DEPLOYMENT_SCHEMA", "unsupported deployment-security receipt schema");
  assertEvidence(receipt.status === "passed", "UI_CONTROL_DEPLOYMENT_STATUS", "deployment-security receipt did not pass");
  exactSha(receipt.candidateCommit, "candidateCommit", SHA1);
  exactSha(receipt.candidateTree, "candidateTree", SHA1);
  exactSha(receipt.backendDeploymentDigest, "backendDeploymentDigest", SHA256);
  assertEvidence(receipt.candidateCommit === expected.candidateCommit, "UI_CONTROL_DEPLOYMENT_COMMIT", "deployment receipt is bound to another candidate commit");
  assertEvidence(receipt.candidateTree === expected.candidateTree, "UI_CONTROL_DEPLOYMENT_TREE", "deployment receipt is bound to another candidate tree");
  assertEvidence(receipt.backendDeploymentDigest === expected.backendDeploymentDigest, "UI_CONTROL_DEPLOYMENT_DIGEST", "deployment receipt is bound to another deployment");
  parseTimestamp(receipt.deployment?.observedAt, "deployment observedAt", now, options.maxAgeMs ?? 30 * 24 * 60 * 60_000);
  assertEvidence(
    receipt.policy?.profile === UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
    "UI_CONTROL_DEPLOYMENT_POLICY_PROFILE",
    "deployment receipt is not bound to the required security-policy profile",
  );
  assertEvidence(
    receipt.policy?.minimumHstsMaxAgeSeconds === UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
    "UI_CONTROL_DEPLOYMENT_POLICY_HSTS",
    "deployment receipt uses another minimum HSTS age",
  );
  assertEvidence(
    receipt.policy?.minimumCertificateLifetimeSeconds === UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
    "UI_CONTROL_DEPLOYMENT_POLICY_CERTIFICATE",
    "deployment receipt uses another minimum certificate lifetime",
  );
  assertEvidence(
    receipt.tls?.profile === UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
    "UI_CONTROL_DEPLOYMENT_TLS_PROFILE",
    "deployment TLS observation is not bound to the required security-policy profile",
  );
  const tls = assertTlsPolicy(receipt.tls, {
    now,
    minimumCertificateLifetimeSeconds: UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  });
  exactSha(receipt.source?.browserBuildManifestSha256, "source.browserBuildManifestSha256", SHA256);
  assertEvidence(receipt.claims?.deployedSecurityObserved === true, "UI_CONTROL_DEPLOYMENT_CLAIM", "deployed security was not accepted");
  assertEvidence(receipt.claims?.exactCandidateAssetsObserved === true, "UI_CONTROL_DEPLOYMENT_ASSET_CLAIM", "exact candidate assets were not observed");
  assertEvidence(Number.isInteger(receipt.assets?.verifiedAssetCount) && receipt.assets.verifiedAssetCount > 1, "UI_CONTROL_DEPLOYMENT_ASSETS", "the deployed browser asset set was not fully verified");
  assertEvidence(
    Array.isArray(receipt.assets?.runtimeSubstitutions) &&
      receipt.assets.runtimeSubstitutions.length === 1 &&
      receipt.assets.runtimeSubstitutions[0]?.path === "index.html" &&
      receipt.assets.runtimeSubstitutions[0]?.kind === UI_CONTROL_CSRF_SUBSTITUTION_KIND,
    "UI_CONTROL_DEPLOYMENT_SUBSTITUTION",
    "deployment receipt does not bind the sole allowed CSRF bootstrap substitution",
  );
  assertExactStringSet(receipt.checks, REQUIRED_DEPLOYMENT_SECURITY_CHECKS, "UI_CONTROL_DEPLOYMENT_CHECKS", "deployment checks");
  return Object.freeze({
    browserBuildManifestSha256: receipt.source.browserBuildManifestSha256,
    policyProfile: receipt.policy.profile,
    tls,
  });
}

export function validateRealBackendReceipt(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  assertEvidence(receipt && typeof receipt === "object" && !Array.isArray(receipt), "UI_CONTROL_BACKEND_RECEIPT", "real-backend receipt must be an object");
  assertEvidence(receipt.schema === "hepta.ui-control.real-backend-receipt.v2", "UI_CONTROL_BACKEND_SCHEMA", "unsupported real-backend receipt schema");
  assertEvidence(receipt.status === "passed", "UI_CONTROL_BACKEND_STATUS", "real-backend receipt did not pass");
  exactSha(receipt.candidateCommit, "candidateCommit", SHA1);
  exactSha(receipt.candidateTree, "candidateTree", SHA1);
  exactSha(receipt.backendDeploymentDigest, "backendDeploymentDigest", SHA256);
  assertEvidence(receipt.candidateCommit === expected.candidateCommit, "UI_CONTROL_BACKEND_COMMIT", "real-backend receipt is bound to another candidate commit");
  assertEvidence(receipt.candidateTree === expected.candidateTree, "UI_CONTROL_BACKEND_TREE", "real-backend receipt is bound to another candidate tree");
  assertEvidence(receipt.backendDeploymentDigest === expected.backendDeploymentDigest, "UI_CONTROL_BACKEND_DEPLOYMENT", "real-backend receipt is bound to another deployment");
  parseTimestamp(receipt.backend?.observedAt, "backend observedAt", now, options.maxAgeMs ?? 30 * 24 * 60 * 60_000);
  const primaryIdentity = boundedText(receipt.backend?.primaryIdentity, "backend.primaryIdentity", 192);
  const secondaryIdentity = boundedText(receipt.backend?.secondaryIdentity, "backend.secondaryIdentity", 192);
  assertEvidence(primaryIdentity !== secondaryIdentity, "UI_CONTROL_BACKEND_IDENTITY_ISOLATION", "real-backend receipt reused one identity for both qualification principals");
  assertEvidence(Number.isSafeInteger(receipt.backend?.runtimeGeneration) && receipt.backend.runtimeGeneration > 0, "UI_CONTROL_BACKEND_GENERATION", "real-backend runtime generation is invalid");
  assertEvidence(Number.isSafeInteger(receipt.backend?.runtimeRevision) && receipt.backend.runtimeRevision > 0, "UI_CONTROL_BACKEND_REVISION", "real-backend runtime revision is invalid");
  assertExactStringSet(receipt.cases, REQUIRED_REAL_BACKEND_CASES, "UI_CONTROL_BACKEND_CASES", "real-backend cases");
  assertEvidence(TERMINAL.has(receipt.terminalObservations?.duplicateOperation), "UI_CONTROL_BACKEND_TERMINAL", "duplicate operation lacks a terminal observation");
  assertEvidence(TERMINAL.has(receipt.terminalObservations?.responseLossOperation), "UI_CONTROL_BACKEND_TERMINAL", "response-loss operation lacks a terminal observation");

  const duplicateOperation = validateOperationBinding(
    receipt.operationBindings?.duplicateOperation,
    "operationBindings.duplicateOperation",
  );
  const responseLossOperation = validateOperationBinding(
    receipt.operationBindings?.responseLossOperation,
    "operationBindings.responseLossOperation",
  );
  assertEvidence(
    duplicateOperation.operationIdSha256 !== responseLossOperation.operationIdSha256,
    "UI_CONTROL_BACKEND_OPERATION_REUSE",
    "real-backend receipt reused one operation identity for both mutation scenarios",
  );
  assertEvidence(
    duplicateOperation.semanticDigest !== responseLossOperation.semanticDigest,
    "UI_CONTROL_BACKEND_SEMANTIC_REUSE",
    "real-backend receipt reused one semantic intent for both mutation scenarios",
  );
  assertEvidence(
    duplicateOperation.auditTraceIdSha256 !== responseLossOperation.auditTraceIdSha256,
    "UI_CONTROL_BACKEND_AUDIT_REUSE",
    "real-backend receipt reused one audit trace identity for both mutation scenarios",
  );

  exactSha(receipt.evidence?.chaosEvidenceSha256, "evidence.chaosEvidenceSha256", SHA256);
  exactSha(receipt.evidence?.chaosRawEvidenceDigest, "evidence.chaosRawEvidenceDigest", SHA256);
  exactSha(receipt.evidence?.authorityEvidenceSha256, "evidence.authorityEvidenceSha256", SHA256);
  for (const claim of [
    "realBackendSemanticsQualified",
    "durableIdempotencyQualified",
    "crashRestartQualified",
    "permissionRevisionAndRevocationQualified",
    "sessionSwitchQualified",
  ]) {
    assertEvidence(receipt.claims?.[claim] === true, "UI_CONTROL_BACKEND_CLAIM", `real-backend claim is not accepted: ${claim}`);
  }
  return Object.freeze({
    cases: Object.freeze([...receipt.cases]),
    operationBindings: Object.freeze({ duplicateOperation, responseLossOperation }),
  });
}
