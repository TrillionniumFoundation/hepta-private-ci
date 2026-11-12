# Original scoped maintenance control — v2 HOLD

This package is a prepared control, not permission to start maintenance. The driver, configuration template and source review have not been executed as a native maintenance operation. The exact actual runtime-restoration success records are still required before Root creates a separately pinned approved configuration.

## Fixed source and actual materialization

The source is `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1`, detached at `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, with ordered original parents `c0f78493f815780f68b9bf5e390a21314d79311f` and `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`.

Materialization actually completed as job `1a1d0c6996e-2564-1bc8`. Its original RESULT is `456f749e7558e18df99172d9c9273cda890b8feb` (69,974 bytes, SHA256 `b2ef9a18547838b5978d8f4b7b8cc11b28d089cc386c207894017c2cfe5e1c58`), with the actual normal complete terminal tool envelope `3e60d21bec849a19efb5d818b43152bfc72486fe` (913 bytes, SHA256 `83a16687e3b108f49c598cb6be9aead68a2a95991c92df49a836889422bab2b2`). It was a source preparation operation, with no Cargo, maintenance or test execution.

Its actual complete physical inventory is 5,611,182 bytes, SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`, Git blob `e7efbbc915cf80db9f873a2b5f9bf162daf4308c`, with exactly 15,188 leaves. Maintenance must freshly reproduce this inventory and the original detached/index identity. A recovered copy of that inventory is not a new physical observation.

The wrapper also verifies that the exact c0f base commit and its complete snapshot are readable. The original formatter uses that fixed base directly. No complete historical ancestry, synthetic shallow boundary, replacement object or whole-history fsck success is invented.

## Exact original execution

| Stage | Unchanged argv | Budget |
| --- | --- | ---: |
| fix | `just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd` | 7,200 seconds |
| fmt, only after complete successful fix | `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` | 900 seconds |

Both launch from the exact source. The original justfile and just-shell select the original recipe. Clippy's original `--tests` compilation remains part of fix; the wrapper dispatches no test command and does not count compilation as a passing test.

The exact original `scripts/hepta_ci_exec.py::execute_logged` body is loaded from its verified archived source bytes. The wrapper does not invoke the clean-source gate `run()`. Intentional maintenance postimages must be preserved for review. Original process-group handling, 64 MiB output bound and command deadlines remain unchanged. No competing wrapper alarm is armed around those commands.

The separate preflight budget remains 600 seconds and the aggregate source/evidence-recording budget remains 300 seconds, exactly as in the reviewed v1 control. These are preparation/evidence overhead, not extensions of a test or source gate. Root/native separately fix the launcher's full outer envelope. A failed or incomplete fix prevents fmt from starting.

## Exact v1-to-v2 scope

The predecessor control is Git blob `842cb1dbc262d09412ab4f1759f05f1115c60d86`, 46,877 bytes, SHA256 `618fb1ab12dafb6c11da0efed59c96b93f841b3db6d306781a5688cb9cd6e71c`.

V2 is Git blob `f288d78be78a0f036a862253dfcafbc5d48e1f80`, 54,853 bytes, SHA256 `fd2a78d56bf43a20e0dd6f34f0ad474980c9273b2c7888ebaecd12412d32a1a8`. Exact patch: `d11187016c15853c3b1398b8ec8b2531cac2d242`. Static check: `80180c7a6415caaee197137f3429753e906d4080`.

The only functional scope is the required runtime-restoration admission and original-source-snapshot/control separation. Static comparison found 42 original definitions byte-for-byte unchanged, four existing definitions changed, three added, none removed. The original main control flow and the original execute_logged call AST remain unchanged. The check parsed and compiled a code object without importing the driver or calling any of its functions.

### Source snapshots and immutable controls

Six original source entry files are verified and archived before maintenance: AGENTS.md, justfile, scripts/format.py, scripts/hepta_ci_exec.py, scripts/just-shell.py and codex-rs/rust-toolchain.toml. Their archived bytes are immutable controls; their writable repository pathnames are not placed in the final immutable-control comparison.

The original execution helper is loaded from the pinned archive. Immediately before fix, the actual justfile, shell wrapper and toolchain are checked against their original pins. Immediately before fmt, the original formatter entry is also checked. After each command starts, legitimate source changes belong to complete postimage evidence. This avoids declaring legitimate formatter output to be immutable-control drift.

Driver/config/proof files, historical environment, inventory implementation and archived entry bytes remain immutable and are reread at the boundaries and final audit.

### Runtime-restoration admission

The configuration must pin three actual documents: the restoration RESULT, its complete normal supervisor tool envelope and the actual ENVIRONMENT_READY file. The RESULT must bind the same source, parents, depot and target, with source unchanged and all three final audits verified. All six original runtime preparation commands must have observed complete terminals, returncode zero, no timeout and no output-limit truncation. The actual environment file must match the original RESULT's bytes/SHA256/Git identity.

An exception or missing command terminal cannot be treated as a completed preparation. The current template deliberately has null runtime job/proof/tool fields; setting a status label alone does not supply evidence.

The historical 12-key environment `69a3d38ff1cf800813f1fbf1f30bca224157f223` is preserved except for the authorized explicit runtime changes:

- The new `/data/hepta-utility-36fa-runtime-materials-86dd-v1/bin` PATH prefix.
- The existing dedicated external Cargo target.
- The two actual V8 files in the depot's fixed GNU sandbox profile.
- `UV_PROJECT_ENVIRONMENT`, `UV_CACHE_DIR`, `RUFF_CACHE_DIR`, `UV_OFFLINE=true` and `UV_PYTHON_DOWNLOADS=never`.

The resulting 17-key explicit map must equal both the actual restoration record and the approved configuration. CODEX_REPO_ROOT and PYTHONPATH must match the actual inherited observations and the approved configuration. CODEX_REPO_ROOT cannot identify an old source worktree. Neither value is guessed or silently rewritten.

Tool, V8 and external venv pins are projected explicitly to `path, resolved, bytes, sha256, mode`. The richer original restoration metadata remains in the archived ENVIRONMENT_READY document. Comparing a full richer dictionary to this five-field view would be incorrect; v2 uses the same explicit projection on both sides.

Actual just --version output is recorded without inventing a just version contract. The just executable must match the exact restored file identity. UV 0.11.3 is a separately established pinned restoration requirement and is checked again. The original installed Rust toolchain must remain available. No package, interpreter or tool is installed by this maintenance wrapper; no uv sync or uv run preflight is substituted.

The target and formatter directories must already exist, be accessible and owned by the current user. Target recreation is rejected even if a configuration attempts to allow it. Actual free space remains a Root-approved, observed precondition. Conflicting or unreadable matching same-user build/formatter processes cause refusal without killing another process.

## Complete postimages and failure evidence

The original full inventory includes tracked, ignored and untracked physical source files. Each stage preserves complete raw logs and the original result dictionary before later processing. Every changed path has its exact before and after bytes, base64 representation, SHA256, Git blob identity, file kind and mode. Added/deleted paths are explicit. A full-index binary HEAD diff supplements these records; untracked files still appear in the transition packet.

The source is inventoried again after capture. A moving postimage is rejected. The complete physical leaf map is encoded using Git's actual tree byte ordering to calculate the observed candidate root. The wrapper writes no Git tree, commit, source branch, evidence branch or PR.

Original HEAD/index/config/refs and the complete own Git metadata are compared before/after. No reset, cleanup or automatic retry hides changes. Failure or Unknown preserves attempted status and any available raw evidence. An attempted command cannot become not_run because later capture failed. Final input/source audits run independently within their separate record budget.

The only successful wrapper status is `MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED`. It says that the two maintenance commands completed with retained evidence. It is not a source gate, Rust test, authorization, independent evaluation, adoption, NoUpdate or ordinary-learning-closure result.

## Post-format handoff

Root must derive the actual new complete source identity from the final observed inventory and exact postimages. The non-Rust writer then uses that observed source, including each of the 46 relevant Rust postimages, for the already reviewed post-format extractor. Original preformat bytes, this HOLD control and the initial materialization snapshot cannot stand in for formatted preimages.

The extractor's original full source collector and all required checks remain unchanged by this wrapper. After review and source-fence alignment, a distinct exact frozen successor still needs the original full gates. No prior c0f or preparation result is transferred to it as a pass.

## Create-only approval and execution

Stage the immutable control files in the new evidence root `/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1`. The unapproved template is `WAITING_CONFIG.json`. Root creates `APPROVED_CONFIG.json` only after the actual restoration terminal, tool/environment observations and peer reviews are available. Do not overwrite the waiting file to disguise it as a prior approved observation.

The formal launcher must pin the driver and approved configuration bytes/SHA256 and actual paths. Only the sole native executor may launch the approved operation, using one unique identity. Existing output is reconciled, never overwritten or replayed.

At the time this package was prepared, the actual runtime restoration terminal was still pending. This package intentionally makes no runtime-success claim.
