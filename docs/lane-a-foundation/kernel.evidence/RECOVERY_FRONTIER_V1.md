# Kernel evidence recovery frontier protocol

This path is retained for compatibility with earlier documentation links. The
current production contract is **Recovery Frontier V2**. Legacy V1/local
frontier formats remain readable only where explicitly supported; their local
integrity fields do not by themselves establish authenticated production truth
or independent freshness.

The protocol is a required activation ceremony. Repository source can validate,
store and consume frontier records, but an independent frontier is not created
by writing another row into the same SQLite database or by placing another file
beside it.

## 1. Threat model

A valid SQLite image can still be stale, replaced, copied from another host or
restored behind a revocation/correction frontier. `PRAGMA quick_check`,
migration checksums and canonical row digests detect local corruption; they do
not prove freshness against an attacker or operator holding an older complete
database image.

The anti-rollback witness must therefore live in a rollback domain independent
from `hepta_evidence_2.sqlite`. Local integrity, authenticated frontier truth and
independent anti-rollback are separate properties and separate readiness flags.

## 2. Production V2 frontier

`EvidenceRecoveryFrontierV2` binds at least:

- schema version, immutable `storeId` and strictly increasing
  `frontierGeneration`;
- a transactionally collected recovery snapshot and `ledgerRootSha256`;
- database lineage, migration-set digest, qualification high-water/frontier and
  AuthBus replay frontier;
- issuer-trust registry digest;
- frontier-signer registry digest and signer-policy generation;
- external backend identity digest;
- build artifact, qualification receipt set and backup publication digests;
- exact source commit and source tree;
- creation time;
- one or more signatures containing signer principal and key epoch.

Signatures cover a domain-separated canonical preimage and do not sign their own
signature bytes. Production verification resolves every signer through the
current independently admitted signer registry, applies key validity/revocation
and threshold/independence policy, and rejects policy downgrade.

A V2 record does not become current merely because its signature verifies. It
must also satisfy the closed-world merge state machine and the external
backend's monotonic CAS/history contract.

## 3. External history and segmented storage

The repository supplies a locked-file reference backend and a production
segmented successor. Both require an owner-private backend identity pinned from
outside the evidence database. Ordinary writes are serialized by one store
lock, reread the current durable frontier under that lock, and append only when
classification is `IncomingWins`.

The segmented backend retains:

- an active bounded JSONL tail;
- immutable segment bytes;
- immutable segment metadata containing byte and record-chain digests;
- predecessor and skip pointers;
- an atomic latest index used as a projection, never as semantic authority.

On load, sealed segments are followed to genesis, reversed into chronological
order and replayed through `classify_frontier_merge`. The archive-to-active
boundary is then replayed through the same classifier. Segment, metadata, record
and latest-index digests are all checked. Rehashing a source, migration or trust
change therefore remains `RepairRequired`; digest consistency cannot upgrade it
to an automatic successor.

## 4. Backup publication protocol

One admissible backup is created in this order:

1. Fence new product writes and wait for current SQLite transactions to finish.
2. Produce a transactionally consistent SQLite backup image.
3. Re-open the image read-only and run migration-ledger, schema-manifest,
   canonical qualification-row, lineage and foreign-key verification.
4. Compute image, migration-set, qualification, replay and ledger-root digests.
5. Bind the exact build, source/tree, qualification receipts, trust registries,
   backend identity and backup object.
6. Read and authenticate the latest external frontier and history boundary.
7. Prepare generation `N+1` and durably persist the local publication intent.
8. Compare-and-swap the exact frontier against generation `N`.
9. Require durable acknowledgement from the independent backend. If the result
   is uncertain, retain the same operation and reconcile authenticated
   latest/history; never create a replacement operation.
10. Only after acknowledgement may the image be labelled an admissible backup.
11. Unfence product writes.

A timeout, lost acknowledgement, signing failure, conflict or uncertain external
durability is `recovery_required` until exact reconciliation completes.

## 5. Startup and restore admission

Before admitting any restored database for product reads or writes:

1. Load owner-private issuer, signer and backend identities.
2. Verify rollback-domain separation, canonical paths, regular-file type,
   ownership, permissions, link count and bounded size.
3. Replay and verify external history, including all automatic transition
   decisions and the active boundary.
4. Verify current signer principal/key epoch/validity/revocation, signature
   threshold and signer-policy generation.
5. Re-open and verify all local SQLite integrity and migration invariants.
6. Recompute the authenticated local recovery snapshot in one transaction.
7. Require exact equality with the frontier's snapshot, ledger root, store,
   backend, source/build/qualification/trust and backup subjects.
8. Atomically accept the frontier and applicable trust generation at that exact
   snapshot.
9. Reject a structurally valid database that is old, differently enrolled or
   not represented by current external history.
10. Attach Agentd only after every check succeeds.

A restore behind an externally observed revocation/correction is rejected. It is
never interpreted as absence of the revocation.

## 6. Repair transitions

Source, build, qualification set, migration set, issuer authority, backend or
store changes are not ordinary overwrite fields. They classify as
`RepairRequired` unless covered by a separately specified automatic transition.

`FrontierRepairAuthorizationV1` cryptographically binds one current digest and
generation to one higher target digest/generation, plus reason, operator,
issuance/expiry, nonce, authority key ID/epoch, algorithm and trust-root
generation. The repository implements this exact verifier.

Normal legacy and segmented CAS methods still reject `RepairRequired`; a signed
document is not accepted as an ordinary publication capability. A production
repair publisher must durably consume the nonce, retain the full authorization
and current/target audit subjects, and perform only that one transition. Such a
publisher and its independent ceremony are not currently source-composed in
Agentd. Until they are separately qualified and activated, a repair decision is
a stop condition.

## 7. Retention and non-resurrection

- Base evidence, corrections and revocations are append-only.
- An externally committed generation is never deleted or overwritten.
- Segmentation may bound the active tail, but immutable segment and record chains
  must remain verifiable across the complete retained horizon.
- Backup retention covers the evidence horizon and at least one accepted
  predecessor generation.
- Missing evidence, replay high-water, trust history or frontier history never
  becomes positive proof.
- An older binary may start only when it can interpret current migration and
  frontier schemas and verify current external authority; otherwise use a
  forward recovery binary.

## 8. Backend and qualification requirements

A production backend provides authenticated latest/history reads, conditional
write/CAS, durable acknowledgement, monotonic generations, signer/key rotation
with revocation, capacity alarms and a rollback domain independent from the
local evidence filesystem. The checked-in locked-file/segmented implementation
is a reference adapter whose real filesystem and failure semantics still require
target-host acceptance.

Qualification injects at least:

- process kill across local commit, dispatch and acknowledgement windows;
- WAL/rollback-journal interruption;
- file fsync, rename and directory-fsync interruption;
- disk/inode exhaustion;
- torn, corrupt and fully rehashed but semantically invalid frontier history;
- stale valid frontier and generation conflict;
- complete database plus frontier rollback;
- backup/restore and restore-behind-revocation;
- multi-process first-generation contention;
- repair/recovery versus append/publication contention.

Every scenario emits a machine receipt bound to the same source/tree/base,
workflow/run/attempt, runner and target identity. Hosted-runner success is not
external backend deployment, target-host acceptance, repair-service activation,
promotion or release.
