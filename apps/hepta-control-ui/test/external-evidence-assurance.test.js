import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateAssuranceChain } from "../../../qualification/ui-control/external-evidence-assurance.mjs";

const baseReceipts = () => ({
  deploymentSecurityReceipt: {
    deployment: { observedAt: "2026-09-29T09:00:00.000Z" },
  },
  realBackendReceipt: {
    backend: { observedAt: "2026-09-29T09:10:00.000Z" },
  },
  independentAcceptanceReceipt: {
    executedAt: "2026-09-29T09:20:00.000Z",
    verifier: { identity: "acceptance@example.test" },
  },
  independentSecurityReceipt: {
    executedAt: "2026-09-29T09:30:00.000Z",
    reviewer: { identity: "security-review@example.test" },
  },
  operationalExerciseReceipt: {
    executedAt: "2026-09-29T09:40:00.000Z",
  },
  productionApprovalReceipt: {
    approvedAt: "2026-09-29T09:50:00.000Z",
    approvals: [
      {
        role: "deployment-authority",
        identity: "deployment@example.test",
        approvedAt: "2026-09-29T09:45:00.000Z",
      },
      {
        role: "release-authority",
        identity: "release@example.test",
        approvedAt: "2026-09-29T09:47:00.000Z",
      },
      {
        role: "security-authority",
        identity: "security-approval@example.test",
        approvedAt: "2026-09-29T09:50:00.000Z",
      },
    ],
  },
});

const approvalSchema = JSON.parse(readFileSync(
  new URL("../../../qualification/ui-control/PRODUCTION_APPROVAL_SCHEMA.json", import.meta.url),
  "utf8",
));

test("production approval schema requires an approval time for every authority", () => {
  const required = approvalSchema.properties.approvals.items.required;
  assert.deepEqual(required, ["role", "identity", "approvedAt"]);
  assert.equal(approvalSchema.properties.approvals.items.additionalProperties, false);
});

test("assurance chain binds distinct reviewers and approvers without exposing raw identities", () => {
  const result = validateAssuranceChain(baseReceipts());
  assert.equal(result.schema, "hepta.ui-control.assurance-chain.v1");
  assert.equal(result.principalCount, 5);
  assert.equal(result.reviewerSeparationVerified, true);
  assert.equal(result.evidenceChronologyBound, true);
  for (const digest of [
    ...Object.values(result.reviewerIdentityDigests),
    ...Object.values(result.approvalIdentityDigests),
  ]) {
    assert.match(digest, /^[0-9a-f]{64}$/u);
  }
  const serialized = JSON.stringify(result);
  assert.doesNotMatch(serialized, /acceptance@example\.test/u);
  assert.doesNotMatch(serialized, /security-review@example\.test/u);
  assert.doesNotMatch(serialized, /deployment@example\.test/u);
});

test("assurance chain rejects one principal reused across independent reviews", () => {
  const receipts = baseReceipts();
  receipts.independentSecurityReceipt.reviewer.identity = " Acceptance@Example.Test ";
  assert.throws(
    () => validateAssuranceChain(receipts),
    error => error?.code === "UI_CONTROL_ASSURANCE_IDENTITY_REUSE",
  );
});

test("assurance chain rejects an independent reviewer reused as an approval authority", () => {
  const receipts = baseReceipts();
  receipts.productionApprovalReceipt.approvals[1].identity = "SECURITY-REVIEW@example.test";
  assert.throws(
    () => validateAssuranceChain(receipts),
    error => error?.code === "UI_CONTROL_ASSURANCE_IDENTITY_REUSE",
  );
});

test("assurance chain rejects aggregate approval that predates accepted evidence", () => {
  const receipts = baseReceipts();
  receipts.productionApprovalReceipt.approvedAt = "2026-09-29T09:39:59.999Z";
  assert.throws(
    () => validateAssuranceChain(receipts),
    error => error?.code === "UI_CONTROL_APPROVAL_PREMATURE",
  );
});

test("assurance chain rejects any individual authority approval that predates evidence", () => {
  const receipts = baseReceipts();
  receipts.productionApprovalReceipt.approvals[0].approvedAt = "2026-09-29T09:39:59.999Z";
  assert.throws(
    () => validateAssuranceChain(receipts),
    error => error?.code === "UI_CONTROL_APPROVAL_PREMATURE",
  );
});

test("assurance chain rejects a summary timestamp padded beyond the last authority approval", () => {
  const receipts = baseReceipts();
  receipts.productionApprovalReceipt.approvedAt = "2026-09-29T09:51:00.000Z";
  assert.throws(
    () => validateAssuranceChain(receipts),
    error => error?.code === "UI_CONTROL_APPROVAL_SUMMARY_TIME",
  );
});
