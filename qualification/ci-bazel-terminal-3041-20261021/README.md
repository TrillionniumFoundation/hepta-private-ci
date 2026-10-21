# Original CI terminal evidence for source 52293403

These are original job logs for PR 3041 source
`52293403ea1e06465c41d24d39b54959bad40936`, base
`48177153ad04605338c3a9a8dbd17defee9981bc`. Blocking CI checked out merge
`938c9ba28ce60ae1f13291a20bd78329be14eb97`. This evidence does not qualify
the later PR 3054 source or a changed base.

| Job | Original result | Observed scope |
| --- | --- | --- |
| 119206185314, Windows shard 1 | failure | Git wrapper exit timed out; two Core cases failed on their first attempt before the original flaky retry passed. |
| 119206185259, Windows shard 2 | failure | Full log and 66 distinct first-panic contexts retained. |
| 119206185416, Windows shard 3 | failure | Queue manual-idle race and Matrixd unsupported peer identity. |
| 119206185425, Windows shard 4 | cancelled | Operator Acceptance, Shadow Qualification, and Exec Server filesystem targets failed before cancellation. |
| 119206185293, macOS Intel test | cancelled | The last original progress record shows 21 / 571 tests and unfinished compilation. |
| 119206185104, macOS ARM Clippy | cancelled | V8 C++ compilation remained active. |
| 119206185142, GNU/Linux release | cancelled | V8 C++ compilation remained active. |
| 119206185164, GNU/Linux test | cancelled | The last original progress record shows 21 / 571 tests and unfinished compilation. |
| 119206184539, SDK | cancelled | Full original log retained; no completed failed test target was reported before cancellation. |
| 119206185086, macOS ARM release | cancelled | Full original log retained; compilation was unfinished. |
| 119206185231, macOS ARM test | cancelled | Intelligence Eval's immediate lock recovery returned Busy; the HTTP route fixture received WouldBlock and then ConnectionReset. Both failed test targets precede cancellation. |
| 119206185356, Windows Clippy | cancelled | Full original log retained; no Rust error diagnostic was reported before cancellation. |
| 119206185260, Linux musl test | cancelled | Full original log retained; unfinished compilation is not a passed test suite. |
| 119206185376, GNU/Linux Clippy | cancelled | Full original log retained; unfinished compilation is not a passed Clippy gate. |
| 119220992411, Architecture required | success | Original aggregate completed at 13:02:38 UTC, after both original source-head and base-merge jobs passed. |

The Architecture job belongs to original run `39591475937`; the remaining
jobs belong to original blocking run `39591475871`. Earlier complete
Architecture source/base logs are already archived in
`qualification/ci-architecture-terminal-3041-20261021` in this branch's
history; this new aggregate receipt closes only that original aggregate's
previously pending status. It does not make blocking CI pass.

Every XZ file round-trips to the full connector-decoded UTF-8 log, including
BOM and original line endings. Companion JSON includes byte counts, raw and
compressed SHA-256, job/step metadata, and diagnostic scope. The first-panic
indexes are navigation aids. Original cancellations remain cancellations,
including those with earlier real failures; elapsed time alone does not
identify who initiated cancellation. No job was cancelled or rerun by an
agent and no workflow assertion, timeout, concurrency rule, or permission
was changed for these receipts.
