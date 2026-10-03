# Exact-head memory diagnostic verification

## Result and identity

The missing scoped executable evidence is now available for the three-file memory
transaction refactor. The existing [matrix run 37075372401, attempt 1](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37075372401)
tested source `2357d58ca2ae30baf452abe25dff71c2f020467f`, tree
`31dc912975f5d2f6056131fcf0a25ea3125bf9ea`, against frozen current-main
`c6f90d48c40f7b5267db587bb3c3f4934f1414a8`.

The [source-head job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37075372401/job/111063992585)
recorded these separate successful commands:

- `cognitive_intelligence_writer_tests`: 7 passed, 272 unselected.
- `local_lease_outbox_tests`: 32 passed, 247 unselected.
- `production_writer::`: 18 passed, 261 unselected.
- `cargo clippy --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-memory --lib --no-deps -- -D warnings`: exit 0.

Each test group ran through `just test` and nextest, used one test thread, and
required at least one observed passing test. All four commands returned exit 0;
none timed out, exceeded its output bound, mutated source or reported a failed
test. These are 57 selected passes, not the complete 279-test memory library.
The outbox selection includes its existing subprocess helper entry. The retained
raw nextest output also contains an ignored `profile.local.inherits` configuration
key warning; no test/lint suppression was added. This does not claim all-target
or dependency-wide strict lint success.

The same source-head run passed 233 inference/worker/types tests, 59 Python tests,
two crash tests, one soak test, worker-helper compilation, metadata and scoped
format checks. Its full job still failed.

## Integrity checks

Artifact `11256298848`, named `inference-readonly-37075372401-1-source-head`,
was obtained through the GitHub artifact connector and its returned file ID.
The 24,206,884-byte ZIP matches GitHub's SHA-256:

`fdcf2f421de0c4ee36d42cee27b67cc8936ffd6a397a9ecb2e5d6f5dbf76569e`.

The bounded existing artifact reader accepted its entry paths, sizes and CRCs.
All 16 JSON command records and their raw log lengths/SHA-256 values were checked.
Every before/after snapshot is the same clean source/tree with parent
`b73445ecc703153bdcf7f505beafb9b25f84b89f`; run, attempt, lane, source, tested
commit and frozen base agree. The source archive was inspected without extraction
or execution, and its complete Git tree recomputed to the tested tree above.
The archive SHA-256 is
`7bf07a2f13375344c5ac2af261a9c821066de85d8ae57c6de8cf6c4e8ba018ca`.

All three modified memory blobs exactly match published source refactor
`f2661efafcd4bef72ec22c37ed4947f19ca1e1de`; their identities are recorded in
[VERIFICATION.json](hosted-2357/VERIFICATION.json). Raw records, memory logs,
protected-command logs and toolchain provenance are retained in `hosted-2357/`.
The large metadata log and source archive remain in the verified upstream artifact
and are identified by their recorded hashes rather than duplicated here.
The runner was Ubuntu 24.04 x86_64, image `20260927.320.1`, Rust/Cargo 1.95.0;
workflow SHA `6109c15f0a65b6e8e419a8a98e52c42a08ce73de` is separately recorded
from the tested source. Workflow pins were just 1.51.0 and nextest 0.9.103.

## Boundaries and remaining failures

The protected `commands/` inventory and exact argv still match the unmodified
artifact acceptor. All additive memory records remain under `memory-diagnostics/`.
Running that acceptor against this artifact still rejects it at
`command did not pass: 04-lane-b`. Lane B and global source-map verification
remain failed. Dependency-wide strict Clippy still fails five diagnostics in
paused AuthBus paths: direct SQLite pool connection calls at
`authority_schema.rs:20` and `authority_store.rs:41`, and redundant closures at
`authority_store.rs:524`, `quota_store.rs:70` and `trust_store.rs:241`.

The [base-merge job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37075372401/job/111063992450)
failed its deterministic-merge binding step; command execution and artifact upload
were skipped. It supplies no merge-candidate test result. No merge or current-main
acceptance is claimed.

This receipt closes the scoped memory execution gap only. Artifact integrity is
not independent proof against fabrication by same-UID candidate code. No source
map, historical anchor, aggregate gate, authority, paused AuthBus/Windows path,
host trust installation or live effect is changed by recording this evidence.
Coordinated provenance migration remains unimplemented; activation and release
remain false. The earlier admission supplement continues to describe its own
`c15884e5` source closure and is not reinterpreted as qualification.
