import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

test("qualification truth and v2 implementation map are consistent", () => {
  const script = resolve(import.meta.dirname, "../scripts/qualification-state.mjs");
  const run = spawnSync(process.execPath, [script, "--check"], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr);
});
