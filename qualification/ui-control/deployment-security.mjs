#!/usr/bin/env node
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const required = name => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const sha256 = value => createHash("sha256").update(value).digest("hex");
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();

const rawBase = required("HEPTA_UI_CONTROL_BASE_URL");
const cookie = required("HEPTA_UI_CONTROL_COOKIE");
const csrfToken = required("HEPTA_UI_CONTROL_CSRF_TOKEN");
const base = new URL(rawBase);
assert(base.protocol === "https:", "deployment qualification requires HTTPS");
assert(!base.username && !base.password && !base.search && !base.hash, "base URL contains forbidden components");
base.pathname = base.pathname.replace(/\/+$/, "");
const origin = base.origin;
const rootUrl = new URL(`${base.pathname || ""}/`, origin);
const apiBase = new URL(`${base.pathname || ""}/api/ui-control/v1/`, origin);
const output = process.argv[2] ? resolve(process.argv[2]) : null;
const buildManifestText = await readFile(
  resolve(process.env.HEPTA_UI_CONTROL_BUILD_MANIFEST || "apps/hepta-control-ui/dist/build-manifest.json"),
  "utf8",
);

async function request(url, options = {}) {
  const response = await fetch(url, {
    redirect: "manual",
    cache: "no-store",
    ...options,
    headers: {
      accept: "application/json",
      cookie,
      ...(options.headers || {}),
    },
  });
  assert(!(response.status >= 300 && response.status < 400), `${url}: redirects are forbidden`);
  assert(response.headers.get("access-control-allow-origin") !== "*", `${url}: wildcard CORS is forbidden`);
  return response;
}

async function json(response, label) {
  const contentType = response.headers.get("content-type") || "";
  assert(/^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/iu.test(contentType), `${label}: JSON content type required`);
  return response.json();
}

const root = await request(rootUrl, { headers: { accept: "text/html" } });
assert(root.ok, `root: expected 2xx, got ${root.status}`);
const csp = root.headers.get("content-security-policy") || "";
for (const directive of ["default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'"]) {
  assert(csp.includes(directive), `root: CSP missing ${directive}`);
}
const hsts = root.headers.get("strict-transport-security") || "";
assert(/(?:^|;)\s*max-age=\d+/iu.test(hsts), "root: HSTS max-age is required");
assert((root.headers.get("x-content-type-options") || "").toLowerCase() === "nosniff", "root: nosniff is required");
assert((root.headers.get("x-frame-options") || "").toUpperCase() === "DENY", "root: X-Frame-Options DENY is required");
assert((root.headers.get("referrer-policy") || "").toLowerCase() === "no-referrer", "root: no-referrer is required");
assert((root.headers.get("cross-origin-opener-policy") || "").toLowerCase() === "same-origin", "root: COOP same-origin is required");
assert((root.headers.get("cross-origin-resource-policy") || "").toLowerCase() === "same-origin", "root: CORP same-origin is required");

const connectBody = JSON.stringify({
  protocolVersion: "hepta.ui-control.v1",
  client: "hepta-control-ui-external-qualification",
  requestedCapabilities: ["runtime.read", "runtime.request", "runtime.start", "runtime.stop"],
});
const connectUrl = new URL("session/connect", apiBase);
const missingCsrf = await request(connectUrl, {
  method: "POST",
  headers: { origin, "content-type": "application/json" },
  body: connectBody,
});
assert([401, 403].includes(missingCsrf.status), `connect without CSRF must fail closed, got ${missingCsrf.status}`);

const attackerOrigin = "https://attacker.invalid";
const wrongOrigin = await request(connectUrl, {
  method: "POST",
  headers: {
    origin: attackerOrigin,
    "content-type": "application/json",
    "x-hepta-csrf-token": csrfToken,
  },
  body: connectBody,
});
assert([401, 403].includes(wrongOrigin.status), `cross-origin connect must fail closed, got ${wrongOrigin.status}`);
assert(wrongOrigin.headers.get("access-control-allow-origin") !== attackerOrigin, "attacker Origin was reflected");

const connectedResponse = await request(connectUrl, {
  method: "POST",
  headers: {
    origin,
    "content-type": "application/json",
    "x-hepta-csrf-token": csrfToken,
  },
  body: connectBody,
});
assert(connectedResponse.ok, `connect: expected success, got ${connectedResponse.status}`);
const setCookies = typeof connectedResponse.headers.getSetCookie === "function"
  ? connectedResponse.headers.getSetCookie()
  : [connectedResponse.headers.get("set-cookie")].filter(Boolean);
assert(setCookies.length > 0, "connect: an observed Set-Cookie is required to qualify cookie policy");
for (const value of setCookies) {
  assert(/;\s*Secure(?:;|$)/iu.test(value), "connect cookie must be Secure");
  assert(/;\s*HttpOnly(?:;|$)/iu.test(value), "connect cookie must be HttpOnly");
  assert(/;\s*SameSite=(?:Strict|Lax)(?:;|$)/iu.test(value), "connect cookie must set SameSite=Strict or Lax");
}
const session = await json(connectedResponse, "connect");
assert(session.authenticated === true, "connect: authenticated session not established");
assert(typeof session.sessionId === "string" && session.sessionId.length > 0, "connect: sessionId missing");
assert(Number.isSafeInteger(session.connectionGeneration) && session.connectionGeneration > 0, "connect: connectionGeneration invalid");

const viewResponse = await request(new URL("view", apiBase), {
  method: "POST",
  headers: { origin, "content-type": "application/json" },
  body: JSON.stringify({
    sessionId: session.sessionId,
    connectionGeneration: session.connectionGeneration,
  }),
});
assert(viewResponse.ok, `view: expected success, got ${viewResponse.status}`);
await json(viewResponse, "view");

const operationWithoutCsrf = await request(new URL("operations", apiBase), {
  method: "POST",
  headers: { origin, "content-type": "application/json" },
  body: "{}",
});
assert([401, 403].includes(operationWithoutCsrf.status), `mutation without CSRF must fail before semantic admission, got ${operationWithoutCsrf.status}`);

const closeResponse = await request(new URL("session/close", apiBase), {
  method: "POST",
  headers: {
    origin,
    "content-type": "application/json",
    "x-hepta-csrf-token": csrfToken,
  },
  body: JSON.stringify({
    sessionId: session.sessionId,
    connectionGeneration: session.connectionGeneration,
  }),
});
assert(closeResponse.ok, `close: expected success, got ${closeResponse.status}`);

const receipt = {
  schema: "hepta.ui-control.deployment-security-receipt.v1",
  status: "passed",
  source: {
    sha: command("git", "rev-parse", "HEAD"),
    tree: command("git", "rev-parse", "HEAD^{tree}"),
    browserBuildManifestSha256: sha256(buildManifestText),
  },
  deployment: {
    origin,
    observedAt: new Date().toISOString(),
  },
  checks: [
    "https",
    "csp",
    "hsts",
    "no-wildcard-cors",
    "cross-origin-rejection",
    "csrf-before-connect",
    "authenticated-connect",
    "secure-httponly-samesite-cookie",
    "authenticated-view",
    "mutation-csrf-precheck",
    "authenticated-close",
  ],
  claims: {
    deployedSecurityObserved: true,
    realBackendSemanticsQualified: false,
    independentAcceptanceSigned: false,
    productionDeploymentApproved: false,
  },
};
const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
if (output) await writeFile(output, serialized);
process.stdout.write(serialized);