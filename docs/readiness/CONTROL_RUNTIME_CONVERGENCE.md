# Control runtime convergence candidate

**Module:** `control.runtime`  
**Owner:** `runtime-control`  
**Deputy:** `security-authority`  
**Candidate ref:** `codex/control-runtime-convergence-v1`  
**Authority delta:** none

This document describes the source candidate introduced to close planner integrity,
durability and execution-boundary gaps. It is not an activation, independent
acceptance, promotion or release receipt. The machine-readable current claim
boundary remains `docs/readiness/LANE_D_MATURITY.json`; native symbol mapping
remains `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

## 1. Subsystem boundaries

The crate contains several independently mature surfaces and must not be reported
with one undifferentiated completion bit.

| Subsystem | Current candidate role | Production claim |
|---|---|---|
| Global planner | bounded snapshot, resource floors, NDU projection, immutable decision and grant requests | read-only Agentd caller exists; effectful global caller remains uncomposed |
| Planner durability | owner-local complete-envelope framed store with recovery and external checkpoints | source candidate only; no selected production writer profile |
| Planner execution closure | authority adapter, immediate revalidation, effect adapter, terminal receipt and reconciliation | boundary candidate only; no named production authority/executor |
| Organ host | compiled-in read-only, single-hop host with generation replacement and quarantine | product caller and activation not established |
| Embodiment reference | synthetic cart and fixed-priority timing fixtures | reference only; no hardware activation |

## 2. Strict public planning admission

The public planner facade rejects supplied owner summaries that are outside the
exact requested owner set. Extra summaries can no longer shorten snapshot expiry
or poison required-owner readiness masks.

The facade also rejects duplicate final-payload digests. The lower-level canonical
planner remains responsible for stable sorting and digest construction, but the
public boundary no longer treats duplicated effect identity as harmless input that
may be silently repaired.

These checks preserve the existing missing-owner observation semantics: a snapshot
may record a missing required owner, but it cannot admit an unrequested owner.

## 3. Durable planner store candidate

`PlannerStoreV1` persists complete canonical envelope bytes rather than only a
receipt digest. Its v1 format provides:

- an explicit schema version and record kind;
- bounded record and envelope counts;
- an owner-local create-new writer lock;
- operation-identity idempotency and conflicting-reuse rejection;
- framed records with semantic digests;
- `sync_data` before in-memory publication;
- recovery to the last complete verified frame when only the final frame is partial;
- fail-closed behavior for corruption inside a complete frame;
- deterministic crash failpoints before write, after write, after log sync and around atomic replacement;
- same-directory temporary files, file synchronization, atomic rename and directory synchronization;
- complete-log checkpoints bound to a non-zero externally supplied anchor;
- suffix compaction that invalidates the predecessor checkpoint;
- checkpoint-required backup and verified restore.

The external anchor is not minted by `control.runtime`. A production owner must bind
it to an independently retained signed evidence receipt, TPM/TEE measurement or
another approved ledger. The current create-new lock is an owner-local single-writer
candidate; selected-host crash ownership and stale-lock recovery remain part of
host qualification.

## 4. Authority-separated execution closure

The execution candidate follows this sequence:

```text
authenticated owner inputs
  -> global snapshot
  -> prepared candidate set
  -> NDU evaluation
  -> durable plan decision
  -> authority-free grant request
  -> independent authority decision
  -> immediate current-state authority revalidation
  -> final-payload-bound effect executor
  -> terminal or indeterminate observation
  -> durable terminal receipt
  -> reconciliation without blind redispatch
```

`PlannerAuthorityConsumerV1` and `PlannerEffectExecutorV1` are composition
boundaries. The planner cannot implement either trait for itself by declaration,
and the source candidate does not name or activate a production authority or
effect owner.

Before dispatch, the closure verifies request expiry, all critical digests, grant
expiry, the exact final payload and the revocation frontier. A revocation or
indeterminate authority state stops before the executor. A terminal receipt carries
`DENY_ALL`; it is evidence, not a reusable capability.

`PlannerStoreV1` implements the terminal-receipt sink so succeeded, failed and
indeterminate observations can be persisted with operation idempotency. An
indeterminate operation is reconciled by identity and is not blindly replayed.

## 5. Qualification fixtures

The source candidate adds negative and recovery fixtures for:

- unexpected owner injection;
- duplicate final payload identity;
- simultaneous writer exclusion;
- complete-envelope reopen;
- partial final-frame recovery;
- complete-frame corruption rejection;
- crash after frame write and idempotent reopen;
- compaction followed by independently anchored backup and restore;
- revocation after initial authorization but before dispatch;
- final-payload drift between request and grant;
- terminal receipt persistence;
- indeterminate-effect reconciliation without redispatch.

These are source fixtures until the exact source head and deterministic synthetic
merge complete package tests, all-target compilation, strict lint and named-host
qualification.

## 6. Remaining product work

The following states remain explicitly false:

- selected production planner store and stale-lock recovery policy;
- named effectful global planner caller;
- named `kernel.authority` adapter with current revocation evidence;
- named effect executor and terminal observation owner;
- request-level final-use binding of the complete context plan receipt;
- monotonic request lease profile for the Agentd cognitive-context adapter;
- disk-full and filesystem-loss target-host evidence;
- long-running overload and backpressure evidence;
- organ fan-out idempotency and partial-delivery reconciliation;
- independent semantic acceptance;
- canary, rollback rehearsal, activation, promotion and release.

No document or source fixture may advance these states. Each requires the named
product composition and its exact-candidate execution receipt.
