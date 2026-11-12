# Exact 86dd maintenance entry constraints — read-only review

Prepared source: `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`. This is a source review for native's next maintenance controller. No maintenance driver or command was executed by this review.

## Verified source identities

I read the six files from the exact 86dd GitHub source. Their full UTF-8 byte lengths, Git blob identities and SHA256 also equal the matching entries in Root's precisely recovered **original** c0f physical inventory (5,474,911 bytes, SHA256 `cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57`). This comparison is not a new observation of the native filesystem.

| File | Git blob | Bytes | SHA256 |
| --- | --- | ---: | --- |
| `AGENTS.md` | `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a` | 22519 | `c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480` |
| `justfile` | `a215a76cf407ace9715bca39c20497014e7dd4dc` | 7838 | `74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124` |
| `scripts/format.py` | `d4eabe70b68605933240e9129245f7f4cccbde5d` | 16599 | `8d93d7a6261bbe5f2b9fceea228154f0be29f721015d05b4f538c30076dd80b3` |
| `scripts/hepta_ci_exec.py` | `c9434b3a4afb31f80e323d543936386a2fa738de` | 12863 | `9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1` |
| `scripts/just-shell.py` | `bb2db6ebc4312a301ee39d2793fde16289d046d8` | 2030 | `444d6b328d44abf6453b77b6acce2a0c881fc162ff30b20f352c85067797fbe9` |
| `codex-rs/rust-toolchain.toml` | `917d2492264a35bc9c0feaef41878d8825870866` | 78 | `e8b379eaa492bf59d35187de269afd1c4f55d85e0322f6fea32803a3fec1a380` |

## Original execution record versus intentional maintenance changes

The correct reusable entry is `scripts/hepta_ci_exec.py::execute_logged`. It retains the actual command return code, timeout flag, output-limit flag, exact raw log size/hash, and observed terminal test summaries. Native proposed retaining the original bounds: scoped fix 7,200 seconds, then fmt 900 seconds.

The same file's higher-level `run` requires a clean tested checkout at admission and equal before/after identity. It is a qualification-style wrapper and intentionally rejects source changes. It should not wrap a maintenance step whose valid result may include new postimages. Reusing `execute_logged` does not weaken the underlying command's actual exit/timeout/output-limit result.

A fix/format success is maintenance evidence, not behavioral test evidence. Zero observed tests is expected for these commands and must neither become a fake test PASS nor a fabricated test failure. A nonzero fix may still have changed files: retain its actual complete postimages and diagnostics before making a next-step decision.

The future controller must record the exact original argv and environment, actual source identity and full before/after inventory for **each** stage. Preserve all unexpected changed files as evidence and send them for source review; do not silently treat an unanticipated hunk as approved or restore an older full-file image over current owner fixes.

## Exact recipe and formatting behavior

The root `justfile` sets `working-directory := "codex-rs"`, exports `CODEX_REPO_ROOT` from its own directory and uses that same repository's `scripts/just-shell.py`. The actual fix recipe is:

```text
cargo clippy --fix --tests --allow-dirty {args}
```

The `{args}` token is intentional. The original POSIX adapter substitutes it with `"$@"` and supplies each recipe argument separately through `sh -cu`; it is not a failed interpolation to repair.

Native's proposed scoped package selection remains `codex-hepta-intelligence-eval` plus `codex-hepta-agentd`. The actual historical environment/argv record must determine any additional inherited flags, cache paths or offline/locked options. This source-only review does not invent them or claim that a cache/tool is currently available.

The fmt recipe calls the original `scripts/format.py`. With the exact `--base c0f78493f815780f68b9bf5e390a21314d79311f`, `changed_paths` resolves that original commit and runs a direct `git diff --name-only --diff-filter=ACDMRT --no-renames -z <resolved-base> --`, together with current untracked files. It does **not** call merge-base or traverse the whole older parent history. Preserving the actual c0f commit and complete snapshot is sufficient for this original comparison; no shallow/graft/replacement history is justified.

Changed Rust paths go through `rust_file_command`: read the owning Cargo manifest and inherited workspace edition, use that crate's working directory so rustup sees the original pinned toolchain, and call rustfmt with `imports_granularity=Item,skip_children=true`. Scope expansion from changed rustfmt configuration stays in its owning subtree. The toolchain file pins **1.96.0**, with clippy, rustfmt and rust-src. Native must check the actual installed toolchain; the file alone does not prove availability.

The original formatter selects owning language groups for the actual changed paths. It may run the existing Python scripts formatter when those paths changed. Final source fences must therefore be derived after the real fix/fmt postimages are known, not guessed from the unformatted 86dd bytes.

## Admission, failure and handoff

Maintenance must wait for an actual successful fresh-materialization terminal, its complete output and the exact new repository inventory. A new directory, a valid tree object or an earlier source gate does not establish that state. The new source's detached HEAD remains 86dd during maintenance; its postimage bytes need a separately recorded tree and subsequent frozen identity.

Use a distinct maintenance execution identity and external records. The approved fresh materialization driver does not authorize or run fix/fmt. Native alone prepares the next original controller; this review does not start it.

Keep the original budgets and actual terminal semantics. Do not manually kill a Rust process by PID or change the repository's sandbox variables, stack size, task deadlines, assertions, permission contracts or test selection to obtain a result. Source compilation errors, missing dependencies, timeouts and output loss remain their actual outcomes. A failed or unknown first stage must not be described as a successful formatted candidate.

After actual maintenance, the sole non-Rust author can consume the exact formatted source and preserve the reviewed caller/authority contracts in final CALLERS/QA/allowlist data. None of the old c0f native failures, the preparation tree, this source review or maintenance alone transfers behavioral qualification to that later source.

## Configuration-path clarification for the materialization package

If the WAITING template is staged on the host, name it `WAITING_CONFIG.json`. Root freezes the separately reviewed **`APPROVED_CONFIG.json` create-only** after approval. Do not first stage WAITING under that approved name and overwrite it. This clarifies the immutable control plan's staging wording without changing driver `1ca5aab7144291449f89364646b62b364d3cbe0d`. The launcher must bind the exact approved driver and approved config paths and byte identities.
