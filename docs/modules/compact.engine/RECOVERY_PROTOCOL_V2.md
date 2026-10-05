# compact.engine V2 publication, recovery, and qualification protocol

This document is normative for the `MemoryCheckpointCoordinatorV2` product surface. It separates signed-manifest preflight, durable admission, immutable artifact publication, recoverable finalization and read-time re-admission. Success in one stage never substitutes for the others.

## 1. Canonical public boundary

A product caller may construct a checkpoint only through the qualified builder and may publish it only as a sealed `VerifiedCompactionPublicationV1` through `MemoryCheckpointCoordinatorV2`. Raw durable bundles/stores and the legacy record-only path are not public construction surfaces.

Canonical identities:

```text
memory.checkpoint-coordinator.v2
agentd.runtime.compaction-scheduler.v1
```

The Agentd composition type is `AgentdCompactionCheckpointHostV1`. Agentd revalidates current production-writer authority before every lease, manifest, publication, recovery, revocation, retention or outbox operation.

## 2. Manifest preflight and anti-rollback

Before any lease can be acquired or replaced:

1. verify every manifest signature against the pinned root;
2. verify owner equality;
3. require a root generation followed by strictly increasing predecessor-bound successors;
4. require the final manifest to be current;
5. compare the final manifest digest and root with any durable active manifest.

A stale, forked or wrong-root chain is rejected before durable mutation. After the lower owner opens, the final in-memory registry is compared with durable active state again. Every public operation repeats durable active-manifest equality checks. Recovery performs checks both before and after the read.

## 3. Generation and predecessor rules

The qualified kernel proves:

```text
candidate.generation == authoritative_snapshot.compact_checkpoint_generation.next()
```

A newly materialized local durable owner may begin at any positive generation already proven by that snapshot. The first local checkpoint is a local lineage root and must not invent a predecessor. Every successor must satisfy:

- `generation == active_generation + 1`;
- `predecessor_checkpoint_digest == active_checkpoint_digest`.

The active-head update is a compare-and-swap inside the immutable artifact transaction. The SQLite hardening trigger uses NULL-safe `IS NOT`; a NULL predecessor cannot bypass monotonicity through three-valued logic.

## 4. Three-stage durable protocol

### Stage A — admission reservation

Under the exact durable owner lease, reserve `(owner, idempotency_key)` and the four role-bound anti-replay nonces. Persist request digest, checkpoint identity, owner instance, fencing token, root, active manifest and operation identity before artifact publication. Equal retries reuse the reservation. Semantic drift and nonce reuse with changed meaning conflict.

### Stage B — immutable artifact transaction

In one SQLite `BEGIN IMMEDIATE` transaction, before resolving idempotency or inserting any artifact, parse owner/root/manifest from the sealed archive and recheck:

- exact owner;
- pinned root;
- exact lease token digest;
- exact lease epoch;
- non-regressing lease expiry;
- durable active manifest;
- active manifest root.

A lease takeover, manifest rotation or root substitution between Stage A and Stage B therefore aborts publication.

The same transaction then:

1. resolves identical idempotent replay or rejects drift;
2. validates and persists the four historical trust enrollments;
3. inserts or verifies the content-addressed payload;
4. inserts immutable candidate, evaluation, proof and checkpoint rows;
5. advances the active head by predecessor/generation CAS;
6. inserts the deterministic publication outbox event;
7. commits.

Commit makes payload, candidate, evaluation, proof, checkpoint, active head and outbox visible together. Failure before commit exposes none of the new generation.

### Stage C — admission finalization

After Stage B commits, change the admission from `reserved` to `committed` and bind publication/checkpoint/outbox digests. This is deliberately a separate transaction. A crash between Stage B and Stage C is a recoverable state, not permission to execute again.

## 5. Restart reconciliation

At startup and before accepting new product work:

1. validate SQLite integrity, foreign keys, required schema objects, immutable digests and exact active pointers;
2. verify manifest/root equality and current lease ownership;
3. inspect every `reserved` admission;
4. if the immutable checkpoint exists and the exact publication digest matches, finalize the admission without rebuilding or republishing;
5. if no artifact transaction committed, retain or terminally resolve the reservation according to the durable protocol;
6. return interrupted outbox claims to pending only under the current fence;
7. never infer success from a changed process ID, new idempotency key or retry.

Committed equal replay returns the original receipt with `Unchanged`. Reuse with semantic drift conflicts.

## 6. Cryptographic reopen and current read admission

Reopen is semantic reconstruction, not a row lookup:

1. rehash payload and artifact images;
2. expand the compact durable archive;
3. verify the historical root-signed manifest named by the archive;
4. reconstruct the exact source request, candidate and proof;
5. verify proof witness and durable cross-object identities;
6. re-admit every historical principal against the current active manifest;
7. return payload only after all checks pass.

Historical signature validity does not override current revocation. A manifest transition during recovery is detected by the post-read guard and the read fails closed.

## 7. Revocation, fallback, retention and GC

Checkpoint revocation is immutable and emits an outbox event. Selection may fall back from a revoked head to the newest unrevoked predecessor and exposes `fell_back_from_revoked_head=true`.

Source facts remain owned by the source store. Compaction records a source-retention fence and deadline but never authorizes source rewriting or deletion.

Physical payload/checkpoint GC is forbidden until a separately reviewed fenced transaction proves:

- revocation is durable;
- the active head cannot select the object;
- every durable reference is accounted for;
- required outbox delivery is terminally recorded;
- source-retention release/deadline conditions are satisfied;
- owner lease and active manifest are still current;
- the GC event is inserted atomically.

## 8. Trust and replay boundary

Retention selector, semantic generator, tokenizer and evaluator are separate roles. Each receipt binds schema, role/key/epoch, validity, exact subjects, non-zero nonce and Ed25519 signature. Tokenizer authority proves accounting only. Evaluator principal/key independence from selector and generator is mandatory.

Current publication requires current trust. Historical reopen first verifies acceptance-time trust and then separately applies current read admission.

## 9. Required qualification evidence

The focused workflow freezes one source SHA and runs exact-head, deterministic synthetic-merge and required full-capacity lanes in one workflow run and attempt. Terminal success requires implementation-map/test reachability, locked check, complete compact-engine plus Agentd tests, strict Clippy, rustfmt and clean worktree evidence. The terminal job emits one fail-closed readiness manifest; it refuses missing success markers, identity disagreement, mixed attempts and non-terminal results.

Crash/recovery qualification includes:

- stale/forked manifest rejection before lease acquisition;
- crash after reservation and before artifact commit;
- lease replacement between reservation and artifact transaction;
- crash after artifact commit and before admission finalization;
- committed-response loss and equal retry;
- nonce reuse with changed semantics;
- concurrent first-local-root publication;
- concurrent successor CAS;
- NULL predecessor CAS attempt;
- claimed outbox recovery;
- active-pointer and artifact corruption;
- revoked-head fallback;
- restart reconstruction and incremental successor publication.

Capacity evidence separately reports the pure-kernel 65,536-record / 64-MiB-payload / 8,000,000-token ceiling and a representative full publish/reopen profile. Until an explicit metadata-overhead allowance is implemented, no claim may state that an exact 64 MiB payload traverses the complete archive path.

## 10. Claim boundary

Source delivery, product source composition, terminal CI success, target-host qualification, independent semantic acceptance, activation, promotion and release are separate claims. This protocol grants no external-effect, deployment, merge or release authority.
