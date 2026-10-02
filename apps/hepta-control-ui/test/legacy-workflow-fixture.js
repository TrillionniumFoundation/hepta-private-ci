import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";

const base = new URL("./fixtures/legacy-workflows/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("ORACLE.json", base), "utf8"));
export function readLegacyWorkflow(name) {
  assert.equal(manifest.productRuntime, false);
  assert.equal(manifest.workflowActivated, false);
  assert.equal(manifest.sourceCommit, "0063323c884d4ac0abb0605dce9c8ca914fbd86a");
  const entry = manifest.files.find(item => item.file === name);
  assert.ok(entry, "workflow must belong to the pinned historical oracle");
  const bytes = readFileSync(new URL(entry.file, base));
  assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
  return bytes.toString("utf8");
}
