import { assertEvidence, boundedText } from "./external-evidence-primitives.mjs";

export const UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE = "hepta.ui-control.deployment-security-policy.v1";
export const UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS = 31_536_000;
export const UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS = 7 * 24 * 60 * 60;

const REQUIRED_CSP = Object.freeze({
  "default-src": Object.freeze(["'self'"]),
  "script-src": Object.freeze(["'self'"]),
  "style-src": Object.freeze(["'self'"]),
  "connect-src": Object.freeze(["'self'"]),
  "img-src": Object.freeze(["'self'", "data:"]),
  "object-src": Object.freeze(["'none'"]),
  "base-uri": Object.freeze(["'none'"]),
  "form-action": Object.freeze(["'self'"]),
  "frame-ancestors": Object.freeze(["'none'"]),
});
const ALLOWED_CSP_DIRECTIVES = new Set([
  ...Object.keys(REQUIRED_CSP),
  "upgrade-insecure-requests",
  "block-all-mixed-content",
]);
const FORBIDDEN_CSP_SOURCES = new Set([
  "*",
  "'unsafe-inline'",
  "'unsafe-eval'",
  "'unsafe-hashes'",
  "'wasm-unsafe-eval'",
  "http:",
]);
const REQUIRED_PERMISSIONS_POLICY = Object.freeze(["camera", "microphone", "geolocation", "payment"]);
const WEAK_CIPHER = /(?:^|[_-])(?:RC4|3DES|DES|CBC|NULL|EXPORT|MD5)(?:[_-]|$)/iu;

function exactTokens(actual, expected, code, label) {
  const observed = [...actual].sort();
  const required = [...expected].sort();
  assertEvidence(
    JSON.stringify(observed) === JSON.stringify(required),
    code,
    `${label} must be exactly ${required.join(" ")}`,
  );
}

export function assertContentSecurityPolicy(value) {
  assertEvidence(typeof value === "string" && value.trim().length > 0, "UI_CONTROL_CSP_MISSING", "Content-Security-Policy is required");
  const directives = new Map();
  for (const rawDirective of value.split(";")) {
    const directive = rawDirective.trim();
    if (!directive) continue;
    const [rawName, ...rawSources] = directive.split(/\s+/u);
    const name = rawName.toLowerCase();
    assertEvidence(/^[a-z][a-z0-9-]*$/u.test(name), "UI_CONTROL_CSP_SYNTAX", `invalid CSP directive: ${rawName}`);
    assertEvidence(ALLOWED_CSP_DIRECTIVES.has(name), "UI_CONTROL_CSP_DIRECTIVE", `CSP directive is not allowed: ${name}`);
    assertEvidence(!directives.has(name), "UI_CONTROL_CSP_DUPLICATE", `duplicate CSP directive: ${name}`);
    const sources = rawSources.map(source => source.toLowerCase());
    if (!Object.hasOwn(REQUIRED_CSP, name)) {
      assertEvidence(sources.length === 0, "UI_CONTROL_CSP_DIRECTIVE", `${name} must not carry source values`);
    }
    for (const source of sources) {
      assertEvidence(!FORBIDDEN_CSP_SOURCES.has(source), "UI_CONTROL_CSP_UNSAFE_SOURCE", `${name} contains forbidden source ${source}`);
      assertEvidence(!source.includes("*"), "UI_CONTROL_CSP_UNSAFE_SOURCE", `${name} contains a wildcard source`);
      assertEvidence(
        !/^(?:https?|wss?|blob):/iu.test(source),
        "UI_CONTROL_CSP_UNSAFE_SOURCE",
        `${name} contains an externally scoped source ${source}`,
      );
      assertEvidence(source !== "data:" || name === "img-src", "UI_CONTROL_CSP_UNSAFE_SOURCE", `${name} contains an unexpected data: source`);
    }
    directives.set(name, sources);
  }
  for (const [name, sources] of Object.entries(REQUIRED_CSP)) {
    assertEvidence(directives.has(name), "UI_CONTROL_CSP_DIRECTIVE", `CSP missing ${name}`);
    exactTokens(directives.get(name), sources, "UI_CONTROL_CSP_DIRECTIVE", `CSP ${name}`);
  }
  return Object.freeze(Object.fromEntries([...directives].map(([name, sources]) => [name, Object.freeze([...sources])])));
}

export function assertHstsPolicy(value, minimumMaxAgeSeconds = UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS) {
  assertEvidence(typeof value === "string" && value.trim().length > 0, "UI_CONTROL_HSTS", "Strict-Transport-Security is required");
  const directives = new Map();
  for (const raw of value.split(";")) {
    const entry = raw.trim();
    if (!entry) continue;
    const separator = entry.indexOf("=");
    const name = (separator === -1 ? entry : entry.slice(0, separator)).trim().toLowerCase();
    const directiveValue = separator === -1 ? true : entry.slice(separator + 1).trim();
    assertEvidence(!directives.has(name), "UI_CONTROL_HSTS_DUPLICATE", `duplicate HSTS directive: ${name}`);
    directives.set(name, directiveValue);
  }
  const maxAgeValue = directives.get("max-age");
  assertEvidence(typeof maxAgeValue === "string" && /^\d+$/u.test(maxAgeValue), "UI_CONTROL_HSTS", "HSTS max-age must be an integer");
  const maxAgeSeconds = Number(maxAgeValue);
  assertEvidence(Number.isSafeInteger(maxAgeSeconds) && maxAgeSeconds >= minimumMaxAgeSeconds, "UI_CONTROL_HSTS_MAX_AGE", `HSTS max-age must be at least ${minimumMaxAgeSeconds}`);
  return Object.freeze({ maxAgeSeconds, includeSubDomains: directives.has("includesubdomains"), preload: directives.has("preload") });
}

export function assertNoStoreCachePolicy(value) {
  assertEvidence(typeof value === "string" && value.trim().length > 0, "UI_CONTROL_CACHE_CONTROL", "Cache-Control is required");
  const directives = new Map();
  for (const raw of value.split(",")) {
    const entry = raw.trim();
    if (!entry) continue;
    const separator = entry.indexOf("=");
    const name = (separator === -1 ? entry : entry.slice(0, separator)).trim().toLowerCase();
    const directiveValue = separator === -1 ? true : entry.slice(separator + 1).trim().replace(/^"|"$/gu, "");
    assertEvidence(!directives.has(name), "UI_CONTROL_CACHE_DUPLICATE", `duplicate Cache-Control directive: ${name}`);
    directives.set(name, directiveValue);
  }
  assertEvidence(directives.get("no-store") === true, "UI_CONTROL_CACHE_CONTROL", "Cache-Control must include no-store as a flag directive");
  for (const forbidden of ["public", "immutable"]) {
    assertEvidence(!directives.has(forbidden), "UI_CONTROL_CACHE_CONTROL", `Cache-Control must not include ${forbidden}`);
  }
  for (const age of ["max-age", "s-maxage"]) {
    if (!directives.has(age)) continue;
    const raw = directives.get(age);
    assertEvidence(typeof raw === "string" && /^\d+$/u.test(raw), "UI_CONTROL_CACHE_CONTROL", `${age} must be an integer`);
    assertEvidence(Number(raw) === 0, "UI_CONTROL_CACHE_CONTROL", `${age} must be zero when present`);
  }
  return Object.freeze(Object.fromEntries(directives));
}

export function assertPermissionsPolicy(value) {
  assertEvidence(typeof value === "string" && value.trim().length > 0, "UI_CONTROL_PERMISSIONS_POLICY", "Permissions-Policy is required");
  const directives = new Map();
  for (const raw of value.split(",")) {
    const entry = raw.trim();
    if (!entry) continue;
    const match = /^([a-z][a-z0-9-]*)\s*=\s*(\([^)]*\))$/iu.exec(entry);
    assertEvidence(match, "UI_CONTROL_PERMISSIONS_POLICY", `invalid Permissions-Policy directive: ${entry}`);
    const name = match[1].toLowerCase();
    const allowlist = match[2].replace(/\s+/gu, "").toLowerCase();
    assertEvidence(!directives.has(name), "UI_CONTROL_PERMISSIONS_POLICY", `duplicate Permissions-Policy directive: ${name}`);
    directives.set(name, allowlist);
  }
  for (const name of REQUIRED_PERMISSIONS_POLICY) {
    assertEvidence(directives.get(name) === "()", "UI_CONTROL_PERMISSIONS_POLICY", `Permissions-Policy must disable ${name}`);
  }
  return Object.freeze(Object.fromEntries(directives));
}

export function assertCookiePolicy(value, expectedPath) {
  assertEvidence(typeof value === "string" && value.length > 0 && value.length <= 8192, "UI_CONTROL_COOKIE_POLICY", "Set-Cookie value is missing or too large");
  const segments = value.split(";").map(part => part.trim());
  const pair = segments.shift();
  const pairSeparator = pair.indexOf("=");
  assertEvidence(pairSeparator > 0, "UI_CONTROL_COOKIE_POLICY", "Set-Cookie is missing a cookie name/value pair");
  const name = pair.slice(0, pairSeparator).trim();
  assertEvidence(/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/u.test(name), "UI_CONTROL_COOKIE_POLICY", "Set-Cookie has an invalid cookie name");
  const attributes = new Map();
  for (const entry of segments.filter(Boolean)) {
    const separator = entry.indexOf("=");
    const attributeName = (separator === -1 ? entry : entry.slice(0, separator)).trim().toLowerCase();
    const attributeValue = separator === -1 ? true : entry.slice(separator + 1).trim();
    assertEvidence(/^[a-z][a-z0-9-]*$/u.test(attributeName), "UI_CONTROL_COOKIE_POLICY", `invalid cookie attribute: ${attributeName}`);
    assertEvidence(!attributes.has(attributeName), "UI_CONTROL_COOKIE_DUPLICATE_ATTRIBUTE", `duplicate cookie attribute: ${attributeName}`);
    attributes.set(attributeName, attributeValue);
  }
  assertEvidence(attributes.get("secure") === true, "UI_CONTROL_COOKIE_SECURE", "connect cookie must be Secure");
  assertEvidence(attributes.get("httponly") === true, "UI_CONTROL_COOKIE_HTTP_ONLY", "connect cookie must be HttpOnly");
  const sameSite = String(attributes.get("samesite") || "").toLowerCase();
  assertEvidence(["strict", "lax"].includes(sameSite), "UI_CONTROL_COOKIE_SAMESITE", "connect cookie must set SameSite=Strict or Lax");
  assertEvidence(attributes.get("path") === expectedPath, "UI_CONTROL_COOKIE_PATH", `connect cookie must set Path=${expectedPath}`);
  assertEvidence(!attributes.has("domain"), "UI_CONTROL_COOKIE_DOMAIN", "connect cookie must remain host-only");
  return Object.freeze({ name, sameSite, path: attributes.get("path") });
}

export function assertTlsPolicy(observation, options = {}) {
  const now = options.now ?? Date.now();
  const minimumLifetimeSeconds = options.minimumCertificateLifetimeSeconds ?? UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS;
  assertEvidence(observation && typeof observation === "object", "UI_CONTROL_TLS_POLICY", "TLS observation is required");
  assertEvidence(["TLSv1.2", "TLSv1.3"].includes(observation.protocol), "UI_CONTROL_TLS_PROTOCOL", `unsupported TLS protocol: ${observation.protocol}`);
  const cipher = boundedText(observation.cipher, "tls.cipher", 128);
  assertEvidence(!WEAK_CIPHER.test(cipher), "UI_CONTROL_TLS_CIPHER", `weak TLS cipher: ${cipher}`);
  if (observation.protocol === "TLSv1.2") {
    assertEvidence(/ECDHE/iu.test(cipher), "UI_CONTROL_TLS_CIPHER", "TLS 1.2 must use ephemeral ECDHE key exchange");
    assertEvidence(/(?:GCM|CHACHA20)/iu.test(cipher), "UI_CONTROL_TLS_CIPHER", "TLS 1.2 must use AEAD encryption");
  }
  const validTo = Date.parse(observation.certificateValidTo);
  assertEvidence(Number.isFinite(validTo), "UI_CONTROL_TLS_CERTIFICATE", "TLS certificate expiry is invalid");
  assertEvidence(validTo >= now + minimumLifetimeSeconds * 1000, "UI_CONTROL_TLS_CERTIFICATE_EXPIRY", `TLS certificate must remain valid for at least ${minimumLifetimeSeconds} seconds`);
  assertEvidence(/^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$/iu.test(observation.certificateFingerprint256 ?? ""), "UI_CONTROL_TLS_CERTIFICATE_FINGERPRINT", "peer certificate SHA-256 fingerprint is unavailable or invalid");
  return Object.freeze({
    profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
    protocol: observation.protocol,
    cipher,
    certificateValidTo: new Date(validTo).toISOString(),
    certificateFingerprint256: observation.certificateFingerprint256.toUpperCase(),
  });
}

export function deploymentSecurityPolicyReceipt() {
  return Object.freeze({
    profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
    minimumHstsMaxAgeSeconds: UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
    minimumCertificateLifetimeSeconds: UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  });
}
