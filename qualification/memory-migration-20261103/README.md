# Existing v2 fixture and the compiled migration ledger

The original complete Memory unit target on dependency union
`0b9da54535a7795b2433947a479e6d9e71525e0a` ran 271 passing cases, one failure and
seven existing ignored qualification/child probes. The failure was the final
exact ledger assertion in
`v2_fixture_migrates_forward_preserving_memory_and_revoking_legacy_projection`:
the already compiled migration `0015_shared_experience_use.sql` had run, but
the test still expected only versions 1 through 14. The complete original job
`126171877870`, run `41701057334`, is retained losslessly in
`original-linux-job.log.gz` with decoded and compressed hashes in `evidence.json`.

Change only that existing expected ledger to the exact sequence 1 through 15.
All earlier memory, citation and head preservation checks, the legacy header
digest and fields, and all four projection revocation assertions remain
unchanged. Production code, all 15 SQL migrations, schema verification,
dependencies, locks and the seven original ignored declarations are unchanged.
The expected list stays explicit: it is not derived from the implementation.

The isolated qualification uses the complete original Bazel Memory unit target
and its existing Clippy target on Linux, macOS ARM and Windows. It requires the
original migration case to execute, zero failed or filtered cases, and only
the original named ignored probes. Those probes are recorded separately; their
existing exclusions are not represented as zero skips or as qualification of
their stress/performance behavior. The original wrappers, authenticated RBE,
fixed 30-minute job budget and committed lock check are retained. Complete
stdout, stderr, original target XML and logs, and input hashes before and after
execution are uploaded even when a target fails.

This is a test expectation repair. Local checks establish the exact source
delta and preserve the real negative result; no local Rust result is claimed.
The published native runs remain the required next evidence. Keep Draft /
`HOLD_NO_GO` / `DENY_ALL`; broader Memory quality, performance, owner and
production acceptance obligations remain open.
