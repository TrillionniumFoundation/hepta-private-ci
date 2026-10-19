#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { isIP } from "node:net";
import { dirname, resolve } from "node:path";
import { connect as tlsConnect } from "node:tls";
import {
  assertRuntimeSubstitutionManifest,
  UI_CONTROL_BROWSER_BUILD_SCHEMA,
  verifyCsrfBootstrapAsset,
  verifyExactAsset,
} from "./deployment-asset-invariants.mjs";
import {
  assertContentSecurityPolicy,
  assertCookiePolicy,
  assertHstsPolicy,
  assertNoStoreCachePolicy,
  assertPermissionsPolicy,
  assertTlsPolicy,
  deploymentSecurityPolicyReceipt,
} from "./deployment-security-invariants.mjs";
import {
  assertEvidence,
  deploymentSubject,
  safeFailure,
  sha256,
} from "./external-evidence-lib.mjs";

const required = name => {
  const value = process.env[name];
  if (!value) {
    const error = new Error(`${name} is required`);
    error.code = "UI_CONTROL_EXTERNAL_INPUT_MISSING";
    throw error;
  }
  return value;
};
const command = (...args) => execFileSync(args[0], args.slice(1), { encoding: "utf8" }).trim();
const output = process.argv[2] ? resolve(process.argv[2]) : null;
const source = {
  sha: command("git", "rev-parse", "HEAD"),
  tree: command("git", "rev-parse", "HEAD^{tree}"),
};
let stage = "initialization";
let deployment = null;
const checks = [];

async function emit(receipt) {
  const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
  if (output) await writeFile(output, serialized);
  process.stdout.write(serialized);
}

async function observeTls(base) {
  return new Promise((resolveTls, rejectTls) => {
    const socket = tlsConnect({
      host: base.hostname,
      port: Number(base.port || 443),
      servername: isIP(base.hostname) ? undefined : base.hostname,
      rejectUnauthorized: true,
      minVersion: "TLSv1.2",
    });
    const timer = setTimeout(() => {
      socket.destroy();
      const error = new Error("TLS handshake timed out");
      error.code = "UI_CONTROL_TLS_TIMEOUT";
      rejectTls(error);
    }, 10_000);
    socket.once("secureConnect", () => {
      clearTimeout(timer);
      try {
        assertEvidence(socket.authorized, "UI_CONTROL_TLS_UNAUTHORIZED", socket.authorizationError || "TLS peer was not authorized");
        const certificate = socket.getPeerCertificate();
        assertEvidence(certificate && certificate.valid_to, "UI_CONTROL_TLS_CERTIFICATE", "peer certificate metadata is unavailable");
        resolveTls(assertTlsPolicy({
          protocol: socket.getProtocol(),
          cipher: socket.getCipher()?.standardName || socket.getCipher()?.name || null,
          certificateValidTo: certificate.valid_to,
          certificateFingerprint256: certificate.fingerprint256,
        }));
      } catch (error) {
        rejectTls(error);
      } finally {
        socket.end();
      }
    });
    socket.once("error", error => {
      clearTimeout(timer);
      rejectTls(error);
    });
  });
}

try {
  const cookie = required("HEPTA_UI_CONTROL_COOKIE");
  const csrfToken = required("HEPTA_UI_CONTROL_CSRF_TOKEN");
  deployment = deploymentSubject(
    required("HEPTA_UI_CONTROL_BASE_URL"),
    required("HEPTA_UI_CONTROL_DEPLOYMENT_ID"),
  );
  const { base, subject, digest: backendDeploymentDigest } = deployment;
  const origin = subject.origin;
  const prefix = subject.basePath === "/" ? "" : subject.basePath;
  const rootUrl = new URL(`${prefix}/`, origin);
  const apiBase = new URL(`${prefix}/api/ui-control/v1/`, origin);
  const buildManifestPath = resolve(
    process.env.HEPTA_UI_CONTROL_BUILD_MANIFEST || "apps/hepta-control-ui/dist/build-manifest.json",
  );
  const buildRoot = dirname(buildManifestPath);
  const buildManifestText = await readFile(buildManifestPath, "utf8");
  const buildManifest = JSON.parse(buildManifestText);
  assertEvidence(
    buildManifest.schema === UI_CONTROL_BROWSER_BUILD_SCHEMA,
    "UI_CONTROL_BUILD_MANIFEST_SCHEMA",
    "unsupported browser build manifest",
  );
  assertRuntimeSubstitutionManifest(buildManifest.runtimeSubstitutions);

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
    assertEvidence(!(response.status >= 300 && response.status < 400), "UI_CONTROL_DEPLOYMENT_REDIRECT", `${url}: redirects are forbidden`);
    assertEvidence(response.headers.get("access-control-allow-origin") !== "*", "UI_CONTROL_CORS_WILDCARD", `${url}: wildcard CORS is forbidden`);
    return response;
  }

  async function json(response, label) {
    const contentType = response.headers.get("content-type") || "";
    assertEvidence(/^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/iu.test(contentType), "UI_CONTROL_JSON_CONTENT_TYPE", `${label}: JSON content type required`);
    return response.json();
  }

  stage = "tls";
  const tls = await observeTls(base);
  checks.push("tls-1.2-or-newer-and-valid-certificate");

  stage = "root-security-headers";
  const root = await request(rootUrl, { headers: { accept: "text/html" } });
  assertEvidence(root.ok, "UI_CONTROL_ROOT_HTTP", `root: expected 2xx, got ${root.status}`);
  assertContentSecurityPolicy(root.headers.get("content-security-policy") || "");
  assertHstsPolicy(root.headers.get("strict-transport-security") || "");
  assertEvidence((root.headers.get("x-content-type-options") || "").toLowerCase() === "nosniff", "UI_CONTROL_NOSNIFF", "root: nosniff is required");
  assertEvidence((root.headers.get("x-frame-options") || "").toUpperCase() === "DENY", "UI_CONTROL_FRAME_OPTIONS", "root: X-Frame-Options DENY is required");
  assertEvidence((root.headers.get("referrer-policy") || "").toLowerCase() === "no-referrer", "UI_CONTROL_REFERRER_POLICY", "root: no-referrer is required");
  assertEvidence((root.headers.get("cross-origin-opener-policy") || "").toLowerCase() === "same-origin", "UI_CONTROL_COOP", "root: COOP same-origin is required");
  assertEvidence((root.headers.get("cross-origin-resource-policy") || "").toLowerCase() === "same-origin", "UI_CONTROL_CORP", "root: CORP same-origin is required");
  assertPermissionsPolicy(root.headers.get("permissions-policy") || "");
  assertNoStoreCachePolicy(root.headers.get("cache-control") || "");
  checks.push("csp", "hsts", "no-store", "browser-isolation-headers");

  stage = "asset-identity";
  const rootBytes = Buffer.from(await root.arrayBuffer());
  const expectedRoot = buildManifest.files?.["index.html"];
  assertEvidence(expectedRoot, "UI_CONTROL_ASSET_MANIFEST", "build manifest is missing index.html");
  const candidateRootBytes = await readFile(resolve(buildRoot, "index.html"));
  assertEvidence(
    candidateRootBytes.length === expectedRoot.bytes && sha256(candidateRootBytes) === expectedRoot.sha256,
    "UI_CONTROL_BUILD_MANIFEST_DRIFT",
    "candidate index.html does not match its build manifest",
  );
  const rootVerification = verifyCsrfBootstrapAsset(candidateRootBytes, rootBytes, csrfToken);
  let verifiedAssetCount = 1;
  for (const [relativePath, expected] of Object.entries(buildManifest.files || {})) {
    if (relativePath === "index.html") continue;
    const candidateBytes = await readFile(resolve(buildRoot, relativePath));
    assertEvidence(
      candidateBytes.length === expected.bytes && sha256(candidateBytes) === expected.sha256,
      "UI_CONTROL_BUILD_MANIFEST_DRIFT",
      `${relativePath}: candidate bytes do not match the build manifest`,
    );
    const response = await request(new URL(`${prefix}/${relativePath}`, origin), { headers: { accept: "*/*" } });
    assertEvidence(response.ok, "UI_CONTROL_ASSET_HTTP", `${relativePath}: expected 2xx, got ${response.status}`);
    const deployedBytes = Buffer.from(await response.arrayBuffer());
    verifyExactAsset(candidateBytes, deployedBytes, relativePath);
    verifiedAssetCount += 1;
  }
  checks.push("bounded-csrf-bootstrap-substitution", "exact-deployed-asset-manifest");

  const connectBody = JSON.stringify({
    protocolVersion: "hepta.ui-control.v1",
    client: "hepta-control-ui-external-qualification",
    requestedCapabilities: ["runtime.read", "runtime.request", "runtime.start", "runtime.stop"],
  });
  const connectUrl = new URL("session/connect", apiBase);

  stage = "csrf-and-cors";
  const missingCsrf = await request(connectUrl, {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: connectBody,
  });
  assertEvidence([401, 403].includes(missingCsrf.status), "UI_CONTROL_CSRF_PRECHECK", `connect without CSRF must fail closed, got ${missingCsrf.status}`);

  const attackerOrigin = "https://attacker.invalid";
  const preflight = await request(connectUrl, {
    method: "OPTIONS",
    headers: {
      origin: attackerOrigin,
      "access-control-request-method": "POST",
      "access-control-request-headers": "content-type,x-hepta-csrf-token",
    },
  });
  assertEvidence(preflight.headers.get("access-control-allow-origin") !== attackerOrigin, "UI_CONTROL_CORS_REFLECTION", "attacker Origin was accepted by preflight");
  const wrongOrigin = await request(connectUrl, {
    method: "POST",
    headers: {
      origin: attackerOrigin,
      "content-type": "application/json",
      "x-hepta-csrf-token": csrfToken,
    },
    body: connectBody,
  });
  assertEvidence([401, 403].includes(wrongOrigin.status), "UI_CONTROL_CROSS_ORIGIN", `cross-origin connect must fail closed, got ${wrongOrigin.status}`);
  assertEvidence(wrongOrigin.headers.get("access-control-allow-origin") !== attackerOrigin, "UI_CONTROL_CORS_REFLECTION", "attacker Origin was reflected");
  checks.push("csrf-before-connect", "cors-preflight-rejection", "cross-origin-rejection");

  stage = "authenticated-session-and-cookie";
  const connectedResponse = await request(connectUrl, {
    method: "POST",
    headers: {
      origin,
      "content-type": "application/json",
      "x-hepta-csrf-token": csrfToken,
    },
    body: connectBody,
  });
  assertEvidence(connectedResponse.ok, "UI_CONTROL_CONNECT", `connect: expected success, got ${connectedResponse.status}`);
  const setCookies = typeof connectedResponse.headers.getSetCookie === "function"
    ? connectedResponse.headers.getSetCookie()
    : [connectedResponse.headers.get("set-cookie")].filter(Boolean);
  assertEvidence(setCookies.length > 0, "UI_CONTROL_COOKIE_MISSING", "connect: an observed Set-Cookie is required to qualify cookie policy");
  const expectedCookiePath = process.env.HEPTA_UI_CONTROL_COOKIE_PATH || (prefix || "/");
  for (const value of setCookies) {
    assertCookiePolicy(value, expectedCookiePath);
  }
  const session = await json(connectedResponse, "connect");
  assertEvidence(session.authenticated === true, "UI_CONTROL_SESSION_AUTH", "connect: authenticated session not established");
  assertEvidence(typeof session.sessionId === "string" && session.sessionId.length > 0, "UI_CONTROL_SESSION_ID", "connect: sessionId missing");
  assertEvidence(Number.isSafeInteger(session.connectionGeneration) && session.connectionGeneration > 0, "UI_CONTROL_CONNECTION_GENERATION", "connect: connectionGeneration invalid");
  checks.push("authenticated-connect", "secure-httponly-samesite-host-only-cookie");

  stage = "authenticated-read-and-mutation-precheck";
  const viewResponse = await request(new URL("view", apiBase), {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify({ sessionId: session.sessionId, connectionGeneration: session.connectionGeneration }),
  });
  assertEvidence(viewResponse.ok, "UI_CONTROL_VIEW", `view: expected success, got ${viewResponse.status}`);
  await json(viewResponse, "view");
  const operationWithoutCsrf = await request(new URL("operations", apiBase), {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: "{}",
  });
  assertEvidence([401, 403].includes(operationWithoutCsrf.status), "UI_CONTROL_MUTATION_CSRF", `mutation without CSRF must fail before semantic admission, got ${operationWithoutCsrf.status}`);
  checks.push("authenticated-view", "mutation-csrf-precheck");

  stage = "authenticated-close";
  const closeResponse = await request(new URL("session/close", apiBase), {
    method: "POST",
    headers: { origin, "content-type": "application/json", "x-hepta-csrf-token": csrfToken },
    body: JSON.stringify({ sessionId: session.sessionId, connectionGeneration: session.connectionGeneration }),
  });
  assertEvidence(closeResponse.ok, "UI_CONTROL_SESSION_CLOSE", `close: expected success, got ${closeResponse.status}`);
  checks.push("authenticated-close");

  await emit({
    schema: "hepta.ui-control.deployment-security-receipt.v2",
    status: "passed",
    candidateCommit: source.sha,
    candidateTree: source.tree,
    backendDeploymentDigest,
    source: {
      ...source,
      browserBuildManifestSha256: sha256(buildManifestText),
    },
    deployment: { ...subject, observedAt: new Date().toISOString() },
    policy: deploymentSecurityPolicyReceipt(),
    tls,
    assets: {
      verifiedAssetCount,
      runtimeSubstitutions: [{ path: "index.html", kind: rootVerification.kind }],
    },
    checks,
    claims: {
      deployedSecurityObserved: true,
      exactCandidateAssetsObserved: true,
      realBackendSemanticsQualified: false,
      independentAcceptanceSigned: false,
      productionDeploymentApproved: false,
    },
  });
} catch (error) {
  await emit({
    schema: "hepta.ui-control.deployment-security-receipt.v2",
    status: "failed",
    candidateCommit: source.sha,
    candidateTree: source.tree,
    backendDeploymentDigest: deployment?.digest ?? null,
    source,
    deployment: deployment ? { ...deployment.subject, observedAt: new Date().toISOString() } : null,
    policy: deploymentSecurityPolicyReceipt(),
    checks,
    failure: safeFailure(error, stage),
    claims: {
      deployedSecurityObserved: false,
      exactCandidateAssetsObserved: false,
      realBackendSemanticsQualified: false,
      independentAcceptanceSigned: false,
      productionDeploymentApproved: false,
    },
  });
  process.exitCode = 1;
}
