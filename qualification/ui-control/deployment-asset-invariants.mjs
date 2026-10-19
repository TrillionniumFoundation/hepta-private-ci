import { assertEvidence, sha256 } from "./external-evidence-primitives.mjs";

export const UI_CONTROL_BROWSER_BUILD_SCHEMA = "hepta.ui-control.browser-build.v2";
export const UI_CONTROL_CSRF_SUBSTITUTION_KIND = "csrf-meta-content-v1";
export const UI_CONTROL_CSRF_META_PLACEHOLDER = '<meta name="csrf-token" content="">';
export const UI_CONTROL_RUNTIME_SUBSTITUTIONS = Object.freeze({
  "index.html": Object.freeze([UI_CONTROL_CSRF_SUBSTITUTION_KIND]),
});

const SAFE_CSRF_TOKEN = /^[A-Za-z0-9._~+/=-]{16,512}$/u;
const CSRF_META_PATTERN = /<meta name="csrf-token" content="[^"]*">/gu;

function asBuffer(value, label) {
  assertEvidence(
    Buffer.isBuffer(value) || value instanceof Uint8Array,
    "UI_CONTROL_ASSET_BYTES",
    `${label} must be bytes`,
  );
  return Buffer.from(value);
}

function decodeUtf8(value, label) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(value);
  } catch {
    const error = new Error(`${label} is not valid UTF-8`);
    error.code = "UI_CONTROL_ASSET_UTF8";
    throw error;
  }
}

function exactSingleMatch(value, pattern, label) {
  const matches = value.match(pattern) ?? [];
  assertEvidence(
    matches.length === 1,
    "UI_CONTROL_CSRF_BOOTSTRAP_SLOT",
    `${label} must contain exactly one CSRF bootstrap slot`,
  );
  return matches[0];
}

export function verifyCsrfBootstrapAsset(candidateValue, deployedValue, csrfToken) {
  assertEvidence(
    typeof csrfToken === "string" && SAFE_CSRF_TOKEN.test(csrfToken),
    "UI_CONTROL_CSRF_BOOTSTRAP_TOKEN",
    "CSRF bootstrap token must be a bounded attribute-safe token",
  );
  const candidateBytes = asBuffer(candidateValue, "candidate index.html");
  const deployedBytes = asBuffer(deployedValue, "deployed index.html");
  const candidate = decodeUtf8(candidateBytes, "candidate index.html");
  const deployed = decodeUtf8(deployedBytes, "deployed index.html");
  const candidateSlot = exactSingleMatch(candidate, CSRF_META_PATTERN, "candidate index.html");
  assertEvidence(
    candidateSlot === UI_CONTROL_CSRF_META_PLACEHOLDER,
    "UI_CONTROL_CSRF_BOOTSTRAP_TEMPLATE",
    "candidate index.html does not contain the canonical empty CSRF bootstrap slot",
  );
  const deployedSlot = exactSingleMatch(deployed, CSRF_META_PATTERN, "deployed index.html");
  const expectedSlot = `<meta name="csrf-token" content="${csrfToken}">`;
  assertEvidence(
    deployedSlot === expectedSlot,
    "UI_CONTROL_CSRF_BOOTSTRAP_BINDING",
    "deployed index.html is not bound to the selected CSRF token",
  );
  const canonicalDeployed = deployed.replace(deployedSlot, UI_CONTROL_CSRF_META_PLACEHOLDER);
  const canonicalBytes = Buffer.from(canonicalDeployed, "utf8");
  assertEvidence(
    canonicalBytes.equals(candidateBytes),
    "UI_CONTROL_DEPLOYED_ASSET_DRIFT",
    "deployed index.html changed outside the declared CSRF bootstrap slot",
  );
  return Object.freeze({
    kind: UI_CONTROL_CSRF_SUBSTITUTION_KIND,
    candidateSha256: sha256(candidateBytes),
    canonicalDeployedSha256: sha256(canonicalBytes),
  });
}

export function verifyExactAsset(candidateValue, deployedValue, relativePath) {
  const candidateBytes = asBuffer(candidateValue, `candidate ${relativePath}`);
  const deployedBytes = asBuffer(deployedValue, `deployed ${relativePath}`);
  assertEvidence(
    deployedBytes.equals(candidateBytes),
    "UI_CONTROL_DEPLOYED_ASSET_DRIFT",
    `${relativePath}: deployed bytes do not match the exact candidate build`,
  );
  return Object.freeze({ kind: "exact-bytes-v1", candidateSha256: sha256(candidateBytes) });
}

export function assertRuntimeSubstitutionManifest(value) {
  assertEvidence(
    value && typeof value === "object" && !Array.isArray(value),
    "UI_CONTROL_BUILD_SUBSTITUTIONS",
    "browser build manifest runtimeSubstitutions must be an object",
  );
  assertEvidence(
    Object.keys(value).length === 1 &&
      Array.isArray(value["index.html"]) &&
      value["index.html"].length === 1 &&
      value["index.html"][0] === UI_CONTROL_CSRF_SUBSTITUTION_KIND,
    "UI_CONTROL_BUILD_SUBSTITUTIONS",
    "browser build manifest must declare only the canonical index.html CSRF substitution",
  );
  return UI_CONTROL_RUNTIME_SUBSTITUTIONS;
}
