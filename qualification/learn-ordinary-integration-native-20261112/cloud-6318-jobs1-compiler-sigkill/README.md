# Exact 6318 with one Cargo build job

The original helper build and its before/after verification succeeded on clean 6318. The subsequent required Agentd/Protocol/Ledger `just test` command failed while building Agentd as a library: rustc received SIGKILL, Cargo returned 101, and no tests or fresh JUnit were produced. The helper and test dependency/feature combinations are different; helper success does not establish the test build. The repository limited-debug profile was retained; only build concurrency changed from two to one.

The complete logs, driver, helper manifest and compiler JSONL are archived. A narrow cache-retirement record is also retained: completed incremental sessions strictly older than this attempt were removed only after acquiring their original session locks and rechecking all mtimes and absence of working directories. Active working caches, dependencies, source and evidence were retained. This record does not establish OOM or ENOSPC as the cause of SIGKILL. No cancellation was requested.

The candidate source bundle and source QA failures are retained in the preceding 6318 compiler observation. Complete positive, NoUpdate and daemon plus Root cold restart counts remain zero.
