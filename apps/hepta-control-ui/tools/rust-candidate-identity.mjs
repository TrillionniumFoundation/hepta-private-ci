import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
export const JAVASCRIPT_BASELINE = "5c0bbe30e4a5d408c430e8ab1fcc25638042d82a";
const sha = /^[0-9a-f]{40}$/u;
export function validateSubject({ source, base, evaluated, tree, sourceTree, mergeTree, parents, subject }) {
  if (![source, base, evaluated, tree, sourceTree].every(value => typeof value === "string" && sha.test(value))) throw new Error("invalid immutable source identity");
  if (subject === "head") {
    if (evaluated !== source || tree !== sourceTree) throw new Error("head does not match pinned source");
  } else if (subject === "merge") {
    if (!sha.test(mergeTree) || tree !== mergeTree || parents.length !== 2 || parents[0] !== base || parents[1] !== source) throw new Error("merge does not match pinned base/source tree and ordered parents");
  } else throw new Error("unknown qualification subject");
  return { source, base, evaluated, tree, parents, subject };
}
async function run() {
  const [source, base, subject, output] = process.argv.slice(2);
  if (!sha.test(source) || !sha.test(base) || !output) throw new Error("expected source SHA, base SHA, head|merge and evidence path");
  const root = fileURLToPath(new URL("../../..", import.meta.url));
  const git = (...args) => execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
  const sourcePaths = ["apps/hepta-control-ui", ".github/workflows/ui-control-rust-parity.yml"];
  git("diff", "--exit-code", "HEAD", "--", ...sourcePaths);
  if (git("ls-files", "--others", "--exclude-standard", "--", ...sourcePaths)) throw new Error("uncommitted source cannot receive an immutable candidate identity");
  const evaluated = git("rev-parse", "HEAD");
  const tree = git("rev-parse", "HEAD^{tree}");
  const sourceTree = git("rev-parse", `${source}^{tree}`);
  const parents = git("rev-list", "--parents", "-n", "1", "HEAD").split(" ").slice(1);
  const mergeTree = subject === "merge" ? git("merge-tree", "--write-tree", base, source) : null;
  const identity = validateSubject({ source, base, evaluated, tree, sourceTree, mergeTree, parents, subject });
  const baselineFiles = ["canonical.js", "control.js", "runtime-contract.js", "snapshot.js", "confirmation.js"].map(name => `apps/hepta-control-ui/src/${name}`);
  git("diff", "--exit-code", JAVASCRIPT_BASELINE, "--", ...baselineFiles);
  const paths = [...baselineFiles, "apps/hepta-control-ui/rust/Cargo.lock", "apps/hepta-control-ui/package-lock.json", "apps/hepta-control-ui/rust/core/tests/fixtures/javascript-reference.json"];
  const hashes = {};
  for (const path of paths) hashes[path] = createHash("sha256").update(await readFile(resolve(root,path))).digest("hex");
  const receipt = { schema: "hepta.ui-control.rust-parity-subject.v1", ...identity,
    javascriptBaseline: JAVASCRIPT_BASELINE, inputSha256: hashes, productCallerSwitched: false, productionQualified: false };
  const destination = resolve(root, output);
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, JSON.stringify(receipt,null,2)+"\n");
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await run();
