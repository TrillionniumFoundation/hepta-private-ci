import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import test from "node:test";

const verifier = resolve(
  "apps/hepta-browser/scripts/verify-deployment-evidence.py",
);

test("deployment evidence verifier is valid Python", () => {
  const result = spawnSync(
    "python3",
    ["-m", "py_compile", verifier],
    {
      cwd: resolve("."),
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
      },
    },
  );
  assert.equal(
    result.status,
    0,
    `deployment verifier failed Python compilation:\n${result.stdout}\n${result.stderr}`,
  );
});
