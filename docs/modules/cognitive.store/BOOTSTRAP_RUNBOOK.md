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

## Initial admission

1. Quiesce or establish a new store and capture `CognitiveRecoveryAnchor` from one coherent transaction.
2. Persist and authenticate that witness outside the rollback domain.
3. An external authority service chooses a nonzero authority epoch, owner epoch, writer generation, lease expiry and opaque token.
4. Hash the raw token into `tokenSha256`; keep token bytes in the separate `0600` file.
5. Build authority-state revision 1 with no predecessor and sign `cognitive_authority_state_signing_bytes` using the trusted Ed25519 key.
6. Build a bootstrap manifest that binds the state semantic digest, exact current cut, source commit/tree, canary id and a rollback generation floor strictly greater than the writer generation. Sign `cognitive_production_bootstrap_signing_bytes`.
7. Atomically install the four files, then call `open_cognitive_production_host_from_signed_bootstrap`.
8. Retain the returned bootstrap receipt and run `execute_cognitive_bootstrap_canary`.
9. Capture/sign a new current-cut witness after the canary before a restart ceremony.

## Live verification and revocation

Before every semantic mutation, Agentd rereads trust and authority state. The same revision must have the same digest. A successor must be exactly revision+1 and name the observed predecessor digest. Revoked trust/state, expiry, field drift, regression or skipped revision fences the writer.

To revoke, publish the exact next signed authority-state revision with `revoked=true` and the prior semantic digest as predecessor. Historical committed writes remain historical truth; the next write is denied.

## Rotation and restart

1. Stop admission and reconcile in-flight/indeterminate operations.
2. Release the current writer lease and drop the host generation.
3. Capture the exact current cut.
4. Issue a fresh token and grant digest.
5. Publish the exact next signed authority state with strictly newer writer and owner generations.
6. Publish a new signed bootstrap binding the new current cut/state and a higher rollback floor.
7. Reopen, reconcile, run canary and retain receipts.

Do not reuse a token, grant or writer generation.

## Rollback generation

Rollback uses the same current durable data only if the rollback binary is schema-compatible. `validate_cognitive_rollback_successor` requires the exact predecessor state, fresh grant and token, strictly newer writer/owner generations, non-regressed authority epoch and the manifest's rollback floor. An old backup or old authority state is never a rollback shortcut.

## Active pointer ambiguity

If recovery may have published the active pointer but durability is uncertain, preserve the candidate and predecessor, stop admission and classify `COG-INDETERMINATE`. Inspect the active pointer and generation files under a trusted recovery ceremony. Never delete the candidate or fall back to ordinary open.

## Target-host qualification

Retain receipts for signed-file identity checks, exact recovery, canary/reopen, rotation, restart reconciliation, live revocation, rollback successor, pointer fault injection and the SLO profiles. Source tests do not substitute for the selected host/filesystem/device profile.
