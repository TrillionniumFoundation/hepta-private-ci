import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("deployment verifier executes file, identity, lock and hostile JSON regressions", () => {
  const script = fileURLToPath(new URL("./evidence-runtime-regression.py", import.meta.url));
  const output = execFileSync("python3", ["-B", script], {
    encoding: "utf8", timeout: 30_000, stdio: ["ignore", "pipe", "pipe"],
  });
  assert.equal(output, "");
});
