# compact.engine V2 publication, recovery, and qualification protocol

This document is normative for the `MemoryCheckpointCoordinatorV2` production surface. It distinguishes the immutable artifact transaction from the surrounding admission and fencing protocol. A successful artifact transaction is necessary but is not, by itself, the whole product operation.

## 1. Canonical public boundary

Product callers may construct a compaction checkpoint only through the qualified builder and may publish it only as a sealed `VerifiedCompactionPublicationV1` through `MemoryCheckpointCoordinatorV2`. The raw SQLite bundle/store and the legacy record-only compaction path are implementation details and are not public construction surfaces.

The named production caller is `agentd.runtime.compaction-scheduler.v1`, composed by `CompactionCheckpointHostV1`. Agentd must revalidate production authority before every state-changing request.

## 2. Generation and predecessor rules

The qualified kernel proves that the candidate checkpoint generation is the authoritative source snapshot's `compact_checkpoint_generation.next()`.

A newly materialized local durable owner may therefore begin at any positive generation already proven by that snapshot. That first local checkpoint is a local lineage root and must not invent a predecessor digest. Every subsequent checkpoint must satisfy both:

- `generation == active_generation + 1`; and
- `predecessor_checkpoint_digest == active_checkpoint_digest`.

The active-head update is a compare-and-swap inside the immutable artifact transaction. A concurrent loser receives a conflict; it must not silently fork the lineage.

## 3. Three-stage durable protocol

### Stage A — admission reservation

Under the durable owner lease, reserve `(owner, idempotency_key)` and the four role-bound anti-replay nonces. Persist the request digest, owner instance, fencing token, registry digest, and request identity before artifact publication. Equal retries reuse the reservation. Semantic drift conflicts.

### Stage B — immutable artifact transaction

In one SQLite `BEGIN IMMEDIATE` transaction:

1. validate and persist the exact historical trust enrollments;
2. insert the content-addressed payload;
3. insert the immutable candidate;
4. insert the immutable evaluation;
5. insert the immutable proof;
6. insert the immutable checkpoint;
7. advance the active head by predecessor/generation CAS; and
8. insert the publication outbox event.

Commit makes candidate, payload, evaluation, proof, checkpoint, active head, and outbox visible together. Failure before commit leaves none of them visible.

### Stage C — admission finalization

After Stage B commits, change the admission from `reserved` to `committed` and bind its publication/checkpoint/outbox digests. This is deliberately a separate transaction. A crash between Stage B and Stage C is an explicit recoverable state, not a second execution opportunity.

## 4. Restart reconciliation

At startup and before accepting new product work:

1. validate SQLite integrity, foreign keys, required schema objects, immutable artifact digests, and exact active pointers;
2. reclaim expired owner leases and claimed outbox rows only under the new fencing token;
3. inspect every `reserved` admission;
4. when the corresponding immutable checkpoint exists and its exact publication digest matches, finalize the admission as `committed` without rebuilding or republishing artifacts;
5. when no artifact transaction committed, leave or terminally resolve the reservation according to its durable deadline; and
6. never infer success from a changed process ID, a new idempotency key, or a retry.

A replay of a committed equal request returns the original receipt with `Unchanged`. A replay with semantic drift conflicts.

## 5. Revocation, fallback, and GC

Checkpoint revocation is immutable and emits an outbox event. Selection may fall back from a revoked active head to the newest unrevoked predecessor and must expose `fell_back_from_revoked_head=true`.

Payload/checkpoint GC is forbidden until:

- revocation is durable;
- the active head no longer selects the object;
- required outbox delivery is terminally recorded; and
- the source-retention fence deadline has passed.

No checkpoint publication authorizes rewriting or deleting source memory facts.

## 6. Trust and replay boundary

Retention selector, semantic generator, tokenizer, and evaluator are separate trusted roles. Each receipt binds schema version, key ID, trust epoch, validity interval, subject digests, and a non-zero nonce and is verified with Ed25519. Tokenizer receipts prove accounting only; they do not establish generator provenance or evaluator independence.

Current publication requires current trust. Historical reopen verifies the accepted historical manifest and then re-admits the publication against the current manifest before payload return.

## 7. Required qualification evidence

The focused qualification workflow must bind every result to an exact source SHA and run both exact-head and deterministic synthetic-merge modes. Terminal success requires locked build, repository test entrypoint, strict Clippy, rustfmt, and clean worktree evidence.

Crash/recovery qualification must cover at least:

- crash after admission reservation and before artifact commit;
- crash after artifact commit and before admission finalization;
- committed-response loss and equal retry;
- nonce reuse with changed semantics;
- concurrent first-local-root publication;
- concurrent successor CAS;
- stale owner instance after lease takeover;
- claimed outbox recovery;
- active-pointer corruption;
- revoked-head fallback; and
- reopen verification after process restart.

Capacity evidence must separately report the pure-kernel 65,536-record / 64-MiB-payload / 8,000,000-token ceiling and a representative full publish/reopen profile. Until the transient full archive is given an explicit metadata-overhead allowance, the module must not claim that a payload of exactly 64 MiB can traverse the full archive path.

## 8. Claim boundary

Source delivery, focused CI success, product composition, independent semantic acceptance, activation, promotion, and release are separate claims. This protocol does not grant external-effect, deployment, merge, or release authority.
