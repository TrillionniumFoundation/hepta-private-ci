import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const verifier = fileURLToPath(
  new URL("../scripts/verify-deployment-evidence.py", import.meta.url),
);

test("deployment evidence verifier is valid Python", () => {
  const result = spawnSync(
    "python3",
    ["-m", "py_compile", verifier],
    {
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
