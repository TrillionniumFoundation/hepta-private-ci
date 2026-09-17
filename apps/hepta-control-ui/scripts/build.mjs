import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(packageRoot, "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(resolve(dist, "web"), { recursive: true });
await mkdir(resolve(dist, "src"), { recursive: true });

for (const file of ["index.html", "main.js", "styles.css"]) {
  await cp(resolve(packageRoot, "web", file), resolve(dist, "web", file));
}
for (const file of [
  "canonical.js",
  "control.js",
  "errors.js",
  "runtime-client.js",
  "web-app.js",
]) {
  await cp(resolve(packageRoot, "src", file), resolve(dist, "src", file));
}
