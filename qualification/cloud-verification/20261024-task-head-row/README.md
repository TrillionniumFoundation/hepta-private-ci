# Shadow task-Head owner: per-row wire-byte bounds

Base #3616 exact `c8a2014750e2c3a59c0966873fbfe0d8084a598c`, parent `d262f70094cc4ad8cd8d254ef709ab8c75e9b066`. Current-head/recent-PR inspection found no already-published repair. Independent branch; no v4/media composition.

Final source **`d1619f1d2dd433f958d76143309011c73b4c5cf5`**, draft [#3617](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3617). All five changed files independently reviewed and remote bytes verified against the local reviewed tree `651eb338b43dad625028f13c0ba536372faa7674`. Exact final-source rerun: 24 Rust passed (100 not selected), isolated owner all-targets Clippy passed, 16 Python passed; see final-sha logs.

First hosted source `dfa467b5b961f79e25ef6860500ee42607ca2642` [run 40054159157](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40054159157) verified its SHA and passed 24 Rust tests, then failed because Clippy was missing; Python did not run. Complete log retained. Independently reviewed two-line workflow correction explicitly installs Clippy with the same fixed Rust action. No gate relaxed. Final-source [run 40054422989](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40054422989) **completed successfully**: job 120754121578 log verifies `d1619f1d2dd433f958d76143309011c73b4c5cf5`, 24 actual-module/native Rust tests passed, 100 unrelated tests not selected, isolated owner all-targets Clippy finished successfully, and 16 Python fixtures passed. See final-hosted-ci.log. Three broader workflows (40054423042 blocking-ci, 40054422986 architecture, 40054423093 v8-canary) remained queued at final observation; no manual rerun.

## Confirmed defect and implementation

The author explicitly left the design's 256 KiB per-row byte bound unimplemented. Original owner tests passed 9/9, but newly constructed valid padded inventory/request rows larger than 256 KiB were accepted under existing aggregate caps. Original-source new regressions were run through the actual owner module: 9 pass, 4 fail (complete negative log retained). No private retained assets were used.

Add allocation-free wire-byte preflight before inventory/request row deserialization. Each row container is limited to 262144 original UTF-8 bytes inclusive, counting delimiters, nested fields, escaped spellings and internal whitespace/newlines. Array separator whitespace outside a row remains governed by the existing total-envelope cap. This is not a per-line check or character-count limit. Every row is checked before any batch forward, including a late oversized row. Inventory pins are still checked over the exact original bytes; no source/pin semantics change.

The scanner only enforces resources; serde remains the syntax/type/duplicate-field validator. Malformed oversized input may return Bounds before Encoding. It scans direct row containers independently of escaped key spelling. Independent review found an initial object-only implementation could be bypassed with serde's positional sequence representation; that failure is retained and the final implementation covers both object and array rows plus positional envelopes. Tests cover exact limit, +1 byte, multiple lines, non-ASCII field bytes, escaped rows key, quoted delimiters/backslashes, duplicate/malformed JSON, late-row zero-forward, and inventory/request sequence representations.

Missing modalities still yield null prediction; original tests verify order and denial posture. No changed native Head math, weights, thresholds, declared pair identities, host pins, source lineage or production routing. SHADOW_ONLY / DENY_ALL and all authority booleans remain unchanged.

## Actual-source validation scope

The checked-in staging script copies the real neuron/infer-core/types crates unchanged, verifies copies bytewise, and imports the actual Agentd owner module and its tests by path. Its 99-file source manifest covers 97 dependency files plus the two owner files. No mock types, substitute predictor or diagnostic instrumentation. A separate committed validation lock fixes registry dependencies; the production workspace manifests/lockfiles are unchanged.

Final local Rust selection: **24 passed, zero ignored within selection** (14 owner = original nine plus five new; 10 native task-Head tests). **100 other neuron tests were not selected.** Python fixture tests: **16 passed**. Isolated owner all-targets Clippy `-D warnings`, staging-script Ruff, compile checks and formatting passed. The isolated workspace does not inherit all repository lint configuration; this is not a whole-repository Clippy pass. Existing missing-null, pins, posture and source-binding tests remain included. Independent complete five-file review and hashes accompany this report.

Commands, with `RUSTUP_HOME=/workspace/rustup`, `CARGO_HOME=/workspace/cargo`, Cargo tools on PATH, `CARGO_BUILD_JOBS=2`, `CARGO_TARGET_DIR=/workspace/task-head-harness/target`:

```sh
python scripts/prepare_research_task_head_check.py /workspace/task-head-final-published
just --working-directory /workspace/task-head-final-published --justfile /workspace/task-head-final-published/justfile test --offline --locked -p research-task-head-owner-check -p codex-hepta-neuron --lib -E 'package(research-task-head-owner-check) | test(task_head_native)'
cargo clippy --manifest-path /workspace/task-head-final-published/Cargo.toml --offline --locked -p research-task-head-owner-check --all-targets -- -D warnings
python -m unittest discover -s qa/stem-bakeoff -p test_research_task_head_owner_fixture.py -v
/workspace/verification-3567/pyenv/bin/python -m ruff check scripts/prepare_research_task_head_check.py
UV_CACHE_DIR=/workspace/uv-cache just fmt
git diff --check
```

Linux x86_64, Rust/Cargo 1.95.0, Python 3.12.14, NumPy 2.3.5, Ruff 0.15.13; five CPUs/~17 GiB memory/no swap, about 6 GiB available disk before scoped builds. Formatting initially encountered missing uv on reduced PATH and then a read-only default uv cache; resolved by using existing uv and a writable workspace cache without security changes. Initial staging rejected the workspace serde table and lost shell quoting for the nextest filter; both staging defects were corrected before final validation. Logs distinguish those setup failures, baseline failures and final passes.

## Remaining limitations

Full Agentd `cargo check --offline --locked -p codex-hepta-agentd --lib` is blocked before compilation by uncached `cargo-i18n` revision `2ce7b1dfe9a8cc224288bf50cbc2a67a6de863c4`; exact error retained. No unbounded workspace/V8 build was launched with limited disk. This is a dependency/cache limitation of the offline full-package attempt, not a permission denial, and no full Agentd acceptance is claimed. The new dedicated exact-SHA CI runs only the actual-module harness and synthetic fixtures.

Private 2560-row historical replay was **not run**; those assets were unavailable in this worktree and author results are not ours. Synthetic fixtures establish resource-boundary regression behavior only. Host integrity pins remain neither independent source authentication nor a revocation oracle. No model downloads/training, access bypass, new credentials, physical performance evidence, scientific qualification, merge or deployment.
