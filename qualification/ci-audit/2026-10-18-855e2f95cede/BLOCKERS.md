# Current blocker disposition

Compiled 2026-10-18T15:42:48.243164+00:00. This is an open-blocker checkpoint.

| ID | Status | Owner | Next action |
|---|---|---|---|
| CI-001 | FIX_PUSHED_NATIVE_AND_REQUIRED_CI_PENDING | Existing PR #1350 Result propagation owner; inventory agent reviewing to avoid duplicate implementation | Run canonical just test plus required Clippy/platform checks at 19c5cd41 with enough disk; no merge until genuine required success. |
| CI-002 | FAILED | #2800/#2805 SQLite fixture owners; semantic comparison required | Use codex_state::sqlite connect_pool with explicit in-memory SqliteConnectOptions preserving max_connections(1); execute migration/schema test plus Windows Clippy. Do not allow the forbidden method. |
| CI-003 | FIX_PUSHED_NATIVE_AND_REQUIRED_CI_PENDING | Fleet authority fixture owner; historical #2746/#2735 overlap needs verification | Run canonical just test plus required Clippy/platform checks at 19c5cd41 with enough disk; no merge until genuine required success. |
| CI-004 | FAILED_INFRASTRUCTURE | Runner/build footprint owner, historical #2776 disk reclaim to inspect | Inspect per-job disk before/after and Cargo test debug/link/archive layout; constrain duplicate outputs, retain full platform/test coverage, rerun same head. Do not classify as code compile failure. |
| CI-005 | FAILED | #2789 ZIP exact-parent diagnostic owner | Review genuine diagnostic proposal artifact 12138013270 against exact Cargo/MODULE parents, regenerate lock with repository's Bazel version, commit complete lock and verify --lockfile_mode=error plus ZIP tests/security. No manual fabricated lock. |
| CI-006 | FAILED_FAIL_CLOSED | Moving target branch owners #2789/#2790 and architecture workflow owner | Snapshot event BASE_SHA/SOURCE_SHA and current pull merge-ref parents/tree, diagnose drift, create/retest exact candidate. Preserve validation; add explicit immutable mismatch receipts if improving diagnostics. |
| CI-007 | FAILED | #2812 source owner; #2814 fix branch has different base, cannot blindly substitute | Run pinned just fmt on same exact source tree and retain relevant Rust hunks; validate full scope before claiming Ruff fix closed blocking-ci. |
| CI-008 | FAILED_CAUSE_NOT_ACCESSIBLE | #2814 owner | Obtain runner diagnostic/retained receipt or rerun eligible exact-head job; do not assert ENOSPC/timeouts without logs. |
| CI-009 | CANCELLED_NOT_SUCCESS | #2815 Objective admission owner | Run canonical local tests on exact candidate while queue is unresolved; fresh required CI remains needed. Independent Architecture success is insufficient. |
| CI-010 | FAILED_DETAIL_NOT_ACCESSIBLE | Security owners #2695/#2790/#2789, fixed-parent semantic merge needed | Run pinned cargo-deny against exact lock under available authorized runtime or retrieve bounded existing receipts; do not re-label historical 13 advisories as current verified count. |
| CI-011 | FAILED | Windows fixture owners including #2813 and existing git/migration branches; per-failure ownership in inventory DAG | Compare existing narrowly scoped patches and preserve canonical/authority boundaries; execute targeted Windows regression followed by full current required matrix. |
| CI-012 | FAILED_NEEDS_ISOLATION | V8/matrixd/evidence/supervisor owners; no local reproduction yet | Run each isolated failed target with exact Windows toolchain and source/merge provenance. Distinguish shared-process V8 initialization from genuine ABI/feature mismatch. Do not skip tests. |
| CI-013 | PENDING | Respective PR owners and runner scheduling owner | Continue authorized local exact-source testing and avoid redundant matrix fanout. Required remote terminal results still needed. |
| CI-014 | BLOCKED_EXTERNAL | Connection/organization administrator | Use an authorized terminal/API with administration visibility to inventory runner online/busy/groups/concurrency; never claim zero running tasks or full utilization without access. |
| MAP-QUALIFICATION | FAILED_26_MODULES | Per-module source-map owners | Review original provenance and actual source with each owner. Do not bypass checked_identity, invent parents or transfer execution claims. |
| NATIVE-DISK | BLOCKED_EXTERNAL | Accessible executor resource owner | Use an accessible independent build workspace with enough disk. Preserve concurrent owners and the canonical test/Clippy/platform gates. |
| RESEARCH-DECLARATIONS | FIX_PUSHED_REQUIRED_CI_PENDING | PR #2714 | Verify exact f191cd08 required checks; contract tests and boolean statements are not independent scientific qualification. |
| MEMORY-FRESH-112 | BLOCKED_EXTERNAL_RESOURCE_AND_NO_GO | PR #1452 / independent evidence reviewer | Use a worker fitting the pinned model and locked protocol, start a new batch, finish 40 calibration then 72 nine-arm calls, independently review answers/citations/holdout/cost. |
| SHARED-STEM-EMPIRICAL | SHADOW_ONLY_NO_GO | PR #2695 and Shared Stem owners | Run pinned shared-versus-replicated ablations with budget receipts, isolation, negative-transfer and forgetting measurements. |
| OS-FINAL-USE | UNQUALIFIED | Hepta #2815 -> Desktop #193 -> #194; A04/A05/A06/A07 | Verify the same-head stack and complete authenticated broker/Final-use positive and negative cases on real native platforms. Missing authority continues to deny effects. |
| FULL-SEMANTIC-COVERAGE | NOT_COMPLETE | Feature and integration owners | Continue by owner DAG. Verify semantic superiority and exact current gates before closing, deleting or merging. |

BLOCKERS.json retains original run/job IDs, source SHAs and failure locations. Full logs and commands are in ci-evidence.tar.gz. A repair commit is not a merge or a terminal required-check success.

Strict source-map qualification is a separate remaining gate. The observed blocking contract gate uses the development profile; do not assert that the 26 qualification failures caused a queued job to fail.
