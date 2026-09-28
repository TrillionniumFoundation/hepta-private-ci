import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

test("bundle validation emits a structured fail-closed receipt", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const directory = mkdtempSync(join(tmpdir(), "ui-control-external-bundle-"));
  try {
    execFileSync("git", ["init", "-q"], { cwd: directory });
    execFileSync("git", ["config", "user.name", "ui.control test"], { cwd: directory });
    execFileSync("git", ["config", "user.email", "ui-control-test@example.invalid"], { cwd: directory });
    writeFileSync(join(directory, "marker.txt"), "candidate\n");
    execFileSync("git", ["add", "marker.txt"], { cwd: directory });
    execFileSync("git", ["commit", "-q", "-m", "candidate"], { cwd: directory });
    const output = join(directory, "bundle.json");
    const result = spawnSync(
      process.execPath,
      [resolve(root, "qualification/ui-control/validate-external-evidence.mjs"), output],
      { cwd: directory, env: { ...process.env, HEPTA_UI_CONTROL_BASE_URL: "", HEPTA_UI_CONTROL_DEPLOYMENT_ID: "" }, encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    const receipt = JSON.parse(readFileSync(output, "utf8"));
    assert.equal(receipt.schema, "hepta.ui-control.external-evidence-bundle.v1");
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.claims.productionDeploymentApproved, false);
    assert.equal(receipt.claims.releaseAuthorized, false);
    assert.equal(receipt.failure.code, "UI_CONTROL_EXTERNAL_INPUT_MISSING");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
