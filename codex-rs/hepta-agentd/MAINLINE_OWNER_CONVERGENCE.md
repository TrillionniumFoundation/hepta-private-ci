# Original owner dependency closure on main

This stage projects the original durable-owner implementation onto main
`f8c9419df6ddeb36ff8b522a50219981fb8d9345`. Its source is the reviewed Notes
owner stage `f91a5d6109ec7e1786746a72bb30452b911b364f`, whose previous stack
base was `6d6097da843f5831dfaf9cee3530da512d072a15`.

The full historical difference contains 130 commits and 544 changed files.
This projection retains the exact owning API closure in four crates:

- `hepta-memory`: original CognitiveStore exact-cut recovery, FinalUse-gated
  outbox, immutable operation bindings, Notes typed receipts and retirement.
- `hepta-agentd`: original writer composition, independent grant-provider
  channel, Notes private descriptor bootstrap, close barriers and bounded
  round-robin observation.
- `hepta-agent-protocol`: the original Objective admission/history wire needed
  by the Agentd owner; this does not create a second Objective signer.
- `hepta-learning-ledger`: original run-start journal publication verification
  required by Objective history. This was the final missing compile dependency.

Seven unrelated Agentd cleanup/test-refactor files were left at main. No
application, third-party vendor tree, general CLI refactor or dependency-version
upgrade is needed. Cargo.lock adds only the original Agentd dependencies
`libc`, `codex-utils-path` and `pretty_assertions`, using existing resolved
versions. Windows path handling is retained but requires its own platform CI.

The large mechanical source projection is intentionally one coherent buildable
stage: separating out the owner implementation while leaving its control wire
or journal publication API absent produced unresolved APIs. Subsequent X11 and
Root authority work remains a separate stage and is not evidence for this one.

## Verification boundary

The locked owning-library compilation passed on Linux with Rust 1.95.0:

```sh
cargo check --locked -p codex-hepta-memory -p codex-hepta-agentd --lib
```

A successful check confirms the type and dependency closure, not a deployed
Root, an authenticated current cut, an actual desktop effect, or native HOS2
execution. The four owning library suites passed together: 682 passed, 11 skipped,
including the real writer-process kill/recovery test. The original Agentd
locked binary build also passed; scoped lint and formatting complete the
review preparation. This build does not itself execute the daemon.
Existing qualification fixtures remain explicitly non-production. No local
SQLite hash, fixture issuer or historical acceptance report is promoted to
independent production authority by this projection.

The owning test invocation was:

```sh
just test --locked -p codex-hepta-memory -p codex-hepta-agentd \
  -p codex-hepta-agent-protocol -p codex-hepta-learning-ledger \
  --lib --test-threads 2 --retries 0
```

Temporary databases used an ordinary ext4 SSD directory; no tmpfs or mocked
SQLite persistence replaced the original owner. The ignored actual GUI and
privileged qualifications remain separately selected and reported.
