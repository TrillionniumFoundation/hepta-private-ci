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
upgrade is needed. The projection originally added `libc`, `codex-utils-path`
and `pretty_assertions`, using existing resolved versions. The follow-up
dependency check removes the unused Windows-only `codex-utils-path` edge from
Agentd and its Cargo lock entry. No resolved package versions change. The
repository's pinned `cargo-shear` check covers that edge; its eight existing
unlinked-source and doctest warnings remain visible. Windows execution still
requires its own platform CI.

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

## Root and desktop closure

The subsequent stages retain the original Root issuer, five private authority
lanes, protected checkpoint, consumer frontiers, whole SQLite pool guard and
commit hook. They add the Root composition factory and exact Current publication
barrier without importing the historical stack wholesale. The complete closure
is larger than the initial four-crate projection described above.

Main's locked Tokio 1.52 API uses `AsyncFd::with_interest` for the two owned Root
pidfds. Each client exclusively retains its `OwnedFd` until the registration is
dropped; the descriptor number and open file description never change. This
compatibility adjustment does not upgrade Tokio or weaken lifetime checks.

The combined six owning libraries passed 1,229 tests, with 47 explicitly skipped,
using Rust 1.95.0 and the existing lockfile:

```sh
just test --locked -p codex-hepta-contracts -p codex-hepta-memory \
  -p codex-hepta-agentd -p codex-hepta-learning-ledger \
  -p codex-hepta-agent-protocol -p codex-state \
  --lib --test-threads 2 --retries 0
```

The locked normal `codex-hepta-agentd` and `hepta-authority-host` binaries also
built successfully. A separately selected actual X11 qualification used the
final Desktop Session SHA-256
`9567224a7a0da4a03554316ab138d90a377f7ee39d314cccf3feb2e0bb534133`.
The original owner entered the effect once, a stock `xmessage` exited with code
7, and an independently observed native receipt settled the original SQLite
outbox after the test withheld its first reply. That test uses an explicit
qualification issuer and current-cut fixture; it is not production Root or
native Asterinas evidence. Its receipt asserts X11 server injection, not generic
third-party business completion.
