import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../..");
const doc = (name) => resolve(root, "docs/modules/browser.servo", name);
const read = (name) => readFileSync(doc(name));
const json = (name) => JSON.parse(read(name));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const manifest = json("QUALIFICATION.json");
const map = json("IMPLEMENTATION_MAP_V2.json");
const falseClaims = [
  "repositoryControlledSourceBoundaryGapsClosed", "productExecutionComplete",
  "deploymentQualificationComplete", "independentAcceptanceComplete",
  "productionImplementation", "productExecutionProved", "independentAcceptance",
  "activation", "promotion", "release",
];

function invariant(ok, message) { if (!ok) throw new Error(message); }
function validate() {
  invariant(manifest.schema === "hepta.browser.servo-qualification.v1", "qualification schema");
  invariant(manifest.sourceBinding?.mode === "runtime-exact-source", "source binding");
  invariant(map.schemaVersion === 2 && map.canonicalQualification.endsWith("QUALIFICATION.json"), "map v2");
  invariant(map.operations.length === 7, "seven mapped operations");
  for (const key of falseClaims) {
    invariant(manifest.claims[key] === false, `manifest claim ${key}`);
    invariant(map.claimBoundary[key] === false, `map claim ${key}`);
  }
  const ids = new Set(manifest.gates.map((gate) => gate.id));
  for (const id of ["browser_node_suite", "agentd_rust_composition", "servo_locked_worker", "workspace_integration_check"]) {
    invariant(ids.has(id), `missing gate ${id}`);
  }
  return manifest;
}

function receipt() {
  validate();
  const lane = process.env.QUALIFICATION_LANE;
  invariant(["exact-head", "synthetic-merge"].includes(lane), "registered lane");
  const result = {
    schema: "hepta.browser.servo-qualification-receipt.v1",
    lane,
    sourceSha: process.env.EFFECTIVE_SOURCE_SHA,
    sourceTree: process.env.EFFECTIVE_SOURCE_TREE,
    runId: process.env.GITHUB_RUN_ID,
    runAttempt: process.env.GITHUB_RUN_ATTEMPT,
    qualificationSha256: sha256(read("QUALIFICATION.json")),
    implementationMapSha256: sha256(read("IMPLEMENTATION_MAP_V2.json")),
    releaseManifestSha256: sha256(read("RELEASE_MANIFEST.json")),
    artifactIndexSha256: sha256(read("ARTIFACT_PROVENANCE_INDEX.json")),
    claims: Object.fromEntries(falseClaims.map((key) => [key, false])),
    selfAuthorizing: false,
  };
  result.receiptDigest = sha256(Buffer.from(JSON.stringify(result)));
  writeFileSync(process.argv[3] ?? "qualification-receipt.json", `${JSON.stringify(result, null, 2)}\n`);
}

validate();
if (process.argv[2] === "--receipt") receipt();
else if (process.argv[2] !== "--check") throw new Error("use --check or --receipt");
