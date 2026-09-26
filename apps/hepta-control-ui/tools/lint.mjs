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
      if (!["dist", "node_modules", "test-results", "playwright-report"].includes(entry.name)) {
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
console.log(`checked ${sources.length} JavaScript modules`);
