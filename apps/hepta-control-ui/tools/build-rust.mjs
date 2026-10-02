// Build the explicit Rust candidate without replacing the JavaScript product artifact.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));
const workspace = join(root, "rust");
const dist = join(root, "dist-rust");
const version = execFileSync("wasm-bindgen", ["--version"], { encoding: "utf8" }).trim();
if (version !== "wasm-bindgen 0.2.128") throw new Error("Rust browser candidate requires wasm-bindgen 0.2.128");
const target = process.env.CARGO_TARGET_DIR ? resolve(process.env.CARGO_TARGET_DIR) : join(workspace, "target");
execFileSync("cargo", ["build", "--locked", "--manifest-path", join(workspace, "Cargo.toml"),
  "-p", "hepta-control-web", "--target", "wasm32-unknown-unknown", "--release"], {
  cwd: root, stdio: "inherit", env: { ...process.env, CARGO_BUILD_JOBS: process.env.CARGO_BUILD_JOBS ?? "2", CARGO_INCREMENTAL: "0" },
});
await rm(dist, { recursive: true, force: true });
await mkdir(join(dist, "pkg"), { recursive: true });
execFileSync("wasm-bindgen", [join(target, "wasm32-unknown-unknown/release/hepta_control_web.wasm"),
  "--target", "web", "--out-dir", join(dist, "pkg"), "--no-typescript"], { stdio: "inherit" });
await cp(join(root, "web/styles.css"), join(dist, "styles.css"));
const html = (await readFile(join(root, "web/index.html"), "utf8"))
  .replace("script-src 'self';", "script-src 'self' 'wasm-unsafe-eval';")
  .replace('<link rel="stylesheet" href="./styles.css">', '<link rel="stylesheet" href="./styles.css">\n    <link rel="stylesheet" href="./theme.css">');
await writeFile(join(dist, "index.html"), html);
const theme = execFileSync("cargo", ["run", "--quiet", "--locked", "--manifest-path", join(workspace, "Cargo.toml"), "-p", "hepta-control-core", "--bin", "hepta-control-theme"], { cwd: root, encoding: "utf8" });
await writeFile(join(dist, "theme.css"), theme);
// Generated bootstrap only. All application, session, transport, recovery and DOM logic is Rust.
await writeFile(join(dist, "main.js"), 'import init, { start } from "./pkg/hepta_control_web.js";\nawait init();\nawait start();\n');
const files = {};
async function inventory(directory) {
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a,b) => a.name.localeCompare(b.name))) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await inventory(path);
    else { const bytes = await readFile(path); files[relative(dist,path).replaceAll("\\","/")] = { bytes:bytes.length, sha256:createHash("sha256").update(bytes).digest("hex") }; }
  }
}
await inventory(dist);
await writeFile(join(dist, "build-manifest.json"), JSON.stringify({ schema: "hepta.ui-control.rust-candidate-build.v1",
  productCallerSwitched:false, generatedGlue:version, files }, null, 2) + "\n");
console.log(`Built explicit Rust candidate (${Object.keys(files).length} assets); JavaScript product artifact unchanged`);
