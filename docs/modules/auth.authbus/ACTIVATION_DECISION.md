# auth.authbus activation decision

Status: **BLOCKED pending terminal exact-head, target-host and signed production acceptance evidence**.

This decision is intentionally fail-closed. Source implementation, queued jobs,
static documentation and a successful run for another commit are not production
activation evidence.

## Implemented repository controls

- the raw authority writer is crate-private and product callers use
  `AuthBusAuthorityHost` capability-scoped ports;
- mutation outcomes distinguish not committed, committed-needs-reconciliation
  and unknown durable outcome;
- the owner lifetime is fenced across processes and stale handles are rejected;
- the incremental authority frontier, dirty marker and checkpoint publication
  are bound to the same owner/generation;
- Agentd and Bao source callers are checked against a machine-readable
  no-bypass and ambiguity contract;
- exact-head and deterministic synthetic-merge qualification are read-only and
  a final gate rejects failed, cancelled or skipped required lanes;
- target-host crash, performance and production-drill evidence is generated only
  by protected root-owned harnesses;
- production acceptance requires distinct independent-security and operator
  Ed25519 signatures over the same immutable evidence digest set.

## Mandatory evidence before canary approval

One unchanged candidate SHA and tree must have all of the following:

1. closed-world API inventory, formatting, focused AuthBus tests, Evidence,
   Agentd and Bao product tests, full workspace all-target regression and strict
   all-feature Clippy;
2. terminal-success exact-head and deterministic synthetic-merge receipts whose
   parent, tree, Cargo lock, source, documentation, migration, test-log and
   artifact digests agree;
3. protected target-host receipts for ENOSPC, real power loss, permission loss,
   restored-old-snapshot rejection, owner collision, WAL corruption,
   backup/mutation overlap, trust-generation mismatch, fsync/rename failure and
   checkpoint corruption;
4. the full caller-visible performance matrix at concurrency 1, 8, 32 and 128,
   including slow storage, checkpoint failure and recovery/backup overlap;
5. real KMS/HSM composition, key rotation/revocation/recovery,
   backup/restore and dual-owner/wrong-mount drill receipts;
6. a candidate- and target-bound canary plan and a tested rollback plan;
7. an independent security reviewer signature over the canonical qualification
   payload;
8. a distinct activation operator signature over the security-signed payload,
   activation plan and rollback plan.

The protected production-acceptance workflow may then emit
`approved_for_canary`. It deliberately leaves `productionActivated`,
`canaryPromotion` and `release` false.

## Mandatory evidence before promotion

Promotion requires a later signed canary observation receipt proving that the
named SLO thresholds held for the full observation window, no unresolved
critical AuthBus alert existed, and the tested rollback command remained
available. Rollback must restore a matched database/checkpoint/trust generation.

A queued, skipped, cancelled, deferred, prior-head, copied-status or static-only
check is not evidence of success. This file may be changed to `APPROVED` only by
naming immutable successful workflow run IDs, artifact digests, target identity
and verified signature digests.
