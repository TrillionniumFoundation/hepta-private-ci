import test from "node:test";
import assert from "node:assert/strict";
import {
  REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS,
  validateIndependentAcceptanceMatrix,
} from "../../../qualification/ui-control/external-evidence-acceptance.mjs";

const expected = Object.freeze({
  candidateCommit: "1".repeat(40),
  candidateTree: "2".repeat(40),
  backendDeploymentDigest: "3".repeat(64),
});
const rawEvidenceDigest = "4".repeat(64);
const now = Date.parse("2026-09-29T10:00:00.000Z");

function observation({ id, modality, browser, os, flows, assistiveTechnology }) {
  return {
    id,
    modality,
    browser,
    os,
    flows,
    ...(assistiveTechnology ? { assistiveTechnology } : {}),
    result: "pass",
    rawEvidenceDigest,
  };
}

function receipt() {
  return {
    schema: "hepta.ui-control.independent-acceptance-receipt.v2",
    status: "passed",
    candidateCommit: expected.candidateCommit,
    candidateTree: expected.candidateTree,
    backendDeploymentDigest: expected.backendDeploymentDigest,
    executedAt: "2026-09-29T09:30:00.000Z",
    verifier: {
      identity: "independent-acceptance@example.test",
      organization: "Independent lab",
      independentOfImplementationAuthor: true,
    },
    observations: [
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
    ],
    rawEvidenceDigest,
  };
}

test("independent acceptance binds three-browser operator and keyboard coverage to critical flows", () => {
  const result = validateIndependentAcceptanceMatrix(receipt(), expected, { now });
  assert.equal(result.observationCount, 8);
  assert.deepEqual(result.browserOperatorBrowsers, ["Chrome", "Firefox", "Safari"]);
  assert.deepEqual(result.keyboardBrowsers, ["Chrome", "Firefox", "Safari"]);
  assert.equal(result.assistiveTechnologyCount, 2);
  assert.deepEqual(result.coveredFlows, [...REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS].sort());
});

test("independent acceptance rejects a missing keyboard browser", () => {
  const value = receipt();
  value.observations.find(item => item.id === "firefox-keyboard").browser.name = "Chrome";
  assert.throws(
    () => validateIndependentAcceptanceMatrix(value, expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_KEYBOARD_BROWSER_MATRIX",
  );
});

test("independent acceptance rejects status-only observations without flow evidence", () => {
  const value = receipt();
  delete value.observations[0].flows;
  assert.throws(
    () => validateIndependentAcceptanceMatrix(value, expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_FIELDS",
  );
});

test("screen-reader acceptance must exercise lookup recovery and storage-failure presentation", () => {
  const value = receipt();
  for (const item of value.observations.filter(entry => entry.modality === "screen-reader")) {
    item.flows = ["read-runtime-view"];
  }
  assert.throws(
    () => validateIndependentAcceptanceMatrix(value, expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_SCREEN_READER_FLOW_MATRIX",
  );
});

test("keyboard acceptance must exercise confirmations, stale rejection, and focus restoration", () => {
  const value = receipt();
  for (const item of value.observations.filter(entry => entry.modality === "keyboard-only")) {
    item.flows = ["read-runtime-view"];
  }
  assert.throws(
    () => validateIndependentAcceptanceMatrix(value, expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_KEYBOARD_FLOW_MATRIX",
  );
});

test("non-screen-reader observations cannot claim assistive-technology identity", () => {
  const value = receipt();
  value.observations[0].assistiveTechnology = { name: "Synthetic AT", version: "1" };
  assert.throws(
    () => validateIndependentAcceptanceMatrix(value, expected, { now }),
    error => error?.code === "UI_CONTROL_ACCEPTANCE_AT_SCOPE",
  );
});
