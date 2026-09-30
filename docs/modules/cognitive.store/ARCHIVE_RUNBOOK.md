# Authenticated cold-generation archive and restore

## Scope and ownership

This extends ADR-0001 through the existing trusted-host maintenance tooling and
`hepta-memory` read-only recovery oracle. It does not introduce another fact store,
writer, active-generation pointer, signer or erasure service. It implements an
executable encrypted **full-history cold-generation** transfer and byte-exact restore,
not hot-row pruning. Memory predecessors, source revisions, fact sets, tombstones,
revocations and unresolved operation/provenance rows remain in the image.

The v1 recovery cut binds complete logical history. Removing historical rows while
claiming the same v1 cut would be incorrect. Destructive hot pruning still requires
checkpoint-aware schema/contract migration, retained segment resolution in readers,
restore equivalence and independent acceptance. Neither successful encryption nor
an owner-signed deletion receipt bypasses these requirements.

## Preparation

Use the normal owner/host to quiesce and checkpoint a detached cold database. Do not
copy an active database without its WAL. Independently retain and authenticate its
current `CognitiveRecoveryAnchor`, complete image SHA-256, byte count and source
writer generation. The maintenance CLI refuses inputs/outputs inside the named live
fleet root and rejects every source WAL, SHM or journal, including empty sidecars.
It will not quiesce, checkpoint or repair the live owner on the caller's behalf.

Build the checker from the approved source and retain its independently authenticated
binary SHA-256:

```sh
cargo build --locked --release -p codex-hepta-memory --bin cognitive-store-archive-check
```

Prepare an isolated Python environment with `archive-requirements.txt`. The Linux
profile requires OpenSSL Ed25519 verification and the pinned cryptography library.
The checker must be a native Linux ELF. The host invokes the exact retained executable
descriptor after checking its approved hash; a shell wrapper, missing checker, malformed
report or unrelated process failure is not evidence that an invalid cut was rejected.

Keep the 32-byte encryption key in a private file outside the live rollback domain.
Its identifier and SHA-256 are part of the signed operation. Use independently governed
keys and signer trust in deployment; the test keys are not production identities.

## Signed operation contract

The envelope is the existing lifecycle format: `payload`, `signer_id`, `key_epoch`,
`signature_hex`. The signing bytes are `hepta.cognitive.lifecycle-observation.v1`, NUL,
and canonical sorted-key ASCII JSON of payload/signer/key epoch, without whitespace.
Archive purpose is separated by the signed payload schema and action. Unknown fields,
duplicate JSON keys, floats, invalid bounds and invalid signatures fail closed.

`payload` has exactly these fields:

| Field | Binding |
|---|---|
| `schema` | `hepta.cognitive.archive-plan.v1` |
| `request_id`, `action` | bounded operation identity; `archive` or `restore` |
| `owner_agent_id`, `writer_generation` | canonical Agent UUID and archived source generation |
| `anchor` | exact v1 profile, Agent, schema digest and complete state digest |
| `image_sha256`, `image_bytes` | independently authenticated cold image, 1..128 MiB |
| `key_id`, `key_sha256`, `policy_sha256` | governed encryption identity and applicable policy |
| `created_at`, `expires_at` | signed validity interval |
| `input_path`, `output_path`, `live_fleet_root` | normalized absolute paths and excluded live domain |
| `verifier_sha256` | approved native owner checker binary |
| `archive_sha256` | null on archive; independently retained manifest digest on restore |

The host independently supplies BOTH the requested plan digest and current trust digest.
Never derive these expected values from untrusted files during admission. The existing
trust contract has its own revision, expiry, coordinator/owner identities, key epochs and
revocation. Admission is repeated before output reservation and final archive publication,
and before restoring a destination. Changed trust, expiration or revocation stops work.

An archive generation is data provenance, not permission to reactivate that generation.
After a cold restore, any live deployment still uses normal signed bootstrap, a currently
valid witness, a fresh grant/writer generation and the existing exclusive recovery fence.
An obsolete but internally valid backup never becomes current merely by being restored.

## Execute

Use a new output path under an owned private directory; destinations are never replaced.
For archive, input is a checkpointed cold file and output is a new directory. For restore,
input is the retained archive directory and output is a new detached cold file. The same
command consumes either signed action:

```sh
python3 tools/cognitive-store-host-bootstrap/archive.py \
  --plan /trusted/archive-operation.json \
  --trusted-owners /trusted/current-owner-trust.json \
  --expected-plan-sha256 "$REQUESTED_PLAN_DIGEST" \
  --expected-trust-sha256 "$CURRENT_TRUST_DIGEST" \
  --key-file /trusted/keys/cold-archive.key \
  --owner-verifier /trusted/bin/cognitive-store-archive-check
```

Archive staging is bounded and descriptor-checked. The native checker uses the same
schema/full-cut/SQLite-integrity oracle as `RecoveredCognitiveReadOnly`, not a Python
reimplementation or a caller-supplied `true`. Encryption uses AES-256-GCM with a distinct
HKDF-SHA256 key per random 256-bit archive salt and unique counter nonces. Each 1 MiB
segment authenticates the header digest, order and length. Ciphertext filenames are
SHA-256 identities. Manifest publication occurs only after segment fsync and re-admission.

Restore rejects missing, duplicate, reordered, foreign or unregistered files; verifies
manifest/ciphertext/AEAD and full plaintext digest; then reruns the real owner's exact-cut
oracle. A same-filesystem no-replace link publishes the detached result, followed by
parent-directory fsync. No active pointer, source image or retired generation is deleted.

## Failure and reconciliation

An existing destination is evidence of a previous attempt or competing owner; do not
remove it and replay. A partial archive without a complete verified manifest is not
committed. A publication/fsync error is indeterminate: retain the destination, source
and operation identity and inspect them through a trusted ceremony. A current-cut denial
has explicit exit 2 and `owner_cut_rejected`; tooling/infrastructure failures are not
reclassified as an expected security rejection.

Temporary plaintext staging is private and removed on normal cleanup, but unlink is
**not** secure media erasure. Crash remnants, filesystem snapshots, swap and backup copies
remain subject to actual storage-owner policy and the lifecycle reconciliation process.
Encryption keys must never enter artifacts, logs or general receipts.

## Qualification and claim boundary

The dedicated source-head/base-merge plan retains all prior checks and adds an isolated
pinned dependency record, 45 protocol/filesystem regressions and an explicit ignored-test
invocation for `signed_archive_restores_real_correction_and_tombstone_history`. That native
integration writes/corrects/tombstones through the real SQLite owner, archives and restores
through separate Python/native processes, requires the exact original cut, and distinguishes
an explicit stale-cut denial from infrastructure failures. Test signatures and temporary
owners still do not establish real deployment signing governance or host acceptance.

Protocol tests use real Ed25519, HKDF and AES-GCM, but substitute the native owner in most
filesystem cases. Their success is not native compilation or a substitute for the separate
real-owner integration. Exact Rust execution, selected-host capacity/recovery measurements,
hot pruning, physical erasure, backup removal, parameter unlearning and release approvals
remain separate. Reports keep all activation, authority and erasure claims false.
