import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve, relative, join } from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));
const candidate = JSON.parse(await readFile(join(root, "dist-rust/build-manifest.json"), "utf8"));
const active = JSON.parse(await readFile(join(root, "dist/build-manifest.json"), "utf8"));
assert.equal(active.schema, "hepta.ui-control.browser-build.v2");
assert.equal(active.browserRuntime, "rust-wasm-v1");
assert.equal(active.productCallerSwitched, true);
assert.equal(candidate.productCallerSwitched, false);
assert.equal(active.generatedGlue, "wasm-bindgen 0.2.128");
assert.deepEqual(active.runtimeSubstitutions, { "index.html": ["csrf-meta-content-v1"] });
assert.deepEqual(active.files, candidate.files, "default browser must be byte-identical to tested Rust candidate");
const expected = ["index.html", "main.js", "pkg/hepta_control_web.js", "pkg/hepta_control_web_bg.wasm", "styles.css", "theme.css"].sort();
assert.deepEqual(Object.keys(active.files).sort(), expected, "no legacy application code in browser artifact");
for (const directory of ["dist", "dist-rust"]) {
  const folder = resolve(root, directory);
  const actual = [];
  async function visit(path) {
    for (const entry of await readdir(path, { withFileTypes: true })) {
      const file = join(path, entry.name);
      if (entry.isDirectory()) await visit(file);
      else {
        assert(entry.isFile(), "artifact must contain only regular files");
        const name = relative(folder, file).replaceAll("\\", "/");
        if (name === "build-manifest.json") continue;
        actual.push(name);
        const bytes = await readFile(file);
        assert.deepEqual(active.files[name], { bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") });
      }
    }
  }
  await visit(folder);
  assert.deepEqual(actual.sort(), expected);
}
console.log("Default Rust artifact is byte-identical to the browser-tested candidate; exactly six inventoried assets");
