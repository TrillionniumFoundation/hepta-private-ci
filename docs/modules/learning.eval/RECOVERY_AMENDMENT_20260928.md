# `learning.eval` convergence amendment — 2026-09-28

This amendment is the current source-level supplement to `TECHNICAL.md` for the
canonical PR #1011 delivery line. It binds the implementation map to executable
source observation `a43cbc5c167f9acfb8130c108693623641662ff0` / tree
`2fbe5a357dd1a4c7217320e91b9027b477d61b96`. It records source presence only;
exact-head and ordered-parent merge execution remain required.

## Closed source gaps

The canonical source now contains:

- module-owned canonical typed archives for single- and multi-outcome
  qualification; arbitrary caller-provided sealed/Debug byte vectors are no
  longer the recovery contract;
- internal V2/V3 reconstruction and signature, expiry, revocation, role, scope
  and timing verification during cold recovery; no public recovery callback can
  return a prebuilt decision;
- Agentd measured-outcome consumption bound to current owner state and a signed
  exact-use payload over run, objective, snapshot, predecessor, candidate set,
  selected candidate, evaluation, execution and publication;
- a persistent bounded selected-host recovery controller and cursor that advances
  past unresolved attempts without rerunning providers or estimators;
- full lifecycle reservation before `IntentPersisted` and a rebuildable pending
  index over unresolved work;
- canonical reducer checkpoints retained under a domain-separated independent
  anchor, with original-journal tail replay and no source truncation;
- actual temporal cross-fit execution over every preregistered fold with exact
  lineage coverage, held-out decision uniqueness and recomputed output digest
  equality;
- fixed-analysis cluster confidence bounds for finite-horizon PDIS/DR under a
  preregistered absolute trajectory-return envelope.

The successful attempt lifecycle is now seven events:

```text
IntentPersisted
  -> HoldoutConsumed
  -> ComparisonSealed
  -> QualificationArtifactsPersisted
  -> QualificationDecided
  -> PublicationPending
  -> Published
```

The sustained source profile therefore configures 4,096 attempts and **28672**
lifecycle events. It creates each checkpoint 64 attempts before a 128-attempt
restart, so checkpoint recovery includes a nonempty append-only tail.

## Remaining repository-controlled closure

1. The final immutable source and its ordered-parent synthetic merge must both
   pass formatting, compilation, default/compatibility API checks, owner and
   consumer tests, process-fault tests, strict lint, measured coverage and the
   sustained profile with retained commit-addressed artifacts.
2. The source facade/controller must be bound to an authenticated independently
   administered anchor authority, real provider and publication store on the
   declared target topology.
3. Near-capacity admission, unresolved backlog, checkpoint rotation, cold startup
   and sustained recovery must be measured on that selected topology.

## Claim boundary

**External gates remain false.** Source code, source tests and repository CI do
not self-issue target-host qualification, independent acceptance, production
activation or release. Real future-calendar outcomes, independent measurement
provenance, retention/change-point/power/subgroup/privacy evidence, unlearning
and backup non-resurrection evidence, operator/semantic acceptance, selection,
canary, promotion and release authority remain separate requirements.
