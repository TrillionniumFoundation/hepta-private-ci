# Memory transaction API refactor

Separate source commit fc5c687e0c groups borrowed correction source/revision/facts and outcome transition kind/allowed states/result/exact-replay policy. Public APIs, transaction ownership, BEGIN/commit order and existing mutation/validation/hash/receipt bodies are unchanged. Source inspection checked both transaction function bodies byte-for-byte after the new input destructuring. Parent independently reviewed all three changed files with no concrete source blocker.

Scoped rustfmt check and git diff --check passed. No Rust build, test or strict lint was run for this new source: disk had approximately 773 MiB free, and deleting the sole owned completed admission test executable would recover only 147,453,464 bytes. That useful test binary and all shared libraries were retained. No dependency, SQL statement, receipt grammar, production trust or paused AuthBus/Windows file changed. The source refactor is not yet executable-qualified.

Planned focused validation from codex-rs, with CARGO_BUILD_JOBS=1, CARGO_INCREMENTAL=0 and dev/test debug=0:

    just test --offline --locked -p codex-hepta-memory --lib -E 'test(cognitive_intelligence_writer_tests) | test(local_lease_outbox_tests) | test(production_writer::)'
    cargo clippy --offline --locked -p codex-hepta-memory --lib --no-deps -- -D warnings

No cached memory test executable was found. Existing PR workflows will provide hosted evidence: hepta-knowledge-graph-qualification.yml contains the full memory library suite, while hepta-inference-readonly-matrix.yml reaches dependency-wide strict lint. Earlier workflow gates may prevent later steps; their admission/result must be reported rather than treating publication as a pass. No new or manually dispatched workflow is introduced.

Canonical maps remain unchanged. The separate admission source supplement is pinned to its earlier source and does not claim these memory changes, new qualification, ancestry repair or activation. Memory/source-root observations will need their own reviewed update when executable validation is available. Remaining Agentd dead-code/large-enum/multiargument findings and genuine absent plasticity product callers remain separate work.
