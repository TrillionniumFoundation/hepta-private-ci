# Partial bridge validation

Baseline: `fe4b945b259c1bf1367c107a36994786b8e56cc1`.

The additive shared DTO stage has seven focused passing tests and strict library
lint. The source-proof/admission stage has 103 passing infer-core library tests,
including four exact-preimage tests and six durable admission/replay tests; one
existing maintenance soak remains skipped. Strict library/test Clippy passed via
`just fix -p codex-hepta-infer-core --lib --offline --locked -- -D warnings`.
`just fmt` completed; unrelated inherited Python formatting was restored.

The new source proof checks the existing signed V2 payload preimage, then keeps
only its bounded run/context/envelope relationship. Bound reservation, replay
and compaction preserve that relationship. Schema 3 is emitted only when bound
metadata exists; schemas 1 and 2 reject such metadata. Legacy dispatch refuses
bound records, and no production caller enables the new profile yet.

These tests do not establish a working cross-owner bridge. Agentd typed dispatch/abort/publication methods, durable outbox, late conflict
notice and product caller migration remain unimplemented. The transition design
continues to specify that future work. Parent independent source review found no concrete blocker in the core and actor
changes; it did not independently rerun Rust tests. Windows retained-file support and authenticated
generation migration remain separate open work.

The core tests used an isolated offline target with one build job, debug info
disabled and incremental compilation disabled. Logs are retained verbatim;
LOG_HASHES.json records their SHA-256 values. The narrow Codespell exclusion for
the earlier guarded-send raw diagnostic log directory preserves original compiler
text. That configuration change awaits an executable Codespell check or CI.

## Sealed writer stage

The existing FIFO writer now accepts the opaque proof through its sealed port.
Three actual-writer tests passed: duplicate admission/restart, deliberately lost
response with preserved durable state, and request/proof substitution rejected
inside the writer. Strict selected worker library/test lint passed using
`just fix -p codex-hepta-infer-worker-host --lib --offline --locked --no-deps -- -D warnings`.
This does not claim dependency-wide lint: inherited dependency warnings remain.
No proof cloning, new executor, effect permit or product activation was added.

The remote branch advanced during publication to upstream repair
`87adc636164945376fd271fba5e9050906448b2e`. Its three workflow/verifier/test files
were preserved by rebase, with byte-identical Rust source before/after. The
repaired five-suite Python command passed 59 tests with the workflow's
`PYTHONPATH=scripts`. New-head hosted CI remains pending. The strict trusted-base
verifier boundary from that upstream repair is retained.
