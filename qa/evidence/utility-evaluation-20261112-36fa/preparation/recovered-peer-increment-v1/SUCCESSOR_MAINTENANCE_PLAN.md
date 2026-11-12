# Successor maintenance: minimal provenance-chain change

Status: design only. No driver, source, native job, Git ref, dependency restoration or maintenance command is executed by this document.

## Fixed inputs

- Reviewed driver: `057da9d456348b1da2a2a6627f7ca20ef04f3a13`, 54,853 bytes, SHA256 `b4972a27ad75806b98c6b62a8e2e652ed75efa6ed71701f5089f8c5dba60adce`.
- Original materialized and dependency-restored source: commit `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, ordered parents `c0f78493f815780f68b9bf5e390a21314d79311f`, `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`.
- Original complete physical inventory: 5,611,182 bytes; SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`; Git blob `e7efbbc915cf80db9f873a2b5f9bf162daf4308c`; 15,188 tracked and physical leaves.
- Original successful materialization RESULT `456f749e7558e18df99172d9c9273cda890b8feb` and supervisor `3e60d21bec849a19efb5d818b43152bfc72486fe` remain unchanged.
- Original successful runtime RESULT `7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09`, environment `8b62ac16f554c1f34ee72974637752f5a3b58aec`, supervisor `3705e1ded34c017b57ee9eb13472f67df0da8e20` remain unchanged.
- The only admitted source delta is `codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_original_ports_tests.rs`, mode 100644, blob `36289de55d67d19d5ed710044efdf7012c08d3a3` to `1cf1bfcfb382dbaffc5b3e33b2d20acaca06b67f`. Packet `a92a472eb5f797973b941abeb88ef08838c905e4` preserves both full byte sequences.

The new canonical commit, tree and actual post-advance inventory must come from Root's frozen successor and an observed successful native source advancement. This document does not invent them.

## Narrow driver changes

| Existing location | Exact change |
|---|---|
| Constants HEAD, TREE, PARENTS, EXPECTED and initial result identity | Bind the new frozen successor; its sole parent must be the exact original 86dd commit. Retain 15,188 leaves. |
| New fixed historical constants | Preserve original 86dd HEAD/tree/parents and complete inventory pin as SEED. They must be literal reviewed identities, not arbitrary values inferred from the new config. |
| validate_materialization, lines 322-331 | Keep all original status, target path, booleans, detached/index/physical checks and five final audit checks. Compare historical source identity/materialized identity with SEED instead of current HEAD/TREE/PARENTS. |
| validate_materialization, lines 336-341 | Compare original destination inventory with SEED inventory. Do not compare it with the new current inventory or rewrite its historical RESULT. |
| validate_runtime_restoration, lines 411-412 and 436 | Compare historical RESULT and ENVIRONMENT_READY source identity with SEED. Preserve exact original job, proof bytes, six observed successful commands, three verified audits, environment-record linkage, paths and all other checks. |
| initial_preflight, immediately after full current inventory/Merkle verification at lines 855-863 | Require one observed successful source-advance proof and independently validate current canonical parent and exact object-tree delta. No fallback when that proof is missing, incomplete or Unknown. |
| validate_config / input retention | Keep current source identity checks; require the new source_advance proof descriptor. Read its original RESULT and supervisor through existing read_input so both remain immutable external controls. |
| Provenance output | Retain the three original proof families separately: materialization, runtime restoration and source advancement. Current source fields always identify the successor. |
| Control identities | Use a new create-only driver/config/output directory or run name and execution key. Preserve the prior failed run and every original record. |

No changes are needed to environment_preflight's original environment, current tool/material byte checks, first global process gate, actual target-free check, launch-entry checks, original execute_logged, stage ordering, postimage collection or raw Git-state equality.

## Minimal added config descriptor

Add only the following proof descriptor alongside the original unchanged materialization and runtime_restoration descriptors:

```json
{
  "source_advance": {
    "job_id": "ACTUAL_NORMAL_TERMINAL_JOB_ID",
    "result_path": "ACTUAL_ORIGINAL_RESULT_PATH",
    "result": {"bytes": "ACTUAL_INTEGER", "sha256": "ACTUAL_SHA256", "git_blob": "ACTUAL_GIT_BLOB"},
    "supervisor_path": "ACTUAL_ORIGINAL_SUPERVISOR_PATH",
    "supervisor": {"bytes": "ACTUAL_INTEGER", "sha256": "ACTUAL_SHA256", "git_blob": "ACTUAL_GIT_BLOB"}
  }
}
```

This is a field specification, not an executable config. The successor source_commit/source_tree/parents/source_inventory and driver identities are also updated only from their actual frozen records. Materialization/runtime pins, all environment/tool projections, original argv, deadlines and 32 GiB minimum remain exact.

## Required actual source-advance facts and independent rechecks

The native advancement RESULT must record the same repository path; exact original commit/tree and full before inventory; exact successor commit/tree/sole parent and full after inventory; the sole admitted path/mode/before/after blob; actual detached HEAD, index-equals-tree and physical-equals-tree completion; final complete source/Git and immutable-input audits; and absence of Cargo, formatter, tests, dependency installation and remote ref mutation. Its normal supervisor terminal must match the actual job. Missing or uncertain completion cannot satisfy the chain.

Reusing existing helpers is sufficient:

1. read_input plus parse_supervisor pins and verifies the original advance proof and its normal terminal. Original before inventory must match SEED; actual after inventory must match both config.source_inventory and the new preflight's full inventory.
2. git cat-file commit HEAD must hash to the frozen new HEAD. Its canonical tree header and complete ordered parent list must be TREE and exactly [SEED_HEAD]. Preserve raw body; do not synthesize a same-tree replacement.
3. Run the object-only complete diff through the existing git helper: diff-tree --no-commit-id --raw -r -z --no-renames --no-abbrev SEED_HEAD HEAD --. Require exactly one complete record: mode 100644 to 100644, the fixed old/new blobs and the exact fixed test-port path. Archive the full raw output. This is not a worktree diff and does not need to refresh the index.
4. Re-read the two changed blob bodies and check their raw Git identities and the frozen before/post SHA256/size pins. No source rewrite or permission adjustment is performed by validation.
5. Keep existing actual full current inventory, require_inventory(EXPECTED), 15,188-leaf count and full physical Merkle equality. The exact one-path canonical diff plus current full physical equality proves every other tracked source file is unchanged, including every original dependency input and all six original launch entries. Those six entries also retain their existing direct byte checks.

This allows reuse of the actual UV/Ruff/V8 preparation while verifying their current bytes again through the unchanged environment_preflight. It does not pretend runtime restoration ran on the successor and does not reinstall or download anything.

## Git-state and failure semantics

The authorized source-advance operation necessarily changes local detached HEAD/index. The next maintenance run establishes its initial_git_state and complete .git metadata from that observed successor, then retains the existing strict byte-equality requirement throughout the new run. Do not compare the successor's index bytes with 86dd's historical materialization index, and do not relax the new run's equality into semantic-only equivalence.

Any proposed diff.autoRefreshIndex=false adjustment belongs only to the original archive_transition worktree-diff invocation and requires the separate actual index-stat finding. This design makes no such finding and does not change that command.

Prior run 1a1d10d8ad0-2564-1bff remains: observed fix returncode 101, non-timeout; fmt not run; no tests; fix.after complete unchanged source and zero postimages; final Git equality audit Unknown. The new chain does not relabel it.

The complete original command log has now been independently fetched and hashed: `e3595315f3e98e4232dfac34d82cbec9032b997c`, 116,897 bytes, SHA256 `e30ead233ff190511d27e06d3465d25aa162bc1f075f50a6114102243b81af93`. It contains one E0425 diagnostic and two summary error lines. This full-log read supplements the previously retained tail-only preparation evidence.

## Unchanged execution limits

- just fix -p codex-hepta-intelligence-eval -p codex-hepta-agentd: 7,200 seconds.
- Only after its complete successful return and retained evidence: just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f: 900 seconds.
- Same execute_logged bytes, 64 MiB bound, preflight and record budgets, actual global concurrency gate, fixed tool pins, current free-space check, failure/Unknown handling and complete raw/postimage retention.
- No tests or qualification are supplied by source advancement or this design.
