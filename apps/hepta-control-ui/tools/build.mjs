// Canonical product build: the same Robrix-derived Rust/Makepad UI as desktop.
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
execFileSync(process.execPath, [fileURLToPath(new URL('./build-robrix.mjs', import.meta.url))], {stdio:'inherit'});
