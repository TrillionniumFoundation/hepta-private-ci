# Remaining native fixture and runner storage repairs

This continuation adds three narrow repairs after published source
`48177153ad04605338c3a9a8dbd17defee9981bc`. Their local source checkpoint is
`a54b1862b`; its two Rust fixture changes were independently reviewed before
integration. Original current-source and current-base CI remains required.

## Confirmed defects and changes

| Scope | Evidence and repair | Remaining qualification |
| --- | --- | --- |
| Automation migration fixture | Executing the repository's 19 real migrations and the fixture's 30 SQL statements reproduced the stale timer trigger referring to the deleted dispatch-outcomes table. Drop the later timer and destination-dedupe tables before rewinding. The same real migration replay reaches schema 19 and retains its timer owner. | Full Rust integration test on the published source. The SQLite receipt is not a claim of Rust execution. |
| Windows terminal ledger fixture | The fixture used `File::open` on a directory. Reuse the existing owner's writable directory handle with `BACKUP_SEMANTICS` and `OPEN_REPARSE_POINT`, keeping the real durable flush and directory assertion. | Original Windows native test. Linux inspection and formatting do not establish Windows qualification. |
| Scoped native runner disk | Reuse #3022's bounded Cargo scheduling and removal of optional preinstalled hosted SDKs before compilation. Keep this branch's existing 75-minute job limit, dependency planner, selected owners/reverse consumers, and exact `just test --locked` command. Report disk usage after execution. | The original current-head workflow must complete without disk exhaustion and propagate real failures. |

The SQL negative control and successful replay are retained in
`qualification/owner-fixtures-20261021/automation-rewind-sql.json`.

## Local checks

- Original `just test-github-scripts`: 101 executions passed with pinned Rust
  1.95 available. This discovery count includes the previously documented
  duplicate detector-suite entry point, not 101 unique behaviors.
- The first invocation omitted Cargo from `PATH` and returned six setup errors.
  Its complete log is retained next to the successful invocation.
- `just fmt` and `git diff --check` passed. Formatting changed no Rust source.
- No heavyweight native compilation was started during the live, separately
  pinned Qwen experiment. No model retry, timeout extension, or smaller test
  selection is used to manufacture a passing result.

## Audit evidence boundary

The lossless inventory in `fifth-wave/inventory.json.xz` contains every PR
number 1 through 3021 and 2954 branch names from complete pagination. A later
updated-PR delta preserves the newly observed #3022 and #3023 plus changed
owner heads. The source/base/prospective-merge identity receipt explicitly
belongs to historical candidate `48177153`; it is not a receipt for this
new publication.

This inventory is metadata coverage. It does not certify semantic review of
all branches or authorize their merging. In particular, #3023 adds a `libc`
dependency to the learning-artifact owner while its observed Cargo lock entry
still omits that dependency; it has not been incorporated here. Broad auth,
transport, and research-owner changes remain separately reviewed work.

Every archived file is bound by `fifth-wave/artifact-receipts.json`. The
original repository blob-size limit and allowlist remain unchanged. Research
continues `SHADOW_ONLY / DENY_ALL / NO_GO`.
