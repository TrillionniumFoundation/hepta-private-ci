# Signed production bootstrap runbook

The bootstrap ceremony is owned by a trusted host outside Agentd. Agentd verifies signed inputs and opens the writer; it never holds the signing key or manufactures authority.

## Files

All paths are absolute, canonical, regular, single-link and outside the Agent home and fleet rollback domains.

| File | Mode | Contents |
|---|---:|---|
| signer trust | `0600` or non-group/world-writable | signer principal, key epoch, Ed25519 public key, revocation flag |
| bootstrap manifest | `0600` or non-group/world-writable | exact recovery anchor, lease id, writer/rollback generations, authority-state digest, canary id, source commit/tree, signature |
| live authority state | `0600` or non-group/world-writable | grant digest, epochs, expiry, writer generation, token digest, revocation, predecessor state and signature |
| opaque token | `0600` | raw externally issued token bytes; never JSON/logged |

The canonical schemas and signing-byte functions are in `codex_hepta_cognitive_store::bootstrap`.
The trusted deployment host also supplies `CognitiveProductionSourceIdentityV1` from its independently authenticated deployed commit and tree. Never copy the expected identity from the manifest being verified. The public constructor validates syntax, not build attestation.

## Initial admission

1. Quiesce or establish a new store and capture `CognitiveRecoveryAnchor` from one coherent transaction. After the transaction commits, the owner normalizes the exact database and existing WAL/SHM/journal descriptors to private `0600`, single-link files. Redirected, cross-owner, hard-linked, special-bit or group/world-writable inputs fail closed rather than being repaired.
2. Persist and authenticate that witness outside the rollback domain. Permission normalization does not sign the cut, prove currentness or grant recovery authority.
3. An external authority service chooses a nonzero authority epoch, owner epoch, writer generation, lease expiry and opaque token.
4. Hash the raw token into `tokenSha256`; keep token bytes in the separate `0600` file.
5. Build authority-state revision 1 with no predecessor and sign `cognitive_authority_state_signing_bytes` using the trusted Ed25519 key.
6. Build a bootstrap manifest that binds the state semantic digest, exact current cut, source commit/tree, canary id and a rollback generation floor strictly greater than the writer generation. Sign `cognitive_production_bootstrap_signing_bytes`.
7. Atomically install the four files and supply the independently authenticated deployed identity in `CognitiveProductionBootstrapFilesV1::expected_source`.
8. Call `open_cognitive_production_host_from_signed_bootstrap`. A valid signature targeting another source candidate is rejected before writable recovery.
9. Retain the returned V2 bootstrap receipt and run `execute_cognitive_bootstrap_canary`.
10. Capture and independently authenticate/sign a new current-cut witness after the canary before a restart ceremony.

The input bootstrap contract remains V1; the returned `CognitiveProductionBootstrapReceiptV2` uses the V2 receipt namespace and binds source commit/tree. `recovered_state_sha256` identifies the independently authenticated pre-lease recovery cut; `opened_state_sha256` identifies the owner after writer-lease admission. Creating the lease can change the cut without changing Memory contents. Do not equate these two cuts or reuse the pre-lease witness for a later restart. Historical V1 receipt semantics are not silently changed.

## Live verification and revocation

Before every semantic mutation, Agentd rereads trust and authority state. The same revision must have the same digest. A successor must be exactly revision+1 and name the observed predecessor digest. Revoked trust/state, expiry, field drift, regression or skipped revision fences the writer.

Writable recovery repeats live authority verification and expiry checks after copy/checkpoint/current-cut validation and before synchronous active-pointer publication. A denied final check closes the unpublished candidate; it does not publish a new active generation. This is a final-use boundary, not a claim of an atomic transaction with an unrelated external authority service.

To revoke, publish the exact next signed authority-state revision with `revoked=true` and the prior semantic digest as predecessor. Historical committed writes remain historical truth; the next write is denied.

## Rotation and restart

1. Stop admission and reconcile in-flight/indeterminate operations.
2. Release the current writer lease and drop the host generation.
3. Capture the exact current cut, including the completed lease lifecycle, and retain it independently.
4. Issue a fresh token and grant digest.
5. Publish the exact next signed authority state with strictly newer writer and owner generations.
6. Publish a new signed bootstrap binding the new current cut/state and a higher rollback floor.
7. Reopen, reconcile, run canary and retain receipts and a fresh externally authenticated witness.

Do not reuse a token, grant or writer generation. A crash after commit but before external witness publication requires trusted reconciliation, not a witness derived from a suspect backup.

## Expired operational evidence

The existing host `bootstrap.py inspect` authenticates historical evidence without granting admission. Authenticated terminal transitions, indeterminate recording and governed rollback preparation remain possible after the old lease expires. `verify` for admission and transitions that reactivate or prepare activation still require a current grant. Recording rollback evidence does not execute a rollback or authorize a writer.

## Rollback generation

Rollback uses the same current durable data only if the rollback binary is schema-compatible. `validate_cognitive_rollback_successor` requires the exact predecessor state, fresh grant and token, strictly newer writer/owner generations, non-regressed authority epoch and the manifest's rollback floor. An old backup or old authority state is never a rollback shortcut.

## Active pointer ambiguity

If recovery may have published the active pointer but durability is uncertain, preserve the candidate and predecessor, stop admission and classify `COG-INDETERMINATE`. Inspect the active pointer and generation files under a trusted recovery ceremony. Never delete the candidate or fall back to ordinary open.

## Target-host qualification

Retain receipts for signed-file identity checks, deployed source identity, exact recovery, pre/post-lease cuts, canary/reopen, rotation, restart reconciliation, live revocation, rollback successor, pointer fault injection and the SLO profiles. Source tests do not substitute for the selected host/filesystem/device profile.

The [current implementation note](IMPLEMENTATION_UPDATE_20260928.md) describes the normal read capability, release recovery measurements and read-only storage-owner lifecycle reconciliation. Owner attestations do not by themselves prove independent physical erasure or production acceptance.

The signed selected-host evidence contract and required dispositions are executable in [HOST_QUALIFICATION.md](HOST_QUALIFICATION.md) and `tools/cognitive-store-host-bootstrap/host_qualification.py`. Its complete result authenticates the owner receipt set but deliberately leaves host qualification, SLO acceptance, activation and release decisions false pending independent review.
