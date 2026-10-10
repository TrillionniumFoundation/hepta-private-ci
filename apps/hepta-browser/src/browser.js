const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const ASCII_CONTROL = /[\u0000-\u001f\u007f]/;
const ENCODED_ASCII_CONTROL = /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i;
const MAX_CANONICAL_INPUT_BYTES = 8192;
const MAX_CANONICAL_URL_BYTES = 4096;
const UTF8 = new TextEncoder();
const PAGE_STATES = new Set(["loading", "ready", "failed", "quarantined"]);
const LOCAL_NAVIGATION_INPUT_SCHEMA =
  "hepta.browser.local-navigation-proposal-input.v1";
const LOCAL_NAVIGATION_PROPOSAL_SCHEMA =
  "hepta.browser.local-navigation-proposal.v1";
const LOCAL_PAGE_OBSERVATION_SCHEMA =
  "hepta.browser.local-page-observation.v1";
const LOCAL_PAGE_PROJECTION_SCHEMA =
  "hepta.browser.local-page-projection.v1";

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function requireStableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function requireDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new TypeError(`${name} must be a lowercase SHA-256 digest`);
  }
  return value;
}

function requireNonzeroDigest(value, name) {
  const digest = requireDigest(value, name);
  if (digest === ZERO_DIGEST) {
    throw new TypeError(`${name} must be non-zero`);
  }
  return digest;
}

function containsLoneUtf16Surrogate(value) {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const nextCodeUnit = value.charCodeAt(index + 1);
      if (!(nextCodeUnit >= 0xdc00 && nextCodeUnit <= 0xdfff)) {
        return true;
      }
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function parseCanonicalInput(encoded, expectedKeys, name) {
  if (
    typeof encoded !== "string" ||
    encoded.length === 0 ||
    encoded.length > MAX_CANONICAL_INPUT_BYTES
  ) {
    throw new TypeError(`${name} must be bounded canonical JSON`);
  }
  const byteLength = UTF8.encode(encoded).byteLength;
  if (byteLength > MAX_CANONICAL_INPUT_BYTES) {
    throw new TypeError(`${name} exceeds the canonical JSON byte limit`);
  }
  let value;
  try {
    value = JSON.parse(encoded);
  } catch {
    throw new TypeError(`${name} must be valid canonical JSON`);
  }
  requireRecord(value, name);
  const canonicalKeys = [...expectedKeys].sort();
  const keys = Object.keys(value);
  if (
    keys.length !== canonicalKeys.length ||
    keys.some((key, index) => key !== canonicalKeys[index])
  ) {
    throw new TypeError(`${name} contains missing, unknown, or unordered fields`);
  }
  const snapshot = Object.fromEntries(
    canonicalKeys.map((key) => [key, value[key]]),
  );
  if (JSON.stringify(snapshot) !== encoded) {
    throw new TypeError(`${name} is not in canonical JSON form`);
  }
  return Object.freeze(snapshot);
}

function requireWebUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError("navigation URL must use HTTP or HTTPS");
  }
  url.username = "";
  url.password = "";
  url.hash = "";
  return url.toString();
}

function requireBoundedCanonicalWebUrl(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("navigation URL must be a bounded string");
  }
  if (ASCII_CONTROL.test(value)) {
    throw new TypeError("navigation URL cannot contain ASCII control characters");
  }
  if (ENCODED_ASCII_CONTROL.test(value)) {
    throw new TypeError(
      "navigation URL cannot contain encoded ASCII control characters",
    );
  }
  if (containsLoneUtf16Surrogate(value)) {
    throw new TypeError("navigation URL must contain well-formed Unicode");
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new TypeError("navigation URL must be an absolute URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError("navigation URL must use HTTP or HTTPS");
  }
  if (url.username !== "" || url.password !== "") {
    throw new TypeError("navigation URL cannot contain credentials");
  }
  const afterScheme = value.slice(value.indexOf(":") + 1);
  const authority = afterScheme
    .replace(/^[\\/]+/, "")
    .split(/[\\/?#]/, 1)[0];
  if (authority.includes("@")) {
    throw new TypeError("navigation URL cannot contain userinfo syntax");
  }
  const normalized = url.toString();
  if (UTF8.encode(normalized).byteLength > MAX_CANONICAL_URL_BYTES) {
    throw new TypeError("normalized navigation URL exceeds the UTF-8 byte limit");
  }
  return normalized;
}

export function buildNavigationIntent(input) {
  requireRecord(input, "input");
  const navigationId = requireStableId(input.navigationId, "navigationId");
  const tabId = requireStableId(input.tabId, "tabId");
  const url = requireWebUrl(input.url);
  const policyDigest = requireDigest(input.policyDigest, "policyDigest");
  const expectedRevision = input.expectedRevision;
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
    throw new TypeError("expectedRevision must be a positive safe integer");
  }
  return Object.freeze({
    kind: "BrowserNavigationIntentV1",
    navigationId,
    tabId,
    url,
    policyDigest,
    expectedRevision,
    networkAuthority: false,
    effectAuthority: false,
    directStoreWrite: false,
  });
}

export function projectPageState(observation) {
  requireRecord(observation, "observation");
  const tabId = requireStableId(observation.tabId, "tabId");
  if (!PAGE_STATES.has(observation.state)) {
    throw new TypeError("state is not registered");
  }
  const documentDigest = requireDigest(
    observation.documentDigest,
    "documentDigest",
  );
  const sourceRevision = observation.sourceRevision;
  if (!Number.isSafeInteger(sourceRevision) || sourceRevision < 1) {
    throw new TypeError("sourceRevision must be a positive safe integer");
  }
  return Object.freeze({
    tabId,
    state: observation.state,
    documentDigest,
    sourceRevision,
    interactive: observation.state === "ready",
    networkAuthority: false,
    effectAuthority: false,
  });
}

/**
 * Build an authority-free, package-local browser shadow proposal.
 * This is not a registered navigation intent or a network capability.
 *
 * @internal
 */
export function buildLocalNavigationProposalFromCanonicalJson(encoded) {
  const input = parseCanonicalInput(
    encoded,
    [
      "schema",
      "navigationId",
      "tabId",
      "url",
      "policyDigest",
      "expectedRevision",
    ],
    "local navigation proposal",
  );
  if (input.schema !== LOCAL_NAVIGATION_INPUT_SCHEMA) {
    throw new TypeError("local navigation proposal schema is unsupported");
  }
  const navigationId = requireStableId(input.navigationId, "navigationId");
  const tabId = requireStableId(input.tabId, "tabId");
  const url = requireBoundedCanonicalWebUrl(input.url);
  const policyDigest = requireNonzeroDigest(input.policyDigest, "policyDigest");
  const expectedRevision = input.expectedRevision;
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
    throw new TypeError("expectedRevision must be a positive safe integer");
  }
  return Object.freeze({
    localSchema: LOCAL_NAVIGATION_PROPOSAL_SCHEMA,
    navigationId,
    tabId,
    url,
    policyDigest,
    expectedRevision,
    networkAuthority: false,
    effectAuthority: false,
    directStoreWrite: false,
  });
}

/**
 * Parse a bounded package-local page fixture before shadow projection.
 * This proves local decoding only, not source freshness or profile durability.
 *
 * @internal
 */
export function projectPageStateFromLocalCanonicalJson(encoded) {
  const observation = parseCanonicalInput(
    encoded,
    ["schema", "tabId", "state", "documentDigest", "sourceRevision"],
    "local page observation",
  );
  if (observation.schema !== LOCAL_PAGE_OBSERVATION_SCHEMA) {
    throw new TypeError("local page observation schema is unsupported");
  }
  requireNonzeroDigest(observation.documentDigest, "documentDigest");
  return Object.freeze({
    localSchema: LOCAL_PAGE_PROJECTION_SCHEMA,
    ...projectPageState(observation),
  });
}
