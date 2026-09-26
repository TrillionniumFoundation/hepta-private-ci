# Offline external-authority signer

`hepta-authority-signer` is an offline ceremony boundary. It is a separate
binary from `hepta-supervisord`; it never starts the daemon, generates a key,
publishes an artifact, or invokes a lifecycle mutation.

## Key input

Exactly one source is required:

```sh
--key-file /absolute/owner-only/ed25519-seed
--key-fd 3
```

The file must be a regular non-symlink with no group/world permissions. The
input is either exactly 32 raw Ed25519 seed bytes or 64 hex characters. A file
descriptor is duplicated and never closed by the signer. Private key bytes are
bounded and zeroized after conversion; no private key is written to output.

The signer refuses to operate without an explicit `--sign` acknowledgement:

```sh
hepta-authority-signer --sign --key-fd 3 --request /absolute/review/request.json
```

The request may be `-` (stdin). Do not use key fd 0 together with request
stdin.

## Request operations

The tagged JSON request rejects unknown fields and supports exactly three
operations:

- `h7_envelope` signs a validated H7 artifact, optional OPE evidence,
  transition, runtime generation/predecessor and validity window.
- `production_grant` signs the exact H7 envelope, UUID Agent id,
  source/target release, transition, control/lifecycle CAS fences, authority
  epoch, signer id/epoch and validity window.
- `production_recovery` signs one operator decision for an already quarantined
  transaction. It binds the original grant digest, signed-intent digest,
  `recovery_required` release-transaction digest, observed release id,
  immutable manifest/agentd/matrixd digests, terminal outcome, current
  lifecycle generation, current daemon-derived authority epoch, signer
  id/epoch and validity window.

The response is tagged JSON with exactly one of `envelope`, `grant`, or
`decision`. The H7 envelope remains `local_qualification_only`; only the
separately signed production grant admits a new lifecycle effect. A recovery
decision cannot select a new release or start a process: it can only certify
`committed` or `rolled_back` for the exact durable bytes and quarantined
transaction it names.

The Rust signer uses the exact versioned framed `signing_bytes()`
implementations. JSON serialization is not used as a substitute signing
preimage.

## Recovery signing ceremony

Do not construct recovery fields from memory. First obtain the caller journal,
owner mutation state, release transaction, and current signing context. The
named caller prints the live generation and daemon-derived authority epoch:

```sh
hepta-supervisor-release-controller context \
  --fleet-root /absolute/fleet \
  --agent 018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12
```

The reviewed `production_recovery` request must use:

- `grant_sha256`, `intent_sha256`, and `release_transaction_sha256` from the
  exact `recovery_required` owner state;
- the release already recorded as durable current state, never a desired
  release;
- immutable release digests from that transaction/catalog binding;
- `expected_lifecycle_generation` and `authority_epoch` from the current
  context;
- `committed` only for a signed upgrade whose durable current release is the
  target;
- `rolled_back` for an upgrade whose durable current release is the source, or
  a signed rollback whose durable current release is its target predecessor.

After independent review, sign the request and preserve the complete tagged
response as an immutable decision file. Submit it only through the named
caller:

```sh
hepta-supervisor-release-controller resolve-recovery \
  --fleet-root /absolute/fleet \
  --request /absolute/release-request.json \
  --journal /absolute/release-caller-journal.json \
  --decision /absolute/signed-recovery-response.json
```

The caller persists a no-replay boundary before sending. If the RPC
acknowledgement is lost, run the same command with the same files: the caller
will not resend the effect and accepts success only when the durable owner
transaction binds the exact decision digest and reconstructs the signed
pre-resolution transaction digest.

## Public-key distribution and rotation

The private seed remains outside the repository and target host. The target
host receives only the pinned Ed25519 public keys plus the exact signer ids and
non-zero signer epochs. `hepta-supervisord` requires the complete H7 and grant
verifier triplets together; partial configuration fails startup. The grant
verifier key also verifies `production_recovery`, so grants and recovery
choices share one externally governed signer identity/epoch without creating a
second trust root.

A rotation is a new public key and strictly new signer epoch, deployed as one
atomic service configuration change followed by a daemon restart. Because the
authority epoch is derived from the daemon epoch, grants and recovery decisions
prepared for the previous process cannot be replayed after that restart. Keep
old public material only in the audit archive needed to verify historical
receipts; never allow two active epochs for one production daemon.

## Ceremony checks

The external authority must independently pin both public keys and verify the
H7 envelope before authorizing a production grant. For recovery, it must also
verify that the observed release and immutable digests come from durable owner
state rather than desired operator intent. After signing, the runtime owner
verifies the envelope/grant or recovery decision with the pinned public keys
and exact CAS fences. A successful local verification does not transfer
trust-root ownership.

Never copy the private key into the repository, daemon, Mac, small-host
filesystem, CI artifact, or Dropbox.

## Separate final-use grant signer

The independently invoked `hepta-final-use-signer` implements the distinct
[final-use signing protocol](../hepta-contracts/FINAL_USE.md#independent-signer-operations)
for an exact Bao operation binding. It shares the `production-authority` build
feature but does not change this H7 upgrade/rollback/recovery protocol or reuse
H7 grants as secret-use permissions. The linked design specifies private seed
ownership, canonical signing bytes, lifetime bounds, verifier trust, durable
nonce/revocation state and verification evidence.
