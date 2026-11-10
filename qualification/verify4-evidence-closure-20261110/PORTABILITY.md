# Native Windows failure and fixture connection lifetime repair

The first published candidate `0006e834178ff3cbc78bb6059e97ca7be52dc282`
ran all 226 tests on native Windows Server 2025 / Python 3.12.10 / NumPy 2.4.2.
It finished with six errors during temporary SQLite database cleanup:
`PermissionError: [WinError 32]`. The SQLite workload and dispatch smoke steps
were consequently skipped, while failure receipts were uploaded successfully.

- [Original run 42825965141](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42825965141)
- [Original Windows job 129863214055](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42825965141/job/129863214055)
- [Original artifact 13768932510](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42825965141/artifacts/13768932510)

That run is not a success and is not superseded by relabeling the earlier Linux
result. Its decoded original job log is retained in `PORTABILITY.zip`, along
with source snapshots, a deterministic connection-lifetime diagnostic and
follow-up test/format records. `PORTABILITY.json` binds the observations and
file identities; the original uploaded artifact's digest is also retained.

## Cause and scope

The label event-rewrite helper and four repair test blocks used
`with sqlite3.connect(...)`. SQLite's connection context manager handles
commit/rollback but does not close the handle. Linux permitted removal of the
open temporary files, whereas Windows refused removal. Keeping every connection
object alive exposes the resource leak without relying on garbage collection.

Each affected block now uses `contextlib.closing` around the connection and
retains the inner transaction context, so transaction exit happens before
connection close. The repair contention probe also closes its handle in a
`finally` block if rollback itself raises. The tests retain their original
authentication, rehashed-evidence rejection, checkpoint-race and parent/child
commit-order assertions. No assertion is skipped, no cleanup error is ignored,
and forced garbage collection is not used as a fix.

The production journal already closes its connections in `finally`; treatment
and repair use those managed transactions. Independent read-only review found
no production connection leak in the affected paths. This follow-up changes
only the two test files and the qualification documentation/evidence.

## Evidence boundaries

`ENGINEERING.zip`, its original run and `FORMAT.json` remain unchanged historical
evidence. `SOURCE.json` retains their executed identities and updates the two
published test identities with explicit follow-up provenance. The local
connection-lifetime diagnostic and focused regression results establish the
specific repair; they do not substitute for a new native Windows run.

After the repair's tests, required `just fmt` and the scoped Ruff checks are
recorded again. Tests are not rerun after that final formatting step. The PR's
latest explicit-head Linux/macOS/Windows workflow remains the authority for
native results on the final published source. A queued run has no passing jobs.
Scientific admission stays HOLD, production authority NONE, and newly admitted
independent real tasks remain zero.
