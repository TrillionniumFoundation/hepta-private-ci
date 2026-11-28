# WAL enum representation and strict Clippy repair

The source and deterministic merge jobs for PR #7262 both failed Rust 1.96.0
strict Clippy on `ControlWalEventV1::Prepare`: its payload was at least 304 bytes,
versus at least 64 bytes for the next-largest variant. This patch boxes only the
private Prepare payload. Its custom event tag, intent encoding, WAL header,
frame chaining, replay loop, authority checks, and rollback behavior are retained.
`PROTOCOL.json` records the unchanged encoding and replay source hashes.

The final candidate passes all 119 existing `codex-hepta-cell-roles` tests and
the crate's strict all-target Clippy command. The original Bellman compatibility
command also passed. **The original complete multi-package CI command did not
complete locally:** its `codex-protocol` Clippy child received SIGKILL before
reaching the WAL crate. These scoped passes do not replace that missing full
gate receipt or the separate failing Windows jobs.

## Actual observations

| Observation | Frozen source | Command / result | Wall time |
| --- | --- | --- | --- |
| `native-01` | `b9be1a277bf664eb4be5fbf39868e74509136edd` | Setup failed because `/usr/bin/time` was absent; no Rust build or test ran | Not a test result |
| `native-02/01` | same | Existing crate tests: 119 passed, 0 skipped; 11 WAL controls | 112.453 s including compilation; 0.410 s tests |
| `native-02/02` | same | Original strict multi-package command: exit 101, `codex-protocol` child SIGKILL 9 | 153.507 s |
| `native-03/01` | same | Crate all-target strict Clippy found two existing test-helper lints | 43.627 s |
| `native-03/02` | same | Original Bellman compatibility strict Clippy: passed | 14.852 s |
| `native-04/01` | `32706bf4e2c0e845617aad640084f4b6a38b0757` | Existing crate tests: 119 passed, 0 failures/errors/skips/flaky failures; 11 WAL controls | 6.141 s including compilation; 0.636 s tests |
| `native-04/02` | same | Crate `--locked --all-targets -- -D warnings`: passed | 4.114 s |

The two test-helper fixes preserve their checks: the false execution-authority
constant is asserted at compile time, while the runtime execution-mode and
`DENY_ALL` assertions remain. A fixture condition whose two branches both
returned `AtMost` now returns that same value directly. No lint suppression or
test deletion was introduced. The compatibility command's source predates only
those two test-helper edits, which are outside the Bellman dependency graph.

## Evidence and limits

`evidence.tar.gz` contains both original CI logs, all local observations including
failures, frozen sources, toolchain/environment records, actual JUnit, peer review,
and resource measurements. `EVIDENCE.json` pins its SHA-256. The archive's
`INDEX.json` lists every original member's byte count and SHA-256, verified by
reading all members back. `RESULTS.json` gives the unrounded command timings,
exit statuses, final source hashes, and precise claim scope.

The multi-package failure's `wait4` peak child RSS was 779,132 KiB. The host-wide
OOM-kill counter increased from 27 to 29 during that command, but no per-PID
kernel event was obtained; the log establishes SIGKILL, not its specific cause.
Ordinary nextest watchdogs, retries, locked dependencies, and strict lint flags
were retained. The shared target was handed to the next task after acquiring and
releasing its nonblocking exclusive lock; no concurrent Rust build was launched
by this task.

Final `just fmt --base d779ed32bb2d235e5a12538b7748bd07b200854f` succeeded after
the tests and Clippy checks. All three Rust files remained byte-identical; no
tests were run afterward. Boxing introduces a heap allocation for a Prepare
event, whose runtime overhead was not benchmarked. These are engineering checks,
with no new model training or foundation-model qualification claim.
