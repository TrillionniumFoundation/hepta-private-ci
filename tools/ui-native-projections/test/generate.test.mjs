import test from "node:test";
import assert from "node:assert/strict";
import { buildProjections, verifyGenerated } from "../generate.mjs";

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
});

test("test registry is source-discovered and has no duplicate paths", () => {
  const registry = buildProjections().get("test-registry.json");
  const paths = registry.files.map((file) => file.path);
  assert.equal(new Set(paths).size, paths.length);
  assert.equal(registry.sourceDiscovery.fileCount, paths.length);
  assert.ok(paths.includes("apps/hepta-native/tests/journal_regressions.rs"));
  assert.ok(paths.includes("apps/hepta-native/tests/update_product.rs"));
});

test("committed projections are exactly reproducible", () => {
  assert.doesNotThrow(() => verifyGenerated());
});
