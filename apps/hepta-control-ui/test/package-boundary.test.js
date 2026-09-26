import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("package metadata declares Node and browser-safe public boundaries", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8"),
  );
  assert.equal(packageJson.type, "module");
  assert.equal(packageJson.main, "./src/index.js");
  assert.equal(packageJson.types, "./src/index.d.ts");
  assert.equal(packageJson.exports["."].import, "./src/index.js");
  assert.equal(packageJson.exports["./browser"].import, "./src/browser-app.js");
  assert.equal(packageJson.engines.node, ">=22.0.0");
  await access(new URL("../src/index.d.ts", import.meta.url));
});

test("unexported src deep imports are rejected", async () => {
  await assert.rejects(
    import("@hepta/control-ui/src/control.js"),
    error => error?.code === "ERR_PACKAGE_PATH_NOT_EXPORTED",
  );
});

test("browser sources avoid unsafe HTML injection sinks", async () => {
  const source = await readFile(new URL("../src/browser-app.js", import.meta.url), "utf8");
  for (const sink of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"])
    assert.equal(source.includes(sink), false, `browser source contains ${sink}`);
});
