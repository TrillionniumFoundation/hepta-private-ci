import { execFileSync } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const sources = [];

async function collect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (!["dist", "dist-rust", "target", "pkg", "node_modules", "test-results", "playwright-report"].includes(entry.name)) {
        await collect(path);
      }
    } else if ([".js", ".mjs"].includes(extname(entry.name))) {
      sources.push(path);
    }
  }
}

await collect(root);
for (const path of sources.sort()) {
  execFileSync(process.execPath, ["--check", path], { stdio: "inherit" });
}

for (const path of sources.filter(path => path.includes(`${join("src", "")}`))) {
  const content = await readFile(path, "utf8");
  for (const forbidden of [".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function("]) {
    if (content.includes(forbidden)) {
      throw new Error(`${relative(root, path)} uses forbidden browser sink ${forbidden}`);
    }
  }
}

const packageJson = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
if (!packageJson.exports?.["."] || packageJson.main !== "./src/index.js") {
  throw new Error("package root export must be explicit and stable");
}

const packageLock = JSON.parse(await readFile(join(root, "package-lock.json"), "utf8"));
if (
  packageLock.lockfileVersion !== 3 ||
  packageLock.name !== packageJson.name ||
  packageLock.version !== packageJson.version
) {
  throw new Error("package-lock.json must be a v3 lock for the exact package identity");
}
const declaredDependencies = packageJson.devDependencies ?? {};
const lockedDeclarations = packageLock.packages?.[""]?.devDependencies ?? {};
if (JSON.stringify(lockedDeclarations) !== JSON.stringify(declaredDependencies)) {
  throw new Error("package-lock.json root dependency declarations are stale");
}
for (const [name, version] of Object.entries(declaredDependencies)) {
  if (!/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error(`${name} must use an exact dependency version`);
  }
  const lockedPackage = packageLock.packages?.[`node_modules/${name}`];
  if (!lockedPackage || lockedPackage.version !== version || typeof lockedPackage.integrity !== "string") {
    throw new Error(`${name} is not exactly and integrally locked`);
  }
}

console.log(`checked ${sources.length} JavaScript modules and exact dependency lock`);
