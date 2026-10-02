// Build the explicit Rust candidate without replacing the JavaScript product artifact.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));
const workspace = join(root, "rust");
const dist = join(root, "dist-rust");
const active = process.argv.includes("--active");
const output = active ? join(root, "dist") : dist;
const version = execFileSync("wasm-bindgen", ["--version"], { encoding: "utf8" }).trim();
if (version !== "wasm-bindgen 0.2.128") throw new Error("Rust browser candidate requires wasm-bindgen 0.2.128");
const target = process.env.CARGO_TARGET_DIR ? resolve(process.env.CARGO_TARGET_DIR) : join(workspace, "target");
execFileSync("cargo", ["build", "--locked", "--manifest-path", join(workspace, "Cargo.toml"),
  "-p", "hepta-control-web", "--target", "wasm32-unknown-unknown", "--release"], {
  cwd: root, stdio: "inherit", env: { ...process.env, CARGO_BUILD_JOBS: process.env.CARGO_BUILD_JOBS ?? "2", CARGO_INCREMENTAL: "0" },
});
await rm(output, { recursive: true, force: true });
await mkdir(join(output, "pkg"), { recursive: true });
execFileSync("wasm-bindgen", [join(target, "wasm32-unknown-unknown/release/hepta_control_web.wasm"),
  "--target", "web", "--out-dir", join(output, "pkg"), "--no-typescript"], { stdio: "inherit" });
await cp(join(root, "web/styles.css"), join(output, "styles.css"));
const html = (await readFile(join(root, "web/index.html"), "utf8"))
  .replace("script-src 'self';", "script-src 'self' 'wasm-unsafe-eval';")
  .replace('<link rel="stylesheet" href="./styles.css">', '<link rel="stylesheet" href="./styles.css">\n    <link rel="stylesheet" href="./theme.css">');
await writeFile(join(output, "index.html"), html);
const theme = execFileSync("cargo", ["run", "--quiet", "--locked", "--manifest-path", join(workspace, "Cargo.toml"), "-p", "hepta-control-core", "--bin", "hepta-control-theme"], { cwd: root, encoding: "utf8" });
await writeFile(join(output, "theme.css"), theme);
// Generated bootstrap only. All application, session, transport, recovery and DOM logic is Rust.
await cp(join(root, "web/main.js"), join(output, "main.js"));
const files = {};
async function inventory(directory) {
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a,b) => a.name.localeCompare(b.name))) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await inventory(path);
    else { const bytes = await readFile(path); files[relative(output,path).replaceAll("\\","/")] = { bytes:bytes.length, sha256:createHash("sha256").update(bytes).digest("hex") }; }
  }
}
await inventory(output);
await writeFile(join(output, "build-manifest.json"), JSON.stringify({ schema: active ? "hepta.ui-control.browser-build.v2" : "hepta.ui-control.rust-candidate-build.v1",
  runtimeSubstitutions: { "index.html": ["csrf-meta-content-v1"] },
  browserRuntime: "rust-wasm-v1", productCallerSwitched: active, generatedGlue:version, files }, null, 2) + "\n");
console.log(`Built ${active ? "default Rust browser" : "isolated Rust candidate"} (${Object.keys(files).length} assets)`);
