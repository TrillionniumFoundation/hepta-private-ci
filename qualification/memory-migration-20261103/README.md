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

The initial repair changes that existing expected ledger to the exact sequence 1 through 15.
All earlier memory, citation and head preservation checks, the legacy header
digest and fields, and all four projection revocation assertions remain
unchanged. Production code, all 15 SQL migrations, schema verification,
dependencies, locks and the seven original ignored declarations are unchanged.
The expected list stays explicit: it is not derived from the implementation.

The initial native run `41725804919` proved Linux's complete original target:
272 passing cases, zero failures, and the seven original ignored probes, followed
by the original Clippy and committed-input checks. macOS failed 158 of 272 active
cases before reaching their assertions; all 158 complete failure blocks report
the same noncanonical cognitive root. The shared positive fixture created its
owned fleet directory through the host's temporary-directory alias. The successor
canonicalizes only that newly created fixture directory. Production admission,
all SQL, and the explicit symlink/junction refusal tests are unchanged.

Windows passed 255 active cases and failed five recovery cases. Those failures
remain open in this successor; its fixture repair does not claim a Windows
recovery fix. The original Windows runner partitions all 267 cases into four
disjoint batches. Each batch reports the other batches as filtered; their union
includes every case once. The reader now checks per-case outcomes against every
summary, equal universe sizes, exact unique coverage, and the exact seven
original ignored probes. Missing or duplicate batches and cases fail. The nine
reader controls include the real Linux pass and both real native failures;
synthetic partition controls are explicitly not native execution evidence.

All three complete original ZIPs, sizes, digests, negative case names and source
inputs are retained under `hosted-398838`. Run `verify_previous.py --repository
<repo> --output <report>` to compare every original input against the actual Git
bytes of `398838d15eaa6f2b68939cb227029c71e1083cc4`. This historical verifier
does not transfer the previous result to changed source.

The isolated qualification uses the complete original Bazel Memory unit target
and its existing Clippy target on Linux, macOS ARM and Windows. It requires the
original migration case to execute, zero failed or uncovered cases across the
complete target, and exactly the original named ignored probes. Per-batch
filtered counts remain in the receipt. Those probes are recorded separately; their
existing exclusions are not represented as zero skips or as qualification of
their stress/performance behavior. The original wrappers, authenticated RBE,
fixed 30-minute job budget and committed lock check are retained. Complete
stdout, stderr, original target XML and logs, and input hashes before and after
execution are uploaded even when a target fails.

These are test expectation and owned-fixture repairs. Local checks establish
the exact source delta and preserve the real negative results; no local Rust
result is claimed. The successor native runs remain required. Keep Draft /
`HOLD_NO_GO` / `DENY_ALL`; broader Memory quality, performance, owner and
production acceptance obligations remain open.
