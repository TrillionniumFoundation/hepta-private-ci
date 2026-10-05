import test from "node:test";
import assert from "node:assert/strict";
import {
  UI_CONTROL_BROWSER_BUILD_SCHEMA,
  UI_CONTROL_CSRF_SUBSTITUTION_KIND,
  assertRuntimeSubstitutionManifest,
  verifyCsrfBootstrapAsset,
  verifyExactAsset,
} from "../../../qualification/ui-control/deployment-asset-invariants.mjs";

const token = "csrf-token_0123456789-ABCDEF";
const candidate = Buffer.from('<!doctype html>\n<meta name="csrf-token" content="">\n<main>safe</main>\n');
const deployed = Buffer.from(`<!doctype html>\n<meta name="csrf-token" content="${token}">\n<main>safe</main>\n`);

test("browser build schema declares one bounded CSRF bootstrap substitution", () => {
  assert.equal(UI_CONTROL_BROWSER_BUILD_SCHEMA, "hepta.ui-control.browser-build.v2");
  assert.deepEqual(
    assertRuntimeSubstitutionManifest({ "index.html": [UI_CONTROL_CSRF_SUBSTITUTION_KIND] }),
    { "index.html": [UI_CONTROL_CSRF_SUBSTITUTION_KIND] },
  );
  assert.throws(
    () => assertRuntimeSubstitutionManifest({ "index.html": [UI_CONTROL_CSRF_SUBSTITUTION_KIND], "main.js": ["other"] }),
    error => error.code === "UI_CONTROL_BUILD_SUBSTITUTIONS",
  );
});

test("deployment may replace only the exact CSRF meta content slot", () => {
  const result = verifyCsrfBootstrapAsset(candidate, deployed, token);
  assert.equal(result.kind, UI_CONTROL_CSRF_SUBSTITUTION_KIND);
  assert.equal(result.candidateSha256, result.canonicalDeployedSha256);
  assert.throws(
    () => verifyCsrfBootstrapAsset(candidate, Buffer.from(deployed.toString("utf8").replace("safe", "changed")), token),
    error => error.code === "UI_CONTROL_DEPLOYED_ASSET_DRIFT",
  );
  assert.throws(
    () => verifyCsrfBootstrapAsset(candidate, deployed, "another-token_0123456789"),
    error => error.code === "UI_CONTROL_CSRF_BOOTSTRAP_BINDING",
  );
  assert.throws(
    () => verifyCsrfBootstrapAsset(candidate, Buffer.concat([deployed, deployed]), token),
    error => error.code === "UI_CONTROL_CSRF_BOOTSTRAP_SLOT",
  );
});

test("all non-bootstrap assets remain byte exact", () => {
  const bytes = Buffer.from("export const value = 1;\n");
  assert.equal(verifyExactAsset(bytes, Buffer.from(bytes), "main.js").kind, "exact-bytes-v1");
  assert.throws(
    () => verifyExactAsset(bytes, Buffer.from("export const value = 2;\n"), "main.js"),
    error => error.code === "UI_CONTROL_DEPLOYED_ASSET_DRIFT",
  );
});
