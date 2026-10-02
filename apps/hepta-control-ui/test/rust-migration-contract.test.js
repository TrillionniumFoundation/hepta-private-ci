import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JAVASCRIPT_BASELINE, validateSubject } from "../tools/rust-candidate-identity.mjs";
const source="a".repeat(40),base="b".repeat(40),evaluated="c".repeat(40),tree="d".repeat(40),sourceTree="e".repeat(40);
const merge={source,base,evaluated,tree,sourceTree,mergeTree:tree,parents:[base,source],subject:"merge"};
test("Rust subject binding rejects swapped, missing and drifted integration parents",()=>{
  assert.deepEqual(validateSubject(merge).parents,[base,source]);
  for (const parents of [[source,base],[base],["f".repeat(40),source],[base,source,evaluated]]) assert.throws(()=>validateSubject({...merge,parents}));
  assert.throws(()=>validateSubject({...merge,mergeTree:sourceTree}));
  assert.throws(()=>validateSubject({...merge,base:"refs/heads/main"}));
});
test("head receipt requires the exact source commit and its tree",()=>{
  const head={...merge,subject:"head",evaluated:source,tree:sourceTree};
  assert.equal(validateSubject(head).evaluated,source);
  assert.throws(()=>validateSubject({...head,evaluated}));
  assert.throws(()=>validateSubject({...head,tree}));
  assert.throws(()=>validateSubject({...head,subject:"unqualified"}));
});
test("workflow resolves one integration base and uses explicit Rust browser assets",async()=>{
  const workflow=await readFile(new URL("../../../.github/workflows/ui-control-rust-parity.yml",import.meta.url),"utf8");
  assert.equal((workflow.match(/git fetch --no-tags origin "\$BASE_REF"/gu)??[]).length,1);
  assert.match(workflow,/needs: identity/u);
  assert.match(workflow,/base-sha: \$\{\{ needs\.identity\.outputs\.base_sha \}\}/u);
  assert.match(workflow,/branches: \["work\/ui-control-rust-20261002"\]/u);
  assert.match(workflow,/contents: read/u);
  assert.match(workflow,/pull_request:\n    paths: \["apps\/hepta-control-ui\/\*\*"/u);
  assert.doesNotMatch(workflow,/pull-requests: write|secrets\.|gh pr |deploy/iu);
  assert.match(workflow,/playwright\.rust\.config\.mjs/u);
  assert.match(workflow,/identity-final\.json/u);
  assert.match(workflow,/cmp \.tmp\/ui-control-rust-evidence\/identity\.json \.tmp\/ui-control-rust-evidence\/identity-final\.json/u);
  const build=await readFile(new URL("../tools/build-rust.mjs",import.meta.url),"utf8");
  assert.match(build,/join\(root, "dist-rust"\)/u);
  assert.match(build,/wasm-bindgen 0\.2\.128/u);
  assert.match(build,/wasm-unsafe-eval/u);
  assert.doesNotMatch(build,/['"]unsafe-eval['"]/u);
  assert.equal(JAVASCRIPT_BASELINE,"5c0bbe30e4a5d408c430e8ab1fcc25638042d82a");
});

test("identity capture refuses dirty tracked and untracked source", async () => {
  const source = await readFile(new URL("../tools/rust-candidate-identity.mjs",import.meta.url),"utf8");
  assert.match(source, /git\("diff", "--exit-code", "HEAD"/u);
  assert.match(source, /"ls-files", "--others", "--exclude-standard"/u);
  assert.match(source, /javascriptBaseline: JAVASCRIPT_BASELINE/u);
});
