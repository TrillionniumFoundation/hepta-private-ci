// The default shipped browser artifact contains Rust WASM and generated ABI only.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
execFileSync(process.execPath, [fileURLToPath(new URL("./build-rust.mjs", import.meta.url)), "--active"], { stdio: "inherit" });
