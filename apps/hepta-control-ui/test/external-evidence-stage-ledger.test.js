import test from "node:test";
import assert from "node:assert/strict";
import {
  createExternalEvidenceStageLedger,
  EXTERNAL_EVIDENCE_STAGE_ORDER,
} from "../../../qualification/ui-control/external-evidence-stage-ledger.mjs";

const digest = character => character.repeat(64);

test("external evidence stage results preserve accepted earlier evidence after a later failure", () => {
  const ledger = createExternalEvidenceStageLedger();

  ledger.begin("deployment-identity");
  ledger.accept("deployment-identity");
  ledger.skip("main-ancestry", "not-required-by-test");

  ledger.begin("repository-source-head");
  ledger.attachEvidence("repository-source-head", digest("1"));
  ledger.accept("repository-source-head");

  ledger.begin("repository-synthetic-merge");
  ledger.attachEvidence("repository-synthetic-merge", digest("2"));
  ledger.accept("repository-synthetic-merge");

  ledger.begin("deployment-security");
  ledger.attachEvidence("deployment-security", digest("3"));
  ledger.fail("deployment-security", "UI_CONTROL_DEPLOYMENT_STATUS");

  const stages = ledger.snapshot();
  assert.deepEqual(Object.keys(stages), [...EXTERNAL_EVIDENCE_STAGE_ORDER]);
  assert.deepEqual(stages["repository-source-head"], {
    observedOutcome: "passed",
    acceptedEvidence: true,
    evidenceDigest: digest("1"),
  });
  assert.deepEqual(stages["repository-synthetic-merge"], {
    observedOutcome: "passed",
    acceptedEvidence: true,
    evidenceDigest: digest("2"),
  });
  assert.deepEqual(stages["deployment-security"], {
    observedOutcome: "failed",
    acceptedEvidence: false,
    evidenceDigest: digest("3"),
    failureCode: "UI_CONTROL_DEPLOYMENT_STATUS",
  });

  assert.deepEqual(ledger.claims(), {
    repositorySourceQualified: true,
    repositoryBrowserCompositionQualified: true,
    deterministicMergeQualified: true,
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
  });
});

test("accepted stage evidence is monotone and cannot be erased by failure handling", () => {
  const ledger = createExternalEvidenceStageLedger();
  ledger.begin("repository-source-head");
  ledger.attachEvidence("repository-source-head", digest("a"));
  ledger.accept("repository-source-head");

  ledger.fail("repository-source-head", "UI_CONTROL_LATE_FAILURE");
  assert.deepEqual(ledger.snapshot()["repository-source-head"], {
    observedOutcome: "passed",
    acceptedEvidence: true,
    evidenceDigest: digest("a"),
  });
  assert.throws(
    () => ledger.begin("repository-source-head"),
    error => error?.code === "UI_CONTROL_EVIDENCE_LEDGER_TRANSITION",
  );
});

test("production approval cannot authorize release while any prerequisite stage is absent", () => {
  const ledger = createExternalEvidenceStageLedger();
  ledger.begin("production-approval");
  ledger.attachEvidence("production-approval", digest("f"));
  ledger.accept("production-approval");
  const claims = ledger.claims();
  assert.equal(claims.productionDeploymentApproved, false);
  assert.equal(claims.releaseAuthorized, false);
  assert.equal(ledger.snapshot()["production-approval"].acceptedEvidence, true);
});

test("evidence-bearing stages cannot be accepted without an exact digest", () => {
  const ledger = createExternalEvidenceStageLedger();
  ledger.begin("real-backend");
  assert.throws(
    () => ledger.accept("real-backend"),
    error => error?.code === "UI_CONTROL_EVIDENCE_LEDGER_DIGEST_REQUIRED",
  );
  ledger.attachEvidence("real-backend", digest("b"));
  ledger.accept("real-backend");
  assert.equal(ledger.snapshot()["real-backend"].acceptedEvidence, true);
});

test("failed bundle projection suppresses release after every stage was accepted", () => {
  const ledger = createExternalEvidenceStageLedger();
  for (const [index, stage] of EXTERNAL_EVIDENCE_STAGE_ORDER.entries()) {
    ledger.begin(stage);
    if (!["deployment-identity", "main-ancestry"].includes(stage)) {
      ledger.attachEvidence(stage, String(index).repeat(64));
    }
    ledger.accept(stage);
  }

  assert.equal(ledger.claims().productionDeploymentApproved, true);
  assert.equal(ledger.claims().releaseAuthorized, true);
  assert.equal(ledger.failureClaims().productionDeploymentApproved, false);
  assert.equal(ledger.failureClaims().releaseAuthorized, false);
  assert.equal(ledger.failureClaims().realBackendSemanticsQualified, true);
  assert.equal(ledger.failureClaims().independentSecurityReviewPassed, true);
});
