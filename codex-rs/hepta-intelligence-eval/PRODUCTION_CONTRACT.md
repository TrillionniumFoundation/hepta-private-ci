# `learning.eval` production contract

This file is the normative public-surface, durability and ownership contract for
`learning.eval`. The architectural guide, native mapping, Lane E matrices and
execution dossiers may add detail but may not weaken this contract. Generated
lexical source truth is recorded in
[`docs/modules/learning.eval/CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).

## Authority boundary

An evaluation may establish eligibility for a later independent consumer. It
never selects, activates, promotes, deploys or releases a candidate. Evaluation,
attempt, admission, archive, checkpoint, compaction and qualification receipts
remain `AuthorityPosture::DENY_ALL`.

Source presence, source tests and repository CI are not target-host qualification,
independent acceptance, activation or release authority.

## Public and internal surfaces

| Surface | Classification | Required use |
|---|---|---|
| `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | default product evaluation ingress | persists intent before provider/holdout access and records consumption before observations are released |
| `RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts` and selected-host qualification methods | default product qualification ingress | derive and persist the canonical typed recovery archive before current V2/V3 verification, decision and durable publication |
| `RecordedProductEvaluationRunnerV1::qualify_and_persist` | crate-internal unarchived composition helper | never cross-crate product ingress; retained only for owner-local tests and composition beneath the archived entrypoint |
| `freeze_product_evaluation_plan_v1` | production plan freeze | freezes metric roles, estimator mapping and candidate/baseline temporal identities before holdout use |
| `CrossFoldPlanV1::execute_temporal_cross_fit_v1` | bounded statistical source executor | executes every preregistered temporal fold and requires exact lineage and recomputed output-digest equality |
| `SequentialPlan::estimate_cluster_intervals_v1` | fixed-analysis sequential confidence source | adds conservative clustered intervals under a preregistered absolute return envelope; it is not anytime-valid |
| `admit_signed_eligibility_v2` | consumer-bound non-product admission | authenticates one exact evaluation and binds an authority-free result to one concrete consumer use |
| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | crate-internal verification primitives | never cross-crate product ingress |
| `ProductEvaluationRunnerV1` | raw compatibility runner | crate-private by default and public only with `trusted-inprocess-eval` |
| `FencedFinalHoldoutOwnerV1` + `FinalHoldoutCasStoreV1` | required contended holdout owner | linearizable CAS, writer fencing and accepted-or-unknown recovery |
| `ReconciledProductQualificationSinkV1` | canonical publication adapter | load-before-write and exact read-after-indeterminate reconciliation |
| `LockedFileProductEvaluationAttemptJournalV1` | concrete attempt journal | complete lifecycle, capacity reservation, unresolved index, checkpoint and tail replay |
| `AnchoredProductEvaluationAttemptJournalV1` | default durable journal capability | acknowledges append only after file sync and independent anchor CAS |

The `trusted_inprocess` compatibility module is absent from default builds.
Production manifests must exclude `trusted-inprocess-eval`, including transitive
feature unification. Compiler-negative fixtures, not comments or lexical scans,
are required to prove the default public boundary. Those fixtures also require
that another crate cannot call the unarchived recorded qualification helper.

## Statistical source contracts

### Temporal cross-fit

`CrossFoldPlanV1::execute_temporal_cross_fit_v1` executes an already frozen
analysis contract. It canonicalizes fold order and requires:

- exact one-to-one coverage of declared folds;
- exact training and held-out principal, episode and window lineage sets;
- no held-out decision identity reused across folds;
- bounded aggregate rows and action cells;
- actual `fit_temporal_fold` model and prediction digests equal to the
  preregistered fold digests.

The executor does not authenticate caller-supplied provenance and does not turn
synthetic fixtures into real future-calendar efficacy evidence.

### Sequential confidence

`SequentialPlan::estimate_cluster_intervals_v1` layers conservative fixed-analysis
cluster intervals over finite-horizon PDIS/DR. The confidence plan, minimum
cluster count and absolute trajectory-return envelope are preregistered. Too few
clusters or an observed estimate outside the envelope is a typed evidence gap.

Cluster labels remain supplied evidence requiring independent provenance. This
surface does not provide anytime-valid confidence sequences, adaptive-stopping
safety, exchangeability proof or causal identification.

## Signed admission and typed recovery

For a successful product qualification, the canonical order is:

1. freeze plan, roles, estimand and measurement semantics before final-holdout
   access;
2. reserve the complete remaining journal lifecycle before admitting a new
   attempt;
3. append and acknowledge `IntentPersisted` before provider manifest lookup or
   final-holdout CAS;
4. consume the exact frozen plan through the authoritative fenced owner;
5. append and acknowledge `HoldoutConsumed` before the provider releases
   observations;
6. compute the bound estimates and append `ComparisonSealed`;
7. build a canonical typed archive from the actual evaluation receipt,
   qualification context, signed evidence and timing evidence, persist it
   create-only under the selected-host binding and append
   `QualificationArtifactsPersisted`;
8. inside `learning.eval`, verify current trust, objective, scope, authority
   epoch, signature lifetime, revocation and required actor/key/credential/
   controller separation; V3 additionally verifies observer and time evidence;
9. append `QualificationDecided` and then `PublicationPending` before invoking
   the evidence writer;
10. append `Published` only after the exact durable publication record is
    observed.

Recovery accepts typed archived inputs, not a caller-created
`SignedEvaluationDecisionV1`. The module rebuilds the exact bundle and re-runs
current V2/V3 verification. A cached, expired, revoked, wrong-scope or
context-substituted decision cannot advance publication.

`admit_signed_eligibility_v2` remains narrower than product qualification: it does
not consume a holdout, publish product evidence or confer selection/activation
rights.

The Agentd measured-outcome consumer must bind the sealed qualification to current
owner state and a signed exact-use payload over run, objective, snapshot,
predecessor context, candidate set, selected candidate, evaluation, execution
and publication identity. Computing a fresh digest for arbitrary request fields
is not sufficient.

## Final-holdout ownership

### Single-host compatibility

`DurableFinalHoldoutJournalV1` is valid only when the host supplies an authorized
regular file, an exclusive namespace, independently retained current anchor and
durable containing-directory semantics. A local file lock is not a distributed
lock.

### Contended deployment

A contended deployment must implement `FinalHoldoutCasStoreV1` with linearizable
compare-and-swap semantics. The authoritative record binds scope, owner identity,
positive monotonic fence generation, lease digest, complete replayable history
and state digest. A newer generation takes ownership only through CAS and stale
writers fail on their next transition.

An accepted-or-unknown write returns `Indeterminate`, poisons the live owner and
requires reload and reconciliation. Missing evidence is never interpreted as
permission to consume the holdout again.

`LockedFileFinalHoldoutCasStoreV1` provides a concrete single-filesystem backend
with an OS lock, checksummed append, fsync and an independently retained minimum
anchor. Cross-host deployment additionally requires external evidence that the
actual shared storage provides linearizable lock/CAS/fsync and directory
semantics.

### Verified compaction

`LockedFileFinalHoldoutCasStoreV1::compact_into` writes a new target and replays
retained state through normal CAS. It returns only when final record and anchor
equal the source. The source is never truncated by compaction and remains the
forensic predecessor until the host durably installs the successor and receipt.
Compaction cannot erase prior final-holdout use.

## Attempt lifecycle, capacity and checkpoints

The successful lifecycle is:

```text
IntentPersisted
  -> HoldoutConsumed
  -> ComparisonSealed
  -> QualificationArtifactsPersisted
  -> QualificationDecided
  -> PublicationPending
  -> Published
```

Known pre-consumption rejection may terminate as `RejectedBeforeHoldout`; known
post-consumption evaluation failure may terminate as `Failed`. Exact duplicate
transitions are idempotent. Skipped phases, changed plan/holdout/archive/request,
conflicting terminal states, truncated frames or a concurrent writer fail closed.

### Capacity reservation

Before a new intent is admitted, `AttemptCapacity::project` reserves the
worst-case remaining success phases in both bytes and event count. New work is
rejected when the reservation would cross journal limits. Existing admitted work
retains its completion budget and later admissions cannot consume it.

The ordered unresolved-attempt index is rebuildable from canonical history and
updated with the addressed transition. `pending(after, limit)` is bounded to
1..1024 and traverses unresolved identities rather than all completed history.
The index is never a source of truth.

### Independently anchored checkpoint and tail replay

`LockedFileProductEvaluationAttemptJournalV1::checkpoint_into` writes a canonical
reducer snapshot to a new regular file and binds the snapshot digest, journal
byte frontier, event count and rolling journal state into a checkpoint record.
The checkpoint record digest is retained under a domain-separated binding in an
independent anchor authority.

`recover_with_checkpoint` requires the normal journal anchor, the derived
checkpoint anchor, the checkpoint file and the original append-only journal. It
restores reducer state and replays only complete later frames. It rejects
checkpoint substitution, a checkpoint newer than the normal anchor, stale
journal restore, conflicting tail or truncation.

Checkpointing never truncates or replaces the source journal and never lowers the
normal anti-rollback anchor. A same-process fixture or trait implementation is
not proof of independently administered storage.

## Publication and reconciliation

A production `ProductQualificationPublicationStoreV1` must provide exactly-once
semantic publication keyed by execution digest:

1. load before write;
2. accept an existing record only when all request, decision, trust and
   authentication digests match;
3. reject semantic conflict without overwrite;
4. after `Indeterminate`, retain the pending request and load again;
5. report success only after the exact committed record is observed.

`PublicationPending` is a read-reconciliation state. Absence after an unknown or
submitted write is not permission to call the writer again. A recovered
`QualificationDecided` may perform the first write only after loading the exact
typed archive and completing current internal verification.

## Canonical product and consumer chain

The recorded runner freezes estimator mapping, consumes the final holdout,
records consumption, and only then permits observations to enter estimation.
Candidate and baseline intervals are derived from sealed estimator receipts over
the same authenticated cohort; callers cannot replace final `MetricGateV1`
values after observing the holdout.

All cross-crate recorded qualification entrypoints persist and journal-bind the
canonical typed archive before decision. The lower unarchived method remains
crate-internal and cannot be used to skip `QualificationArtifactsPersisted`.
Single- and multi-outcome paths share the typed archive, publication lifecycle,
selected-host store and recovery controller. The internal single-stream carrier
cannot be extracted to masquerade as multiple independently measured outcomes.

Repository consumers recheck current trust and exact use binding. Every result
remains `DENY_ALL`; eligibility is not selection, promotion, activation, effect
or release authority.

## Qualification evidence

Final source qualification requires one immutable candidate and its ordered-
parent synthetic merge to retain passing artifacts for:

- source identity and clean-tree checks;
- default and compatibility API tests, including rejection of the unarchived
  recorded qualification helper from another crate;
- all-target compilation;
- owner and consumer tests;
- typed archive and two-process cold recovery;
- process-kill fault cuts and publication reconciliation;
- lifecycle reservation, unresolved backlog, checkpoint/tail recovery and
  sustained profile;
- temporal cross-fit and sequential-confidence tests;
- strict Clippy, rustfmt and measured line coverage at or above the declared
  threshold.

Queued, pending, skipped, cancelled or infrastructure-invalid jobs are not
passing evidence.

## Target-host and external gates

Repository source and CI cannot self-issue:

- authenticated target-host identity or independent anchor administration;
- real provider/publication topology and persistent supervisor invocation;
- network-filesystem linearizability or deployment durability;
- real future-calendar outcomes and independent measurement provenance;
- retention, change-point, power, subgroup/privacy, unlearning and backup
  non-resurrection evidence;
- independent semantic/operator acceptance;
- selection, canary, promotion, activation or release authority.

`productionImplementation`, `targetHostQualified`, `independentAcceptance`,
activation and release remain false until their separate evidence and authority
gates pass.
