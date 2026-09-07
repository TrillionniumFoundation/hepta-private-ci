# Exact-source deployment and durable learning integration handoff

This is an implementation companion to the existing V8 plan and V8.2 readiness specifications, not a new global plan, cached live status, selection receipt or claim that all work packages are complete. Owners retain their canonical data and effect boundaries. ECP-1 coordinates this handoff; LRN-1, ART-1/2, LRN-2, INT-2 and the C1 vertical slice retain their existing scopes and predecessors.

## 1. One reviewable source stack

Choose one exact reviewed upstream source for a bounded integration candidate. Record source commit/tree, actual target commit/tree, ordered merge parents and all canonical registry digests in external evidence. Do not infer selection from branch names, recency, equal document bytes or administrative privileges. A new source stack must preserve predecessor fixes; unrelated implementation branches are compared and integrated through separately reviewed changes, not overlaid. The current candidate's parent is in Git history, not a mutable pointer here.

Run `python3 tools/hepta-engineering-control/deployment_inventory.py --base FULL_SHA` on the exact candidate. Output is derived solely from committed blobs. It maps all module source roots and Cargo packages to organ roles, canonical schema owners, authoritative writers and readers. HNMF reference is explicitly not a 41st product module. A present crate is NOT a running process. No host, process, physical database, production caller or independent acceptance is invented. The output is an audit artifact, not a new authority registry.

## 2. Required deployment binding per module and organ instance

Before runtime attachment, the owning team must supply: organ role and instance; module and exact package; entrypoint and consumer callsite; host/runtime identity; binary/image digest; configuration/body generation; resources and deadline; owned physical store and schema/migration identity; single-writer fence; observer; revocation source; fallback; and exact rollback predecessor. Empty bindings block attachment. A source checkout cannot discover a live host's identity by itself.

A library shares a host but does not transfer its durable domains to that host. Multiple processes need explicit shard/lease keys before sharing a writer domain. A qualification process must never be silently reclassified as production. Source dependencies/initialization may be acyclic while runtime feedback is cyclic; feedback edges separately bind sampling, delay, gain, uncertainty and stop policy.

## 3. Durable causal learning transaction boundaries

`learning.ledger` is the sole writer of causal decisions, independent observations, credit and logical revocation. Use its existing `DurableLedger` rather than a parallel Python ledger. The host authenticates scope, observer identity and file handles BEFORE admission. Distinct caller-supplied strings are not authentication.

Append order is validate/prepare -> predecessor CAS -> canonical frame -> file sync -> core publication -> independently durable acknowledgement witness -> external acknowledgement. Loss after file sync but before acknowledgement is reconciled from the exact event ID and original predecessor, never blind retry. A failed anchored recovery must not retry through unanchored recovery. Record and segment limits reject; rotation is a separate migration with continuity evidence. Logical exclusion is not physical erasure or deletion from training artifacts.

## 4. Evaluation is not generator self-scoring

`learning.eval` consumes a frozen, ledger-bound dataset and preregistered plan. The terminal observer is not the policy; the evaluator is not the generator; acceptance and selection are separate identities/keys under host enforcement. Dataset joins must bind decision, episode, principal, complete legal set, propensity, outcome watermark, correction/revocation cutoff and objective.

The implemented single temporal holdout and conservative cluster intervals are not generic cross-fitting or proof of causal identification. Repeated decisions inside a dependent cluster cannot manufacture independent samples. Missing or pending outcome is not zero reward. Unsupported candidates return insufficient evidence. Plan, data, code, intervals, multiplicity, retention and resource floors must all be checked before issuing independent eligibility evidence.

## 5. Candidate bytes, registry and next-snapshot reload

`learning.artifacts` owns create-only candidate bytes and lineage. The runtime supervisor owns selection. Candidate registration does not select the candidate. Persist bytes and a canonical registry snapshot, then obtain independent evidence. The supervisor verifies exact objective, compatibility, body/config generation, revocation cutoff, content hash and selected predecessor before a NEW run starts. The old run keeps its immutable snapshot; no mixed-generation layer loading.

Rollback selects an explicitly compatible predecessor for future runs and checks its complete lineage against CURRENT revocations. It must not restore an old registry which predates a forget/revoke event. If the predecessor is revoked or incompatible, abstain/quarantine instead of inventing a safe fallback. Cross-store atomicity uses durable intents/outboxes and reconciliation; two successful file writes do not establish an atomic transaction across stores.

## 6. Minimum executable vertical acceptance

C1 must execute a real request through the named host and ports, log a complete read-only retrieval candidate set, record an independently observed outcome, reopen the causal ledger, fit a bounded candidate from eligible training rows, evaluate a disjoint frozen holdout, persist candidate bytes/lineage, obtain an independent decision, load a new run snapshot, demonstrate changed behavior and perform rollback. A fixture may qualify boundaries but does not prove efficacy.

Mandatory failures: stale CAS; changed retry; acknowledgement loss; truncated acknowledged history; generator/evaluator collision; unknown outcome; mixed objective or generation; revoked training ancestry; corrupt payload; incompatible predecessor; failed reload; process death at publication boundaries; and restore of a pre-revocation backup. Unknown external effects remain indeterminate.

## 7. Completion states and evidence

Track separately: specification-ready, contract-compiles, tests-executed, source-implemented, host-composed, independently-evaluated, next-snapshot-loaded, rollback-qualified and longitudinally-validated. Do not rewrite existing claim ladders or mark a whole parent work package complete from a sub-slice.

Every handoff needs exact DDL/schema or byte format, migration/recovery algorithm, public types and consumers, scalar oracle, error taxonomy, fault points and measured target-host budgets. Synthetic future labels cannot close LONG-1/2/3; fixture credentials cannot close observer/evaluator authentication; a deployment inventory cannot close physical safety, independent acceptance or production selection. These remain explicit blockers until their actual evidence exists.

## 8. All-module execution dossier materialization

The mandatory execution specification is `qualification/module-execution-dossiers/TECHNICAL.md`; the exact forty-module projection is `qualification/module-execution-dossiers/MODULE_DOSSIERS.json`. Every module handoff supplies one immutable record with the following exact fields:

```text
sourceReceipt
moduleGuideDigest
declaredSourceRoots
entrypoints
consumerCallsites
hostRuntimeIdentity
binaryOrArtifactDigest
configurationAndBodyGeneration
ownedPhysicalState
schemaAndMigration
singleWriterFence
terminalObserver
revocationSource
faultResults
resourceMeasurements
fallback
rollbackPredecessor
externalGateDisposition
```

The receipt binds one exact candidate, one module guide revision and one host/configuration/body generation. `entrypoints` and `consumerCallsites` must identify executable symbols or process endpoints and their real callers; package membership alone is insufficient. `ownedPhysicalState`, `schemaAndMigration` and `singleWriterFence` identify the deployed state owner and recovery contract rather than an in-memory qualification substitute. `terminalObserver` names the component that can observe completion, not the policy or dispatcher. `faultResults` and `resourceMeasurements` bind exact target profiles and raw result identities.

For a stateless module, a field may be `none_by_design` only with evidence proving absence. For an external effect, acknowledgement loss remains indeterminate until the named observer or reconciler resolves it. For an adaptive module, the current run remains immutable; any parameter, prompt, skill, code or topology change is an artifact for a later generation.

Each `externalGateDisposition` lists applicable `RDY-EXT-001` through `RDY-EXT-009` gates as open or supported by an external receipt. Documentation, generated status and repository fixtures cannot mark those gates passed. A handoff with an empty required field, a positive authority delta, an unresolved duplicate writer, mixed generations or an incompatible rollback predecessor is rejected before composition.
