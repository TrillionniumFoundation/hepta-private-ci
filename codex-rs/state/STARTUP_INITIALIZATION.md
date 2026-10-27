# State database startup

`StateRuntime::init_inner` creates a private home, resolves its canonical path,
and opens the existing FD-bound dispatch-lock directory before opening a database.
Existing unsafe homes are rejected without changing their permissions. The primary
`state_5.sqlite` is still opened and migrated first; its path, permission, open, or
migration failure starts none of the other databases.

After primary success, logs, goals, memories, and queue open and migrate concurrently.
Each has its own file, SQLite connection pool, transaction and migration history.
The embedded logs/goals/memory/queue migrations do not attach or reference another
database file. The goals foreign key refers to its own `thread_goals` table. Memory
store operations that also need primary state are constructed only after all opens
finish. Paginated thread history retains its separate lazy owner.

All four futures finish before success or failure is returned. Results retain the
previous logs, goals, memories, queue error precedence, including the original error
chain and corrupt-database path used by recovery. A failure closes the primary pool
and every successful independent pool before returning. A per-file migration failure
still closes its own pool in the existing SQLite shim. Initialization publishes no
`StateRuntime` until all schemas, backfill and timestamp queries, and the queue's
existing dispatch-root binding succeed in their original order.

Concurrent initialization changes partial failure side effects: an independent
schema and its SQLx migration metadata may already have been created or migrated
when another independent file fails. These are trusted-home per-file initialization
changes, not a cross-database transaction or rollback. Retrying uses each file's
existing transactional migration/checksum rules. The primary-state failure boundary
and common directory checks remain before the concurrency boundary.

The ordinary pools retain their existing WAL, NORMAL synchronous mode, auto-vacuum,
busy timeout and connection limits. Durable evidence pools, FULL synchronous mode,
commit hooks, Current/writer coordination, owner checks and Root assembly are outside
this change and retain their existing implementation. No authorization is supplied
by successful state initialization.

`runtime/startup_tests.rs` holds a real SQLite logs transaction while requiring queue
migration progress, then checks that the runtime remains unpublished until the logs
lock is released. Additional cases exercise every independent error position and
multiple errors using actual pools, require all successful pools to be closed, retain
corruption error precedence, reject unsafe homes before creating files, and preserve
the primary failure boundary. The test's two-second wait bounds a dependency barrier;
it does not replace the original SDK five-second assertions or qualify a new CLI.
