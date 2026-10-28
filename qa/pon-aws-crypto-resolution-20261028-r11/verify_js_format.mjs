import fs from "node:fs";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const acorn = require(process.env.HEPTA_ACORN_MODULE);
const [beforePath, afterPath] = process.argv.slice(2);
assert.equal(acorn.version, "8.15.0");
function normalized(text) {
  const comments = [];
  const tree = acorn.parse(text, {
    ecmaVersion: "latest",
    sourceType: "script",
    onComment: comments,
  });
  function clean(value) {
    if (Array.isArray(value)) return value.map(clean);
    if (!value || typeof value !== "object") return value;
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !["start", "end", "loc", "range", "raw"].includes(key))
        .map(([key, item]) => [key, clean(item)]),
    );
  }
  return { tree: clean(tree), comments: clean(comments) };
}
const before = fs.readFileSync(beforePath, "utf8");
const after = fs.readFileSync(afterPath, "utf8");
assert.deepEqual(normalized(before), normalized(after));
assert.notDeepEqual(normalized(after), normalized(after.replace("node", "browser")));
process.stdout.write(
  JSON.stringify({ acorn: acorn.version, semanticAstEqual: true, changedLiteralRejected: true }) + "\n",
);
