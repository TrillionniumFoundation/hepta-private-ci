import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const expected = JSON.parse(
  await readFile(new URL("./api-surface.json", import.meta.url), "utf8"),
);

test("historical oracle API surface remains explicit", async () => {
  const api = await import("../src/index.js");
  assert.deepEqual(Object.keys(api).sort(), expected);
});

test("named control-client-core export excludes browser and transport composition", async () => {
  const core = await import("../src/core.js");
  assert.equal("RuntimeClient" in core, true);
  assert.equal("projectRuntime" in core, true);
  assert.equal("createControlConsole" in core, false);
  assert.equal("SameOriginHttpTransport" in core, false);
  assert.equal("SessionProvider" in core, false);
});

test("legacy core alias remains compatible", async () => {
  const namedCore = await import("../src/core.js");
  const coreAlias = await import("../src/core.js");
  assert.deepEqual(Object.keys(coreAlias).sort(), Object.keys(namedCore).sort());
});

test("browser export is explicit", async () => {
  const browser = await import("../src/browser-app.js");
  assert.deepEqual(Object.keys(browser), ["createControlConsole"]);
});
