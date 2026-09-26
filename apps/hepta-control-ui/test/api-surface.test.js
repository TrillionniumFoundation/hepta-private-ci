import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const expected = JSON.parse(
  await readFile(new URL("./api-surface.json", import.meta.url), "utf8"),
);

test("public API surface is explicit and review-gated", async () => {
  const api = await import("@hepta/control-ui");
  assert.deepEqual(Object.keys(api).sort(), expected);
});

test("core export excludes browser and transport composition", async () => {
  const core = await import("@hepta/control-ui/core");
  assert.equal("RuntimeClient" in core, true);
  assert.equal("projectRuntime" in core, true);
  assert.equal("createControlConsole" in core, false);
  assert.equal("SameOriginHttpTransport" in core, false);
  assert.equal("SessionProvider" in core, false);
});

test("browser export is explicit", async () => {
  const browser = await import("@hepta/control-ui/browser");
  assert.deepEqual(Object.keys(browser), ["createControlConsole"]);
});
