import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import {
  UI_CONTROL_BROWSER_BUILD_SCHEMA,
  UI_CONTROL_RUNTIME_SUBSTITUTIONS,
} from "../../../qualification/ui-control/deployment-asset-invariants.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const dist = join(root, "dist");
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(join(root, "web"), dist, { recursive: true });
await cp(join(root, "src"), join(dist, "src"), { recursive: true });

const files = [];
async function collect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await collect(path);
    else if (entry.name !== "build-manifest.json") files.push(path);
  }
}
await collect(dist);

const manifest = {
  schema: UI_CONTROL_BROWSER_BUILD_SCHEMA,
  runtimeSubstitutions: UI_CONTROL_RUNTIME_SUBSTITUTIONS,
  files: {},
};
for (const path of files.sort()) {
  const content = await readFile(path);
  manifest.files[relative(dist, path).replaceAll("\\", "/")] = {
    bytes: content.byteLength,
    sha256: createHash("sha256").update(content).digest("hex"),
  };
}
await writeFile(join(dist, "build-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`built ${Object.keys(manifest.files).length} browser assets`);
