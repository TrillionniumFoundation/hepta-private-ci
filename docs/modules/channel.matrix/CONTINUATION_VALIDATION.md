# Matrix continuation polling and executable evidence

## Scope and ownership

This increment continues PR #992 on the existing Matrix owner. It does not
introduce another sender, state store, signer, provider or production caller.
The nine existing module development documents remain the main specification.
This supplement records the continuation-poll behavior and command-receipt
format implemented in this increment.

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
bounded by the unchanged lease deadline. Stronger transport-specific entry,
canonical wire-content binding and sealed durable entry evidence still require
separate implementation/qualification; this increment does not claim them.

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
