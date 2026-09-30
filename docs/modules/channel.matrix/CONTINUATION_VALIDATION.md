# Matrix continuation polling and executable evidence

## Scope and ownership

This increment continues PR #992 on the existing Matrix owner. It does not
introduce another sender, state store, signer, provider or production caller.
The nine existing module development documents remain the main specification.
This supplement records the continuation-poll behavior and command-receipt
format implemented in this increment. Subsequent source commits additionally
sealed the raw SDK entry, persisted the non-constructible entered-use proof,
completed exact migrations 6-11 startup validation and parked sealed legacy
holds; those source facts still require the exact-candidate receipts below.

## Resuming a pending transport future

`outbound_v2::gate::FinalSendGate` refreshes the authenticated revocation feed
and checks the exact claimed authority epoch/revocation revision before every
poll of the lazy transport, including resumption after `Pending`. It also
rechecks the authenticated homeserver/user/device/session identity, cancellation
and the original absolute lease deadline. Synchronous refresh/identity work
never renews that deadline. The kernel entry token is consumed exactly once.

A changed revocation head stops further polling, including unrelated head
advances; this is intentionally fail-closed. An unrelated nonce admission does
not by itself change that head and must not stop an otherwise valid send.
A transport future is not proof that no bytes have been sent. Stopping an
already-entered future because of revocation, feed failure or identity loss
therefore records response loss/indeterminacy, never a pre-entry cancellation
or a terminal negative effect. The stable transaction and attempt history
remain available to durable reconciliation.

This is a local poll boundary, not a lock spanning the homeserver. It cannot
undo bytes already written, independently police work spawned by a transport,
or prove continuous protected-clock authorization until server persistence.
The kernel performs expiry validation at initial entry; transport duration is
bounded by the unchanged lease deadline. The current source now binds canonical
Matrix content, persists the entered-use proof before any network effect and
requires an opaque permit at the SDK facade. This remains a local adapter
boundary rather than a network-wide atomic lock, and exact native/target
qualification is still required.

The six new `pending_poll_regressions.rs` tests exercise revoked grants, epoch
changes, feed failure, device rotation, unchanged authority and unrelated nonce
admission. They use the real kernel verifier and SQLite store with a two-poll
fake transport and verify the durable state/attempt history after reopening.
They are source fixtures, not real-homeserver tests.

## Command receipts and manifest v2

The exact-source and deterministic-base-merge workflow runs the fixed
`focused-tests`, `clippy` and `format` commands through
`scripts/channel_matrix_evidence.py run`. Each command has a separately created,
non-overwriting log and `*.command.json` receipt containing the exact arguments,
source SHA and source-snapshot digest, actual exit code, completion status,
monotonic duration, log bytes/digest and before/after source equality.

Manifest `hepta.channel-matrix-artifact-manifest.v2` only reports
`focusedCommandsPassed=true` when the runner reports success, all three command
receipts are complete/successful, their arguments match the registered commands,
their source/log digests match retained files, source/candidate commit and tree
agree, and final source bytes are unchanged. Invalid JSON, duplicate fields,
placeholder logs without receipts, symlinks, missing steps, altered logs,
nonzero/bool exit codes and interrupted commands cannot produce that result.
Empty output is permitted for a genuinely completed quiet command such as
`cargo fmt --check`; nonempty output alone is no longer proof of execution.
Logs are hashed in bounded memory; logs above 64 MiB cannot qualify. The CI job
owns the process/wall-time limit. A terminated command with no completed receipt
cannot become successful through the always-running artifact finalizer.

These are runner provenance checks, not cryptographic remote attestation. A
compromised runner is not an independent oracle. Passing source commands also
does not certify the scenario coverage of ignored tests, authenticated Synapse,
E2EE/device rotation, backup restore, sustained capacity, operator acceptance,
activation or release. Those claims remain false.

## Source identity

Keep `IMPLEMENTATION_MAP.sourceBase` as historical provenance. The current
candidate SHA/tree and source Git blobs/SHA-256 digests are emitted in external
receipts, because a file cannot contain the SHA of the commit hashing that same
file without self-reference. Qualification never patches the tested checkout.

## Validation performed for this increment

The revised Python verifier suite ran locally: 28 tests passed. These tests use
real temporary Git repositories, deterministic merge objects and subprocesses;
the subprocess fixtures use Python rather than claiming to run Cargo. Python
AST parsing, workflow YAML parsing and every embedded Bash syntax check passed.
The six new Rust tests were not compiled or executed in the current tool host,
which had no Rust/just toolchain. No exact-head native pass, real Synapse run,
encryption/rotation qualification, authenticated restore, acceptance or release
is claimed. Consult the final commit's actual CI artifacts for later execution.

## 2026-09-28: materialization and post-entry error boundary

Continuation baseline: PR #1105, source commit
`1ce711d4494f191b3912fa9c793be810c1de9c90`. The retained bootstrap workspace
(artifact `10936340892`, SHA-256
`61e8a75f6651321081ee57b7868d22b7bdf29c0d6bfe93f0d5063e18db6d198f`)
contains the source snapshot, not a native pass: its `Reject staged recovery
source` step failed and the native-command logs are empty.

The pending entropy patch did not apply exactly because the current grant
fixture also binds `request.attempt` into its previous deterministic nonce.
This continuation rebases that patch against the actual bytes, replaces the
complete old nonce construction with Unix OS entropy, preserves the distinct
wrong-signer negative path, and retains its manual-only recovery-workflow change.
The materializer must remove the staged patch after applying the source; a
patch file alone is never an implemented or qualified repair.

`FinalSendGate::enter_verified_use` now delegates every operation after kernel
entry to `send_entered`, whose return type is `EnteredSend`, not
`Result<EnteredSend, OutboxDispatchError>`. The proof stays attached even if the
post-entry clock sample, binding verification, persistence, cancellation,
freshness check, permit construction, or transport continuation fails. Such
failures remain unknown effects under the original transaction. A `?` cannot
propagate a pre-entry error from this post-entry function. This does not claim
that kernel entry alone means any network bytes were sent. Existing native
`final_poll_regressions` and `pending_poll_regressions` exercise the surrounding
kernel/SQLite paths; they still need execution on the final candidate.

The source-navigation checker referred to a nonexistent migration-10 trigger
name. It now checks the actual replacement trigger and its entered-use join and
failure message, without modifying a historical migration or its checksum.
Regression coverage checks every registered source marker against current
files. Implementation maps also reject duplicate JSON keys at any depth,
non-integer/wrong schema versions, missing operations, duplicate operations and
mismatched design/native operation identities. All three owner operations must
be represented exactly once before source mapping can be reported complete.

Local verification: `python3 -m unittest discover -s scripts/tests -p
 'test_channel_matrix*.py' -v` ran 66 tests, with zero failures or skips. This
includes real SQLite migration fixtures and temporary-Git/real-subprocess
receipt tests; it is not Rust execution. The original snapshot suite ran 62
tests successfully before these changes. No Rust compiler, Cargo, just, Docker,
or usable network resolver was available in the local tool host. Locked native
checks, strict lint, formatting, deterministic merge qualification, authentic
Synapse, encryption/device rotation, authenticated restore, sustained retention
and independent acceptance remain unproved here. Final exact SHA/tree receipts
belong in the existing read-only qualification jobs; no sourceBase self-hash,
unchecked success marker, gate waiver, activation or release is introduced.

## Typed optimization continuation (2026-09-28)

Source baseline `516fe78a0e123ef5d981f62947a5c9ca27898f28` was downloaded from
bootstrap artifact `10953921399`. ZIP SHA-256:
`cde74f3613f35dc6f781422f060fb6fc02101fc68196dfbe939c2dd3a508d3cc`.
Every artifact manifest entry was checked. The bootstrap rejected the staged
recovery directory; its empty native logs are not successful execution evidence.

The retained recovery patch's fixture entropy, strict map parsing, operation
inventory, migration-10 marker and historical documentation changes are carried
forward. Its old gate edit is superseded by the typed admission/entered/settlement
implementation. The one-time authoring workflow is replaced by a bounded exact
patch publisher. Qualification remains read-only; no unknown patch hunks or
failed native checks are discarded. Source presence, compilation, test execution,
real target qualification and independent acceptance stay separate.
