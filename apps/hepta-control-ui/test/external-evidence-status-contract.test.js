import assert from "node:assert/strict";
import test from "node:test";
import { validateCommonReceipt } from "../../../qualification/ui-control/external-evidence-primitives.mjs";

const expected = Object.freeze({
  candidateCommit: "1".repeat(40),
  candidateTree: "2".repeat(40),
  backendDeploymentDigest: "3".repeat(64),
});
const now = Date.parse("2026-09-29T12:00:00.000Z");

function receipt(schema, status) {
  const timestampField =
    schema === "hepta.ui-control.production-approval-receipt.v1"
      ? { approvedAt: "2026-09-29T11:00:00.000Z" }
      : { executedAt: "2026-09-29T11:00:00.000Z" };
  return {
    schema,
    status,
    ...expected,
    ...timestampField,
    rawEvidenceDigest: "4".repeat(64),
  };
}

test("non-approval evidence accepts only the exact passed status", () => {
  const schema = "hepta.ui-control.independent-security-review-receipt.v1";
  assert.doesNotThrow(() =>
    validateCommonReceipt(
      receipt(schema, "passed"),
      schema,
      expected,
      now,
      24 * 60 * 60_000,
    ));

  assert.throws(
    () =>
      validateCommonReceipt(
        receipt(schema, "approved"),
        schema,
        expected,
        now,
        24 * 60 * 60_000,
      ),
    error => error?.code === "UI_CONTROL_EXTERNAL_STATUS",
  );
});

test("production approval accepts only the exact approved status", () => {
  const schema = "hepta.ui-control.production-approval-receipt.v1";
  assert.doesNotThrow(() =>
    validateCommonReceipt(
      receipt(schema, "approved"),
      schema,
      expected,
      now,
      24 * 60 * 60_000,
    ));

  assert.throws(
    () =>
      validateCommonReceipt(
        receipt(schema, "passed"),
        schema,
        expected,
        now,
        24 * 60 * 60_000,
      ),
    error => error?.code === "UI_CONTROL_EXTERNAL_STATUS",
  );
});
