import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildProjections, discoverRustTestFiles, REPO_ROOT, verifyGenerated } from "../generate.mjs";

test("canonical API projection is Rust-only and closed against historical inheritance", () => {
  const api = buildProjections().get("api-registry.json");
  assert.equal(api.canonicalImplementation.language, "rust");
  assert.equal(api.historyInheritance.allowed, false);
  assert.deepEqual(
    api.operations.map((operation) => operation.id),
    [
      "connect_runtime",
      "render_runtime_view",
      "request_platform_capability",
      "reconcile_pending",
      "apply_shell_update",
      "confirm_running_update",
    ],
  );
  assert.ok(
    api.historyInheritance.retiredEntrypoints.every((path) => path.endsWith(".js")),
  );
});

test("capability registry binds every admitted action to final-use and terminal receipts", () => {
  const registry = buildProjections().get("capability-registry.json");
  assert.deepEqual(
    registry.actions.map((action) => action.id),
    ["open_path", "reveal_path", "copy_text", "notify"],
  );
  assert.ok(
    registry.actions.every(
      (action) => action.finalUseGrantRequired && action.terminalReceiptRequired,
    ),
  );
  assert.deepEqual(registry.durablePhases, [
    "prepared",
    "invoking",
    "indeterminate",
    "observation_closed",
    "terminal",
  ]);
});

test("platform projection retains all three product targets and honest external gates", () => {
  const matrix = buildProjections().get("platform-matrix.json");
  assert.deepEqual(
    matrix.platforms.map((platform) => platform.id),
    ["linux", "macos", "windows"],
  );
  assert.equal(matrix.windowPolicy.singleProcess, true);
  assert.ok(matrix.platforms.every((platform) => platform.signingState.includes("gate")));
  assert.ok(matrix.physicalAcceptanceGates.includes("screen_reader"));
  assert.equal(
    matrix.keyboardAndFocusAcceptance,
    "pending executed behavioral and physical evidence",
  );
});

test("test registry is source-discovered and has no duplicate paths", () => {
  const registry = buildProjections().get("test-registry.json");
  const paths = registry.files.map((file) => file.path);
  assert.equal(new Set(paths).size, paths.length);
  assert.equal(registry.sourceDiscovery.fileCount, paths.length);
  assert.ok(paths.includes("apps/hepta-native/tests/journal_regressions.rs"));
  assert.ok(paths.includes("apps/hepta-native/tests/update_product.rs"));
  assert.ok(paths.includes("apps/hepta-native/src/ui/input_event_tests.rs"));
  assert.deepEqual(
    registry.files.find((file) => file.path === "codex-rs/utils/private-state/src/windows.rs"),
    {
      path: "codex-rs/utils/private-state/src/windows.rs",
      role: "unit_test",
      ownerPackage: "codex-utils-private-state",
    },
  );
  const command = registry.profiles.find((profile) => profile.id === "gateway_authority").command;
  for (const owner of [
    "codex-hepta-native-gateway",
    "codex-hepta-contracts",
    "codex-hepta-private-state",
    "codex-utils-private-state",
  ]) {
    assert.ok(command.includes(`-p ${owner} `));
  }

  const fixture = mkdtempSync(join(tmpdir(), "hepta-native-test-discovery-"));
  try {
    for (const root of registry.sourceDiscovery.roots) {
      mkdirSync(join(fixture, root), { recursive: true });
    }
    const inline = "codex-rs/utils/private-state/src/platform_adapter.rs";
    writeFileSync(
      join(fixture, inline),
      "#[cfg(windows)]\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn owned_handles_are_fenced() {}\n}\n",
    );
    writeFileSync(join(fixture, "codex-rs/utils/private-state/src/lib.rs"), "pub fn production_only() {}\n");
    assert.deepEqual(discoverRustTestFiles(fixture), [{
      path: inline,
      role: "unit_test",
      ownerPackage: "codex-utils-private-state",
    }]);
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});

test("committed projections are exactly reproducible", () => {
  assert.doesNotThrow(() => verifyGenerated());
});

test("running update confirmation remains a crate-private boundary", () => {
  const api = buildProjections().get("api-registry.json");
  const operation = api.operations.find((item) => item.id === "confirm_running_update");
  assert.equal(operation.symbol, "pub(crate) fn confirm_running_process(");
  assert.equal(operation.visibility, "crate");
});

test("local receipt binds the current workflow without manufacturing execution evidence", () => {
  const output = mkdtempSync(join(tmpdir(), "hepta-native-projection-receipt-"));
  try {
    const path = join(output, "receipt.json");
    execFileSync(
      process.execPath,
      [join(REPO_ROOT, "tools/ui-native-projections/receipt.mjs"), "--out", path],
      { cwd: REPO_ROOT },
    );
    const receipt = JSON.parse(readFileSync(path, "utf8"));
    const workflow = ".github/workflows/ui-native-qualification.yml";
    assert.deepEqual(receipt.qualificationWorkflow, {
      path: workflow,
      sha256: createHash("sha256")
        .update(readFileSync(join(REPO_ROOT, workflow)))
        .digest("hex"),
    });
    assert.equal(
      receipt.workingTreeClean,
      execFileSync("git", ["status", "--porcelain"], {
        cwd: REPO_ROOT,
        encoding: "utf8",
      }).trim().length === 0,
    );
    assert.equal(receipt.claims.workflowExecutionObserved, false);
    assert.equal(receipt.claims.automatedKeyboardFocusAccepted, false);
    assert.equal(receipt.claims.physicalAccessibilityAccepted, false);
    assert.equal(receipt.claims.releaseAuthorized, false);
  } finally {
    rmSync(output, { recursive: true, force: true });
  }
});
