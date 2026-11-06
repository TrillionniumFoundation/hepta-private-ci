# Source52 apply-only preparation

**INERT — FROZEN=False; no native command or Rust was executed by this preparation.**
The actual source52 commit/tree, root manifest, five-member input archive and candidate bindings remain eight explicit \`None\` constants. Root approval of their exact values and native-owner execution are separate later actions.

The reviewed baseline is source51 commit \`e28b0f385ee882f842911044958b2810f62f6379\`, tree \`763c8d2b4089f6e9806c3bbb68fa247bc2f6af36\`, with 194 changed paths. The only allowed change is the already-existing \`codex-rs/network-proxy/src/runtime.rs\` leaf. Its source51 Git blob is \`1a449a44381fafa4a5d6a5d0e08753f425f339fc\`; it was **not** in the previous 194 changed-path manifest. The root source52 manifest must therefore contain exactly all unchanged 194 rows plus this leaf: 195 paths.

## Frozen input contract

The input archive has exactly five regular members, with no links, duplicate paths, unsafe names, or implicit extra files:

- \`delta-manifest.json\`
- \`source52-manifest.json\`
- \`candidate.patch\`
- \`before/codex-rs/network-proxy/src/runtime.rs\`
- \`after/codex-rs/network-proxy/src/runtime.rs\`

The delta uses \`hepta.source52-apply-delta.v1\` and contains source-before/after commit/tree, one file row with complete before/after pins, and a full pin for \`candidate.patch\`. The entire source52 manifest and archive are independently pinned. Their actual identities are unknown in this inert template.

## Execution order if separately bound and authorized

1. Reject unbound constants, optimized Python, wrong existing leaf pins, non-Rust/build/dependency paths, or a different expected count.
2. Read and validate the original source51 manifest and four closed r26 originals. Preserve r26's natural outer/test exit100, false timeout/cancellation/retry flags, raw/receipt linkage and unchanged194/HEAD/dual-lock postguard. This is failed-gate provenance, never qualification.
3. Verify exact five-member input bytes, both manifests, every original194 row, candidate before/after and literal forward/reverse patch replay. Independently compare the baseline runtime raw bytes with the source51 Git leaf even though it is outside the old changed-path manifest.
4. Verify complete source51 index/worktree, HEAD \`bef6fa7645df9df12b69fda499e97eed25de6c75\`, both locks and absent unstaged/untracked changes.
5. Run only \`git apply --check\`, recheck all source51/baseline-leaf facts, then \`git apply\`; verify all195 working bytes and exactly one unstaged path; stage only that exact path.
6. Verify the root-expected source52 tree, all195 raw/Git/mode fields, exact one-leaf tree delta, original194 retained, HEAD unchanged and both locks unchanged. Write the source52 manifest and completion only after these checks.

Each of the three Git commands persists its true return code with fsync before reading its output or checking later source facts. Any command/guard failure preserves the real worktree/index, raw result, available diffs and failure record; there is no reset, retry, kill, or automatic restoration.

Completion/postguard schemas are \`hepta.source52-apply-complete.v1\` and \`hepta.source52-apply-postguard.v1\`. They record \`changed_from_source51_paths\`, \`prior_changed_file_count=194\`, \`actual_changed_file_count=195\`, \`before_existing_repo_leaf_not_in_prior_changed_manifest=true\`, complete manifest/delta/postguard pointers and unchanged locks. \`bazel_lock_update_executed\`, \`rust_executed\`, and \`fix_fmt_executed\` remain false.

The original successful **source50** lock update is retained as history for unchanged dependency inputs; it is not renamed a source52 lock run. This preparation runs no build, test, metadata query, formatter, tool installation, Git network/ref operation, or native controller job.

\`build_inert_template.py\` is an offline string/AST derivation from the exact source51 inert reference. \`verify_preparation.py\` performs only local AST/byte/schema checks; it does not import or execute the resulting executor.
