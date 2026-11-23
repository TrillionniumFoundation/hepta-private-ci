// Source-locked workflow inputs of the HCSN static and migration qualifications.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const expected = new Map([
  [
    ".github/workflows/hcsn-source-tree-static-branchfix-successor.yml",
    "a604633b4e83cc9a37bb09235ac10d3c2e04ac9d69662723c02542c65f208aef",
  ],
  [
    ".github/workflows/hcsn-source-tree-static-just-successor.yml",
    "aebac21f36592c9236415ee32371decc8431dc934d71a8520d51658eb71f1957",
  ],
  [
    ".github/workflows/hcsn-visit897-n128-stretch-field-static.yml",
    "50ebc64d1c6e3dbdc16577c1d1d911cbdebf65a36d8fb36946ff1319c689cdc4",
  ],
]);

for (const [path, digest] of expected) {
  const content = readFileSync(new URL(`../${path}`, import.meta.url));
  const actual = createHash("sha256").update(content).digest("hex");
  if (actual !== digest) {
    console.error(
      `Frozen workflow changed: ${path} expected ${digest}, got ${actual}`,
    );
    process.exitCode = 1;
  }
}
