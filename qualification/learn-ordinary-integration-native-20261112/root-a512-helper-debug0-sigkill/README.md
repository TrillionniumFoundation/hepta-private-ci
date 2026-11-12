# Exact a512 with an explicit debug-zero diagnostic profile

The separate diagnostic helper attempt used the same clean a512 source and changed only compiler debug information, incremental-cache use and build concurrency. All 1,122 compiler-artifact events report debuginfo=0, opt_level=0, enabled debug assertions and enabled overflow checks. The profile is observed from Cargo output, not inferred from environment variables.

After 984.59 seconds, rustc compiling codex-core as a library received SIGKILL. Cargo returned 101 and the outer helper exited 1. No new Rust type-error diagnostic was emitted; no tests executed and no JUnit was produced. This is distinct from the preceding limited-debug attempt, where the helper recorded Cargo itself returning -9. Neither attempt establishes OOM, ENOSPC or timeout as the cause.

The complete compiler JSONL, stderr, helper manifest, command/environment driver and source-before/source-after records are retained. The compiler-profile diagnostic does not substitute for the required original-profile gate. Complete positive, NoUpdate and daemon plus Root cold-restart counts remain zero.
