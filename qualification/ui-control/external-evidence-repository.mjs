import {
  SHA1,
  SHA256,
  assertEvidence,
  exactSha,
  parseTimestamp,
} from "./external-evidence-primitives.mjs";

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
  exactSha(receipt.source?.browserBuildManifestSha256, "source.browserBuildManifestSha256", SHA256);
  assertEvidence(receipt.claims?.deployedSecurityObserved === true, "UI_CONTROL_DEPLOYMENT_CLAIM", "deployed security was not accepted");
  assertEvidence(receipt.claims?.exactCandidateAssetsObserved === true, "UI_CONTROL_DEPLOYMENT_ASSET_CLAIM", "exact candidate assets were not observed");
  assertEvidence(Number.isInteger(receipt.assets?.verifiedAssetCount) && receipt.assets.verifiedAssetCount > 0, "UI_CONTROL_DEPLOYMENT_ASSETS", "no deployed assets were verified");
  return Object.freeze({ browserBuildManifestSha256: receipt.source.browserBuildManifestSha256 });
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
  for (const claim of [
    "realBackendSemanticsQualified",
    "durableIdempotencyQualified",
    "crashRestartQualified",
    "permissionRevisionAndRevocationQualified",
    "sessionSwitchQualified",
  ]) {
    assertEvidence(receipt.claims?.[claim] === true, "UI_CONTROL_BACKEND_CLAIM", `real-backend claim is not accepted: ${claim}`);
  }
  return Object.freeze({ cases: Object.freeze([...(receipt.cases ?? [])]) });
}
