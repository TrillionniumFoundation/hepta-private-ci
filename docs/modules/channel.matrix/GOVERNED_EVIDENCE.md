# channel.matrix governed evidence receipts

Local compilation, native tests, lint and formatting do not prove a real
homeserver, encrypted session rotation, protected restore, sustained capacity or
independent operator/security acceptance. This document defines how the evidence
status renderer may consume those externally governed receipts without treating
them as activation or release authority.

## 1. Trust boundary

The governance policy and public keys must be canonical regular files outside
the candidate checkout. The status command never auto-discovers a trust policy:

```sh
python3 scripts/channel_matrix_status.py \
  --directory "$EVIDENCE_DIRECTORY" \
  --governance-policy /protected/channel-matrix/policy.json
```

A policy has the closed schema:

```json
{
  "schema": "hepta.channel-matrix-governance-policy.v1",
  "namespace": "hepta-channel-matrix",
  "principals": {
    "target_qualification": "matrix-target-operator",
    "independent_acceptance": "matrix-independent-acceptance"
  },
  "publicKeys": {
    "target_qualification": "target-qualification.public.pem",
    "independent_acceptance": "independent-acceptance.public.pem"
  }
}
```

The two scopes require distinct Ed25519 public keys. Key paths are sibling file
names; symlinks, checkout-local trust roots, duplicate JSON fields, path
traversal and oversized inputs fail closed.

## 2. Exact receipt identity

The evidence directory may contain these fixed files:

- `target-qualification.attestation.json` and `.sig`;
- `independent-acceptance.attestation.json` and `.sig`.

Each JSON receipt has schema
`hepta.channel-matrix-governed-attestation.v1` and exactly these fields:

```json
{
  "schema": "hepta.channel-matrix-governed-attestation.v1",
  "scope": "target_qualification",
  "candidate": {
    "commit": "40-lowercase-hex",
    "tree": "40-lowercase-hex"
  },
  "result": "pass",
  "principal": "matrix-target-operator",
  "issuedAtUnixMs": 1800000000000,
  "evidenceManifest": {
    "path": "target.manifest.json",
    "bytes": 1234,
    "sha256": "64-lowercase-hex"
  },
  "checks": [
    "hermetic_homeserver_ack_loss",
    "target_process_restart"
  ],
  "authorityGranted": false,
  "activation": false,
  "release": false
}
```

The candidate commit and tree must exactly match `source.json`. The manifest must
be a sibling regular file with the declared byte count and SHA-256. Check names
are closed-format identifiers, not free-form logs or secrets.

## 3. Signature contract

The detached signature is raw Ed25519 over:

```text
"hepta.channel-matrix-governed-attestation.v1\0"
|| namespace || "\0" || scope || "\0" || exact_receipt_bytes
```

Verification uses the scope-specific public key through `openssl pkeyutl`.
Changing whitespace, candidate identity, manifest digest, checks, result,
principal or any denial flag invalidates the signature. Independent acceptance
is rejected unless target qualification is also present and valid.

Private signing keys and signing operations belong to separately protected
target/operator workflows. They must never be stored in the repository, emitted
to artifacts or made available to a candidate-authored workflow.

## 4. Status semantics

A valid receipt changes only the matching evidence state to `passed`.
`activation`, `release` and `authority_granted` remain `false`. Missing receipts
remain `not_proved`; malformed, tampered, wrongly signed, wrong-candidate or
wrong-principal receipts fail the status command rather than degrading to a
green or ambiguous state.

The evidence status output records the policy digest, public-key digests,
receipt/signature digests, evidence-manifest digest, principal and check
identities. It does not reproduce target logs or message content.
