import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const workflow = readFileSync(
  `${root}.github/workflows/ui-control-qualification-observer.yml`,
  "utf8",
);
const schema = JSON.parse(
  readFileSync(
    `${root}qualification/ui-control/QUALIFICATION_WORKFLOW_OBSERVATION_SCHEMA.json`,
    "utf8",
  ),
);

test("qualification observer is secretless, metadata-only, and non-authoritative", () => {
  assert.match(workflow, /workflow_run:/u);
  assert.match(workflow, /ui\.control exact-head qualification/u);
  assert.doesNotMatch(workflow, /workflow_dispatch:/u);
  assert.match(workflow, /permissions:\n  actions: read/u);
  assert.doesNotMatch(workflow, /contents:\s*(?:read|write)/u);
  assert.doesNotMatch(workflow, /\$\{\{\s*secrets\./u);
  assert.doesNotMatch(workflow, /actions\/checkout@/u);
  assert.doesNotMatch(workflow, /download-artifact/u);
  assert.doesNotMatch(workflow, /pull_request_target/u);
  assert.match(workflow, /attempts\/\{attempt\}/u);
  assert.match(workflow, /jobInventoryComplete/u);
  assert.match(workflow, /artifactInventoryComplete/u);
  assert.match(workflow, /acceptedEvidence": False/u);
  assert.match(workflow, /UI_CONTROL_QUALIFICATION_OBSERVER_INFRASTRUCTURE/u);
  assert.match(workflow, /if: always\(\)/u);
  assert.match(workflow, /Upload the immutable qualification-run observation/u);
});

test("qualification workflow observation schema forbids acceptance claims", () => {
  assert.equal(
    schema.$id,
    "hepta.ui-control.qualification-workflow-observation.v1",
  );
  assert.equal(schema.properties.acceptedEvidence.const, false);
  assert.equal(schema.properties.jobInventory.maxItems, 1000);
  assert.equal(schema.properties.artifactInventory.maxItems, 1000);
  for (const property of Object.values(schema.properties.claims.properties)) {
    assert.equal(property.const, false);
  }
});
