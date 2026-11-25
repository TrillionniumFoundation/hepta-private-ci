# Original-owner checkpoint admission repair

The original protected checkpoint held a receipt MutexGuard across asynchronous
owner RPCs. A capacity-one semaphore now retains the full operation interval;
the receipt mutex is used only for synchronous snapshot/CAS. The acknowledged
Publishing receipt is retained before the Commit RPC. Cancellation fences the
original generation before the operation permit is released. Poison or local
predecessor drift also reuses the permanent original fence.

Two real SQLite/held-Prepare tests cover queued checkout exclusion through both
ACKs and cancellation before the next checkout. The affected older tests use an
independent connection through the shared SQLite shim with busy_timeout=0;
the process-death fixture still writes and fsyncs file then directory before exit.
No production deadline, authority, database, permission, dependency or lint
suppression was added.

## Observed validation

- Job 1a16cc165f8-1b6abb-46b8: 27/27 protected_checkpoint tests passed, including
  the two new tests. An earlier test-only Debug-bound compile error is retained
  in the preceding failed run; it was fixed with an explicit cancellation match.
- That job's strict dependency lint found pre-existing fixture unwrap/direct
  SQLite connection violations. The two fixture files were corrected.
- Job 1a16cd285b6-1b6abb-46f4: all four affected original SQLite-lock and real
  process-death tests passed separately; just fix -p codex-hepta-memory,
  just fmt, cargo clippy -p codex-hepta-memory -p codex-app-server-client --tests,
  and git diff --check all exited 0.
- Clippy used workspace denial rules, not -D warnings; existing warnings remain.
  No full-workspace test or deployed-runtime qualification is claimed.

This branch is based on backend-adapter commit
79d275de109e6efc68e54d7e9f1b2af47619eb3b. All changes ran in an isolated worktree.
No deployed service was changed or restarted.
