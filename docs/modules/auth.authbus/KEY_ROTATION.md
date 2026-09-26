# auth.authbus key rotation and custody

Status: production security procedure

AuthBus separates message, settlement and trusted-time issuer purposes. A key is
never authorized implicitly for another purpose, even when the same organization
controls both signers.

## Production providers

The activation record must name one implementation for each role:

| Purpose | Public-key registry | Private-key custody | Online signer |
|---|---|---|---|
| Message admission | owner-controlled private registry or SQLite authority | workload KMS/HSM identity | named ingress producer |
| Settlement | SQLite authority registry | settlement KMS/HSM key | named provider/settlement signer |
| Trusted time | SQLite authority registry | independent time-authority KMS/HSM key | named time attestor |

Private keys must not be stored in the AuthBus SQLite database, checkpoint,
configuration file, log or qualification artifact. The authority stores public
verification material and lifecycle state only.

## Custody requirements

- hardware-backed or managed KMS/HSM key where supported;
- non-exportable production private key;
- purpose-specific key and IAM role;
- signing API bound to the exact domain/versioned preimage;
- audit log for key creation, policy changes and every production signature;
- least-privilege service identity and environment separation;
- two-person approval for emergency revocation and production registry changes;
- independent backup/recovery plan for signer availability, not private-key
  export into application storage.

## Planned rotation

1. **Prepare.** Create a new key under the same purpose and issuer identity with
   `next_epoch = current_epoch + 1`. Record key ID, algorithm, custody policy and
   public key fingerprint.
2. **Enroll.** Add the new epoch through the fenced authority host. Do not replace
   the registry file or database by hand.
3. **Distribute verification state.** Atomically publish the owner-controlled
   registry/configuration containing the new epoch. Verify ownership,
   permissions, digest and deployment acknowledgement.
4. **Switch signer.** Configure the named signer to emit only the new epoch.
5. **Observe overlap.** Continue verifying the previous active epoch for the
   bounded overlap window needed for in-flight messages/settlement evidence.
6. **Revoke old signing authority.** Prevent new signatures at the KMS/HSM policy
   layer before marking the epoch revoked in AuthBus.
7. **Revoke in registry.** Update the exact `(purpose, issuer_id, epoch)` and
   verify product callers reload it.
8. **Drain/quarantine.** Reconcile or quarantine outstanding work using a sealed
   revoked handle or issuer-retirement receipt; never a caller-created revoked
   object.
9. **Retire.** Retire the old epoch only after the retention and audit window is
   satisfied.
10. **Record.** Persist the old/new fingerprints, revisions, checkpoint frontier,
    deployment acknowledgements and workflow receipts.

Epoch reuse is prohibited. Rotation does not permit purpose change.

## Emergency compromise

1. Stop the affected signer and revoke its KMS/HSM permission.
2. Stop affected admission/settlement traffic if the exact compromised scope is
   not yet known.
3. Revoke the exact purpose/issuer/epoch through the authority host.
4. Publish the new registry/checkpoint and verify all consumers reload it.
5. Enumerate every message, reservation and settlement admitted under the epoch.
6. Quarantine unprocessed deliveries only through verified revoked authority
   state. Mark ambiguous dispatched work indeterminate.
7. Rotate to a fresh epoch and fresh private key; do not reactivate the
   compromised epoch.
8. Conduct an incident review and re-run exact-head qualification before traffic
   resumes.

## Trusted-time key rotation

Trusted-time rotation additionally requires monotonic continuity:

- the first attestation from the new epoch must not reduce wall time or source
  revision;
- the source digest must identify the same or explicitly migrated time source;
- overlap must not permit two authorities to advance incompatible frontiers;
- rollback and stale-attestation tests run before cutover.

## Settlement key rotation

Settlement evidence may arrive after dispatch. Keep old public verification
material for at least the maximum reservation lifetime plus provider receipt
retention. Revocation prevents new settlement authority but does not justify
silently releasing quota for unresolved operations.

## Registry publication

Registry files are written to a temporary file in the same private directory,
fsynced, atomically renamed and followed by parent-directory fsync. Consumers
verify canonical path, owner, permissions, regular-file type, single link, size
and metadata stability. Publication tooling must emit a digest and revision that
are included in the deployment receipt.

## Rotation drill

Before activation and quarterly thereafter, staging must demonstrate:

- planned rotation with old/new overlap;
- wrong-purpose and wrong-epoch rejection;
- revoked-key admission and settlement rejection;
- signer rollback rejection;
- fake quarantine rejection;
- emergency revocation with outstanding held and dispatch-attempted work;
- restart from the post-rotation database/checkpoint pair.
