# codex-hepta-memory-extension

This package adapts Hepta memory to the host extension registry. Its actual
directory is `codex-rs/ext/hepta-memory`; the Cargo package is
`codex-hepta-memory-extension`. The persistent stores and authority ports belong
to the embedding host and `codex-hepta-memory`, rather than this adapter.

## Technical contract

The exported API is in [src/lib.rs](src/lib.rs). The main registry integration
is [src/extension.rs](src/extension.rs):

- `HeptaMemoryThreadConfig::for_features` returns no extension configuration
  when memory is disabled. Memory alone selects digest-only shadow mode;
  governance plus read-only mode enables attachment proposals. Write feature
  state is resolved separately and frozen at thread start.
- `on_thread_start` requires a configured mode, nonempty installation identity
  and host-supplied `ThreadOriginator`. It freezes installation/principal
  digests and limits in thread-local `ExtensionData`. These attribution digests
  are selectors, not credentials. Recall also binds the exact thread and the
  primary absolute workspace.
- Turn preparation performs bounded same-thread recall. A backend read has a
  two-second timeout. Missing/error/timeout backends and source-binding or
  source-time failures produce typed digest-only observations, without an
  attachment. Query and summary limits use UTF-8 bytes; secret-like queries
  do not query the state backend.
- The legacy ephemeral proposal path rereads the state row on each physical
  model send. It checks the request schema, generating turn, thread/turn store
  identities, absolute cwd, revision, source digest, content/token bounds and
  context-window budget. A prepared digest is not sufficient to attach changed
  raw content. Proposals are attempt-bound ephemeral input, not history edits.
- With an available `CognitiveRuntime`, `install_with_turn_writer` installs
  cognitive contributors and optional federation through
  [src/cognitive/mod.rs](src/cognitive/mod.rs). The legacy attachment path is
  used when that runtime is absent. Cognitive `remember`, `correct`, `forget`,
  `recall` and `explain` are defined in
  [src/cognitive/tools.rs](src/cognitive/tools.rs); writes have explicit
  qualification/host mutation gates. A supplied `ProductionCognitiveMutation`
  port does not prove that a production deployment is configured or qualified.

Local rehydration has distinct ownership cuts. `read_local_rehydration_for_turn`
reads host-bound state; `prepare_local_rehydration_runtime` verifies the local
lease/event/outbox fence and returns a read-only plan. Replay consumption in
[src/local_replay.rs](src/local_replay.rs) revalidates turn/fence bindings and
reports `NotStarted` or `Complete`; it performs no write, provider call or
automatic replay. The plan serializes a fencing-token digest, not the raw token.

An explicit `HeptaLocalDevelopmentLifecycleOwner` in
[src/local_development_owner.rs](src/local_development_owner.rs) validates a
qualification-only policy. The host supplies the store and bound lease handle;
lease expiry rejects a mismatched store or missing authority/owner/expiry
binding. It installs no callback, scheduler or retry loop. Witness writes are
separate explicit host calls. Errors preserve policy, witness and lease causes.
The local runtime/replay/owner constants retain their non-production boundaries.

Ordinary `install` supplies no production mutation port or qualification turn
writer. The latter requires an explicit enable flag, validated local policy,
available store and host writer capability. Policy-gated embeddings do not
silently install the older unbound local lifecycle callback. Registry-held
`Arc`s own contributor lifetimes; the embedding owns the database/runtime and
the authority-bearing capabilities it passes in.

## Development and validation

Start at `extension.rs:129` for feature selection, `extension.rs:662` for the
backend timeout and `extension.rs:677` / `:712` for installation. Keep changes
to scope/digest framing aligned with [src/framing.rs](src/framing.rs) and the
underlying contracts; never turn a read-only plan into an implicit writer.

Run the original package lane from the repository root with the pinned
toolchain, lock, profile, two test threads and zero retries:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline \
  -p codex-hepta-memory-extension --test-threads 2 --retries 0 --cargo-profile dev-small
```

[src/extension_tests.rs](src/extension_tests.rs) contains the real existing
`default_shadow_recall_is_same_thread_digest_only_and_never_attaches`,
`read_only_proposal_revalidates_source_and_binds_exact_physical_attempt`,
`missing_error_and_timeout_backends_are_typed_and_digest_only` and
`policy_gated_runtime_never_registers_legacy_turn_callback` cases.
[src/local_development_owner_tests.rs](src/local_development_owner_tests.rs)
covers explicit witness/replay, production-policy rejection and bound expiry;
[src/advisory_observation_tests.rs](src/advisory_observation_tests.rs) covers
missing/tampered input, replay and conflict rejection. Their fixtures include
fake recall backends and owned temporary stores, not a real production issuer.

This manual was source-reviewed against code baseline
`7673ea62fc019f97ad17d205ee1f81f96e0f47a0`. No Rust build or test was run for
this documentation change. It transfers no earlier runtime qualification and
does not establish native Notes/Device execution or the seven production inputs.
