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

The tagged JSON request has `"operation":"h7_envelope"` or
`"operation":"production_grant"` and rejects unknown fields. H7 requests
contain the validated `H7Artifact`, optional OPE, transition, runtime
generation/predecessor and validity window. Production-grant requests contain
the exact H7 envelope, UUID agent id, source/target release, transition, CAS
revisions, authority epoch, signer id/epoch and validity window.

The response is tagged JSON with either `envelope` or `grant`. The H7 envelope
remains `local_qualification_only`; only the separately signed production
grant has the four positive authority flags. The Rust signer uses the exact
versioned framed `signing_bytes()` implementation; JSON serialization is not
used as a substitute signing preimage.

## Ceremony checks

The external authority must independently pin both public keys and verify the
H7 envelope before authorizing a production grant. After signing, the runtime
owner verifies the envelope/grant with the pinned public keys and exact CAS
fences. A successful local verification does not transfer trust-root
ownership. Never copy the private key into the repository, daemon, Mac,
small-host filesystem, or Dropbox.

## Separate final-use grant signer

The independently invoked `hepta-final-use-signer` implements the distinct [final-use signing protocol](../hepta-contracts/FINAL_USE.md#independent-signer-operations) for an exact Bao operation binding. It shares the `production-authority` build feature but does not change this H7 upgrade/rollback protocol or reuse H7 grants as secret-use permissions. The linked design specifies private seed ownership, canonical signing bytes, lifetime bounds, verifier trust, durable nonce/revocation state and verification evidence.
