const STAGE_CLAIMS = Object.freeze({
  "deployment-identity": Object.freeze([]),
  "main-ancestry": Object.freeze([]),
  "repository-source-head": Object.freeze([
    "repositorySourceQualified",
    "repositoryBrowserCompositionQualified",
  ]),
  "repository-synthetic-merge": Object.freeze([
    "deterministicMergeQualified",
  ]),
  "deployment-security": Object.freeze([
    "deployedSecurityObserved",
    "exactCandidateAssetsObserved",
  ]),
  "real-backend": Object.freeze([
    "realBackendSemanticsQualified",
    "durableCrashRestartQualified",
    "identityPermissionAndSessionSwitchQualified",
  ]),
  "independent-accessibility-and-operator-acceptance": Object.freeze([
    "independentAccessibilityAndOperatorAcceptanceSigned",
  ]),
  "independent-security-review": Object.freeze([
    "independentSecurityReviewPassed",
  ]),
  "operational-exercise": Object.freeze([
    "rollbackDisasterRecoveryMonitoringAndRedactionExercised",
  ]),
  "production-approval": Object.freeze([
    "productionDeploymentApproved",
    "releaseAuthorized",
  ]),
});

export const EXTERNAL_EVIDENCE_STAGE_ORDER = Object.freeze(Object.keys(STAGE_CLAIMS));
export const EXTERNAL_EVIDENCE_CLAIM_ORDER = Object.freeze([
  "repositorySourceQualified",
  "repositoryBrowserCompositionQualified",
  "deterministicMergeQualified",
  "deployedSecurityObserved",
  "exactCandidateAssetsObserved",
  "realBackendSemanticsQualified",
  "durableCrashRestartQualified",
  "identityPermissionAndSessionSwitchQualified",
  "independentAccessibilityAndOperatorAcceptanceSigned",
  "independentSecurityReviewPassed",
  "rollbackDisasterRecoveryMonitoringAndRedactionExercised",
  "productionDeploymentApproved",
  "releaseAuthorized",
]);

const SHA256 = /^[0-9a-f]{64}$/u;
const FINAL_OUTCOMES = new Set(["passed", "failed", "not-required"]);
const RELEASE_PREREQUISITES = Object.freeze(
  EXTERNAL_EVIDENCE_STAGE_ORDER.filter(stage => stage !== "production-approval"),
);
const NON_EVIDENCE_STAGES = new Set(["deployment-identity", "main-ancestry"]);

function ledgerError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function freshResult() {
  return {
    observedOutcome: "not-observed",
    acceptedEvidence: false,
    evidenceDigest: null,
  };
}

export function createExternalEvidenceStageLedger() {
  const results = Object.fromEntries(
    EXTERNAL_EVIDENCE_STAGE_ORDER.map(stage => [stage, freshResult()]),
  );
  let activeStage = null;

  const requireStage = stage => {
    if (!Object.hasOwn(results, stage)) {
      throw ledgerError("UI_CONTROL_EVIDENCE_LEDGER_STAGE", `unknown external-evidence stage: ${stage}`);
    }
    return results[stage];
  };

  const requireActive = stage => {
    const current = requireStage(stage);
    if (activeStage !== stage) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_TRANSITION",
        `external-evidence stage is not active: ${stage}`,
      );
    }
    return current;
  };

  const begin = stage => {
    const current = requireStage(stage);
    if (activeStage !== null) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_TRANSITION",
        `external-evidence stage is already active: ${activeStage}`,
      );
    }
    if (FINAL_OUTCOMES.has(current.observedOutcome)) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_TRANSITION",
        `external-evidence stage is already final: ${stage}`,
      );
    }
    activeStage = stage;
  };

  const attachEvidence = (stage, digest) => {
    const current = requireActive(stage);
    if (typeof digest !== "string" || !SHA256.test(digest)) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_DIGEST",
        `external-evidence digest is invalid for stage: ${stage}`,
      );
    }
    if (current.evidenceDigest !== null && current.evidenceDigest !== digest) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_DIGEST",
        `external-evidence digest changed within stage: ${stage}`,
      );
    }
    results[stage] = { ...current, evidenceDigest: digest };
  };

  const accept = stage => {
    const current = requireActive(stage);
    if (!NON_EVIDENCE_STAGES.has(stage) && current.evidenceDigest === null) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_DIGEST_REQUIRED",
        `external-evidence stage cannot be accepted without an exact receipt digest: ${stage}`,
      );
    }
    results[stage] = {
      ...current,
      observedOutcome: "passed",
      acceptedEvidence: true,
    };
    activeStage = null;
  };

  const skip = (stage, reason = "not-required") => {
    const current = requireStage(stage);
    if (activeStage !== null || FINAL_OUTCOMES.has(current.observedOutcome)) {
      throw ledgerError(
        "UI_CONTROL_EVIDENCE_LEDGER_TRANSITION",
        `external-evidence stage cannot be skipped: ${stage}`,
      );
    }
    results[stage] = {
      ...current,
      observedOutcome: "not-required",
      acceptedEvidence: false,
      reason,
    };
  };

  const fail = (stage, failureCode) => {
    const current = requireStage(stage);
    if (current.acceptedEvidence || current.observedOutcome === "passed") return;
    if (current.observedOutcome === "not-required") return;
    results[stage] = {
      ...current,
      observedOutcome: "failed",
      acceptedEvidence: false,
      failureCode,
    };
    if (activeStage === stage) activeStage = null;
  };

  const projectClaims = suppressRelease => {
    const projected = Object.fromEntries(
      EXTERNAL_EVIDENCE_CLAIM_ORDER.map(claim => [claim, false]),
    );
    for (const stage of EXTERNAL_EVIDENCE_STAGE_ORDER) {
      if (!results[stage].acceptedEvidence) continue;
      for (const claim of STAGE_CLAIMS[stage]) projected[claim] = true;
    }
    const releasePrerequisitesAccepted = RELEASE_PREREQUISITES.every(
      stage => results[stage].acceptedEvidence,
    );
    if (suppressRelease || !releasePrerequisitesAccepted) {
      projected.productionDeploymentApproved = false;
      projected.releaseAuthorized = false;
    }
    return projected;
  };

  const claims = () => projectClaims(false);
  const failureClaims = () => projectClaims(true);

  const snapshot = () => Object.fromEntries(
    EXTERNAL_EVIDENCE_STAGE_ORDER.map(stage => [stage, { ...results[stage] }]),
  );

  return Object.freeze({
    begin,
    attachEvidence,
    accept,
    skip,
    fail,
    claims,
    failureClaims,
    snapshot,
  });
}
