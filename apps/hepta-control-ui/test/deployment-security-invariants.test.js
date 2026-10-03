import test from "node:test";
import assert from "node:assert/strict";
import {
  UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
  assertContentSecurityPolicy,
  assertCookiePolicy,
  assertHstsPolicy,
  assertNoStoreCachePolicy,
  assertPermissionsPolicy,
  assertTlsPolicy,
  deploymentSecurityPolicyReceipt,
} from "../../../qualification/ui-control/deployment-security-invariants.mjs";

const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "connect-src 'self'",
  "img-src 'self' data:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const fingerprint = Array.from({ length: 32 }, () => "AA").join(":");

test("deployment security policy metadata is stable and explicit", () => {
  assert.deepEqual(deploymentSecurityPolicyReceipt(), {
    profile: UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
    minimumHstsMaxAgeSeconds: UI_CONTROL_MINIMUM_HSTS_MAX_AGE_SECONDS,
    minimumCertificateLifetimeSeconds: UI_CONTROL_MINIMUM_CERTIFICATE_LIFETIME_SECONDS,
  });
});

test("CSP validation is exact rather than substring based", () => {
  assert.doesNotThrow(() => assertContentSecurityPolicy(`${csp}; upgrade-insecure-requests`));
  assert.throws(
    () => assertContentSecurityPolicy(csp.replace("default-src 'self'", "default-src 'selfish'")),
    error => error.code === "UI_CONTROL_CSP_DIRECTIVE",
  );
  assert.throws(
    () => assertContentSecurityPolicy(`${csp}; script-src 'self'`),
    error => error.code === "UI_CONTROL_CSP_DUPLICATE",
  );
  assert.throws(
    () => assertContentSecurityPolicy(csp.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")),
    error => error.code === "UI_CONTROL_CSP_UNSAFE_SOURCE",
  );
  assert.throws(
    () => assertContentSecurityPolicy(`${csp}; script-src-elem 'self'`),
    error => error.code === "UI_CONTROL_CSP_DIRECTIVE",
  );
});

test("HSTS and cache policy reject superficially matching weak values", () => {
  assert.equal(assertHstsPolicy("max-age=31536000; includeSubDomains").maxAgeSeconds, 31_536_000);
  assert.throws(() => assertHstsPolicy("max-age=0"), error => error.code === "UI_CONTROL_HSTS_MAX_AGE");
  assert.doesNotThrow(() => assertNoStoreCachePolicy("private, no-store, max-age=0"));
  assert.throws(() => assertNoStoreCachePolicy("public, no-store"), error => error.code === "UI_CONTROL_CACHE_CONTROL");
  assert.throws(() => assertNoStoreCachePolicy("no-store, max-age=60"), error => error.code === "UI_CONTROL_CACHE_CONTROL");
  assert.throws(() => assertNoStoreCachePolicy("no-store=yes"), error => error.code === "UI_CONTROL_CACHE_CONTROL");
});

test("Permissions-Policy disables every sensitive feature exactly", () => {
  assert.doesNotThrow(() => assertPermissionsPolicy("camera=(), microphone=(), geolocation=(), payment=()"));
  assert.throws(
    () => assertPermissionsPolicy("camera=(self), microphone=(), geolocation=(), payment=()"),
    error => error.code === "UI_CONTROL_PERMISSIONS_POLICY",
  );
});

test("cookie policy rejects scope expansion and ambiguous duplicate attributes", () => {
  assert.deepEqual(
    assertCookiePolicy("hepta_session=opaque; Secure; HttpOnly; SameSite=Strict; Path=/console", "/console"),
    { name: "hepta_session", sameSite: "strict", path: "/console" },
  );
  assert.throws(
    () => assertCookiePolicy("hepta_session=opaque; Secure; Secure; HttpOnly; SameSite=Lax; Path=/", "/"),
    error => error.code === "UI_CONTROL_COOKIE_DUPLICATE_ATTRIBUTE",
  );
  assert.throws(
    () => assertCookiePolicy("hepta_session=opaque; Secure; HttpOnly; SameSite=None; Path=/", "/"),
    error => error.code === "UI_CONTROL_COOKIE_SAMESITE",
  );
  assert.throws(
    () => assertCookiePolicy("hepta_session=opaque; Secure; HttpOnly; SameSite=Strict; Path=/; Domain=example.test", "/"),
    error => error.code === "UI_CONTROL_COOKIE_DOMAIN",
  );
});

test("TLS policy requires modern ciphers and certificate runway", () => {
  const now = Date.parse("2026-09-28T00:00:00Z");
  assert.equal(
    assertTlsPolicy({
      protocol: "TLSv1.3",
      cipher: "TLS_AES_256_GCM_SHA384",
      certificateValidTo: "2026-10-28T00:00:00Z",
      certificateFingerprint256: fingerprint,
    }, { now }).profile,
    UI_CONTROL_DEPLOYMENT_SECURITY_PROFILE,
  );
  assert.throws(
    () => assertTlsPolicy({
      protocol: "TLSv1.2",
      cipher: "ECDHE-RSA-AES256-SHA",
      certificateValidTo: "2026-10-28T00:00:00Z",
      certificateFingerprint256: fingerprint,
    }, { now }),
    error => error.code === "UI_CONTROL_TLS_CIPHER",
  );
  assert.throws(
    () => assertTlsPolicy({
      protocol: "TLSv1.3",
      cipher: "TLS_AES_256_GCM_SHA384",
      certificateValidTo: "2026-09-30T00:00:00Z",
      certificateFingerprint256: fingerprint,
    }, { now }),
    error => error.code === "UI_CONTROL_TLS_CERTIFICATE_EXPIRY",
  );
});


test("Rust CSP permits only explicit first-party WASM compilation", () => {
  const runtime = { browserRuntime: "rust-wasm-v1" };
  const wasm = csp.replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'");
  assert.doesNotThrow(() => assertContentSecurityPolicy(wasm, runtime));
  assert.throws(() => assertContentSecurityPolicy(wasm));
  assert.throws(() => assertContentSecurityPolicy(csp, runtime));
  assert.throws(() => assertContentSecurityPolicy(wasm, { browserRuntime: "unknown" }));
  for (const source of ["'unsafe-eval'", "'unsafe-inline'", "https://cdn.invalid", "blob:", "*"]) {
    assert.throws(() => assertContentSecurityPolicy(wasm.replace("'wasm-unsafe-eval'", source), runtime));
    assert.throws(() => assertContentSecurityPolicy(`${wasm} ${source}`, runtime));
  }
  assert.throws(() => assertContentSecurityPolicy(wasm.replace("style-src 'self'", "style-src 'self' 'wasm-unsafe-eval'"), runtime));
});
