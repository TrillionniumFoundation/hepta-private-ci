import {
  SHA256,
  assertEvidence,
  boundedText,
  exactSha,
  validateCommonReceipt,
} from "./external-evidence-primitives.mjs";

export const REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS = Object.freeze([
  "read-runtime-view",
  "start-confirmation",
  "reconcile-confirmation",
  "stop-confirmation",
  "stale-confirmation-rejected",
  "indeterminate-recovery-by-lookup",
  "terminal-storage-failure-visible",
  "keyboard-focus-restoration",
]);

const BROWSERS = Object.freeze(["Chrome", "Firefox", "Safari"]);
const MODALITIES = new Set(["browser-operator", "keyboard-only", "screen-reader"]);
const REQUIRED_KEYBOARD_FLOWS = Object.freeze([
  "start-confirmation",
  "reconcile-confirmation",
  "stop-confirmation",
  "stale-confirmation-rejected",
  "keyboard-focus-restoration",
]);
const REQUIRED_SCREEN_READER_FLOWS = Object.freeze([
  "read-runtime-view",
  "indeterminate-recovery-by-lookup",
  "terminal-storage-failure-visible",
]);

function assertExactKeys(value, required, optional, label) {
  assertEvidence(
    value && typeof value === "object" && !Array.isArray(value),
    "UI_CONTROL_ACCEPTANCE_OBJECT",
    `${label} must be an object`,
  );
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  assertEvidence(
    required.every(key => keys.includes(key)) && keys.every(key => allowed.has(key)),
    "UI_CONTROL_ACCEPTANCE_FIELDS",
    `${label} has unknown or missing fields`,
  );
}

function validateBrowser(browser, label) {
  assertExactKeys(browser, ["name", "version"], [], label);
  assertEvidence(
    BROWSERS.includes(browser.name),
    "UI_CONTROL_ACCEPTANCE_BROWSER",
    `${label} must name Chrome, Firefox, or Safari`,
  );
  boundedText(browser.version, `${label}.version`, 64);
  return browser.name;
}

function validateAssistiveTechnology(value, label) {
  assertExactKeys(value, ["name", "version"], [], label);
  const name = boundedText(value.name, `${label}.name`, 128);
  const version = boundedText(value.version, `${label}.version`, 64);
  return `${name.normalize("NFKC").toLowerCase()}:${version.normalize("NFKC").toLowerCase()}`;
}

function validateFlows(flows, label) {
  assertEvidence(
    Array.isArray(flows) && flows.length > 0 &&
      flows.length <= REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS.length,
    "UI_CONTROL_ACCEPTANCE_FLOWS",
    `${label} must contain one or more bounded operator flows`,
  );
  const observed = new Set();
  for (const flow of flows) {
    assertEvidence(
      REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS.includes(flow) && !observed.has(flow),
      "UI_CONTROL_ACCEPTANCE_FLOW",
      `${label} contains an unexpected or duplicate flow: ${String(flow)}`,
    );
    observed.add(flow);
  }
  return observed;
}

function assertCoverage(observed, required, code, message) {
  assertEvidence(required.every(value => observed.has(value)), code, message);
}

export function validateIndependentAcceptanceMatrix(
  receipt,
  expected,
  { now = Date.now(), maxAgeMs = 90 * 24 * 60 * 60_000 } = {},
) {
  validateCommonReceipt(
    receipt,
    "hepta.ui-control.independent-acceptance-receipt.v2",
    expected,
    now,
    maxAgeMs,
  );
  assertEvidence(
    receipt.verifier?.independentOfImplementationAuthor === true,
    "UI_CONTROL_ACCEPTANCE_INDEPENDENCE",
    "acceptance verifier is not independent",
  );
  boundedText(receipt.verifier?.identity, "verifier.identity");
  boundedText(receipt.verifier?.organization, "verifier.organization");
  assertEvidence(
    Array.isArray(receipt.observations) &&
      receipt.observations.length >= 8 && receipt.observations.length <= 128,
    "UI_CONTROL_ACCEPTANCE_OBSERVATIONS",
    "independent acceptance requires three-browser operator and keyboard coverage plus two screen-reader observations",
  );

  const observationIds = new Set();
  const browserOperatorBrowsers = new Set();
  const keyboardBrowsers = new Set();
  const screenReaderBrowsers = new Set();
  const assistiveTechnologies = new Set();
  const coveredFlows = new Set();
  const keyboardFlows = new Set();
  const screenReaderFlows = new Set();

  for (const item of receipt.observations) {
    assertExactKeys(
      item,
      ["id", "modality", "browser", "os", "flows", "result", "rawEvidenceDigest"],
      ["assistiveTechnology", "notes"],
      `acceptance observation ${item?.id ?? "unknown"}`,
    );
    const id = boundedText(item.id, "observation.id", 128);
    assertEvidence(
      !observationIds.has(id),
      "UI_CONTROL_ACCEPTANCE_DUPLICATE",
      `duplicate acceptance observation: ${id}`,
    );
    observationIds.add(id);
    assertEvidence(
      item.result === "pass",
      "UI_CONTROL_ACCEPTANCE_CASE_FAILED",
      `acceptance observation failed: ${id}`,
    );
    assertEvidence(
      MODALITIES.has(item.modality),
      "UI_CONTROL_ACCEPTANCE_MODALITY",
      `unsupported acceptance modality: ${String(item.modality)}`,
    );
    const browser = validateBrowser(item.browser, `${id}.browser`);
    boundedText(item.os, `${id}.os`, 128);
    exactSha(item.rawEvidenceDigest, `${id}.rawEvidenceDigest`, SHA256);
    if (item.notes !== undefined) boundedText(item.notes, `${id}.notes`, 4096);
    const flows = validateFlows(item.flows, `${id}.flows`);
    for (const flow of flows) coveredFlows.add(flow);

    if (item.modality === "browser-operator") {
      assertEvidence(
        item.assistiveTechnology === undefined,
        "UI_CONTROL_ACCEPTANCE_AT_SCOPE",
        "browser-operator observations must not claim assistive-technology identity",
      );
      browserOperatorBrowsers.add(browser);
    } else if (item.modality === "keyboard-only") {
      assertEvidence(
        item.assistiveTechnology === undefined,
        "UI_CONTROL_ACCEPTANCE_AT_SCOPE",
        "keyboard-only observations must not claim assistive-technology identity",
      );
      keyboardBrowsers.add(browser);
      for (const flow of flows) keyboardFlows.add(flow);
    } else {
      const assistiveTechnology = validateAssistiveTechnology(
        item.assistiveTechnology,
        `${id}.assistiveTechnology`,
      );
      assistiveTechnologies.add(assistiveTechnology);
      screenReaderBrowsers.add(browser);
      for (const flow of flows) screenReaderFlows.add(flow);
    }
  }

  assertCoverage(
    browserOperatorBrowsers,
    BROWSERS,
    "UI_CONTROL_ACCEPTANCE_OPERATOR_BROWSER_MATRIX",
    "browser-operator acceptance must cover Chrome, Firefox, and Safari",
  );
  assertCoverage(
    keyboardBrowsers,
    BROWSERS,
    "UI_CONTROL_ACCEPTANCE_KEYBOARD_BROWSER_MATRIX",
    "keyboard-only acceptance must cover Chrome, Firefox, and Safari",
  );
  assertEvidence(
    screenReaderBrowsers.has("Safari") &&
      (screenReaderBrowsers.has("Chrome") || screenReaderBrowsers.has("Firefox")),
    "UI_CONTROL_ACCEPTANCE_SCREEN_READER_BROWSER_MATRIX",
    "screen-reader acceptance must cover Safari and at least one non-Safari browser",
  );
  assertEvidence(
    assistiveTechnologies.size >= 2,
    "UI_CONTROL_ACCEPTANCE_AT_MATRIX",
    "at least two distinct assistive-technology observations are required",
  );
  assertCoverage(
    keyboardFlows,
    REQUIRED_KEYBOARD_FLOWS,
    "UI_CONTROL_ACCEPTANCE_KEYBOARD_FLOW_MATRIX",
    "keyboard-only acceptance did not cover confirmation, stale-state, and focus-restoration flows",
  );
  assertCoverage(
    screenReaderFlows,
    REQUIRED_SCREEN_READER_FLOWS,
    "UI_CONTROL_ACCEPTANCE_SCREEN_READER_FLOW_MATRIX",
    "screen-reader acceptance did not cover runtime reading, lookup recovery, and storage-failure presentation",
  );
  assertCoverage(
    coveredFlows,
    REQUIRED_INDEPENDENT_ACCEPTANCE_FLOWS,
    "UI_CONTROL_ACCEPTANCE_FLOW_MATRIX",
    "independent acceptance did not cover every required operator flow",
  );

  return Object.freeze({
    schema: "hepta.ui-control.independent-acceptance-summary.v1",
    observationCount: receipt.observations.length,
    browserOperatorBrowsers: Object.freeze([...browserOperatorBrowsers].sort()),
    keyboardBrowsers: Object.freeze([...keyboardBrowsers].sort()),
    screenReaderBrowsers: Object.freeze([...screenReaderBrowsers].sort()),
    assistiveTechnologyCount: assistiveTechnologies.size,
    coveredFlows: Object.freeze([...coveredFlows].sort()),
  });
}
