# `learning.eval` native implementation mapping

This file maps the current estimator, admission, product, persistence, recovery
and consumer design to concrete Rust symbols. The immutable executable-source
observation for the final candidate is recorded in
[`IMPLEMENTATION_MAP.json`](../../docs/modules/learning.eval/IMPLEMENTATION_MAP.json);
this document does not self-reference a mutable head. Source presence is not
execution, target-host qualification, independent acceptance, activation or
release. The normative contracts are
[`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md) and
[`RECOVERY_CONTRACT.md`](RECOVERY_CONTRACT.md); generated lexical truth is
[`CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).

## Estimator and statistical operations

| Operation | Native symbol | Source | Bound and claim boundary |
|---|---|---|---|
| point IPS/SNIPS/DR | `estimate_ope` | `src/ope.rs` | at most 1,000,000 rows; point evidence only |
| conservative single-decision cluster intervals | `estimate_cluster_intervals` | `src/ope_confidence.rs` | fixed-analysis cluster evidence |
| finite-horizon PDIS/DR | `estimate_sequential` | `src/sequential.rs` | 4,096 trajectories, 65,536 steps, horizon 128 |
| clustered finite-horizon intervals | `SequentialPlan::estimate_cluster_intervals_v1` | `src/sequential_confidence.rs` | fixed analysis, preregistered absolute trajectory-return envelope and minimum clusters; not anytime-valid |
| one isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | 100,000 training or target rows |
| actual preregistered temporal cross-fit | `CrossFoldPlanV1::execute_temporal_cross_fit_v1` | `src/temporal_cross_fit.rs` | executes every declared fold, exact lineage coverage, no held-out decision reuse, recomputed digest equality |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | 16,384 held-out rows |
| complete measured-outcome batch | `RecordedProductEvaluationRunnerV1::evaluate_outcome_comparison` | `src/outcome_runner.rs` | 32 channels / 100,000 aggregate batch rows |

The cross-fit executor does not authenticate caller-supplied provenance and does
not turn source fixtures into future-calendar efficacy. The sequential confidence
layer treats cluster labels as supplied evidence; it does not prove cluster
independence, exchangeability, adaptive-stopping validity or causal
identification.

## Default API and compatibility boundary

| Operation | Native symbol | Source | Scope |
|---|---|---|---|
| product plan freeze | `freeze_product_evaluation_plan_v1` | `src/product_runner.rs` | public production plan freeze |
| recorded temporal comparison | `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | `src/recorded_runner.rs` | default product evaluation ingress |
| archived single-outcome qualification | `RecordedProductEvaluationRunnerV1::qualify_and_persist_with_artifacts` | `src/qualification_artifacts.rs` | public product qualification ingress; canonical typed archive precedes decision |
| selected-host qualification | `RecordedProductEvaluationRunnerV1::{qualify_and_persist_on_selected_host,qualify_outcomes_and_persist_on_selected_host}` | `src/selected_host_facade.rs` | public concrete archive/publication composition |
| unarchived signed qualification helper | `RecordedProductEvaluationRunnerV1::qualify_and_persist` | `src/recorded_runner.rs` | crate-internal only; never cross-crate product ingress |
| consumer-bound admission | `admit_signed_eligibility_v2` | `src/signed_admission.rs` | public, sealed, `DENY_ALL`, one exact consumer use |
| signed V2 primitive | `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | crate-internal |
| signed V3 primitive | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | crate-internal |
| raw product runner | `ProductEvaluationRunnerV1` | `src/product_runner.rs` | crate-private by default; public only with `trusted-inprocess-eval` |
| trusted direct comparators | `trusted_inprocess::*` | `src/lib.rs` | compatibility/testing only |

Default recorded operations require
`DurableProductEvaluationAttemptJournalV1`. Production manifests must exclude
`trusted-inprocess-eval`, including transitive feature unification. Compiler
negative fixtures, not lexical comments, enforce that low-level decisions, the
raw runner, unverified publication resume and the unarchived recorded
qualification helper are unavailable to another crate.

## Attempt owner, capacity and checkpoint mapping

The canonical successful lifecycle is:

```text
IntentPersisted
  -> HoldoutConsumed
  -> ComparisonSealed
  -> QualificationArtifactsPersisted
  -> QualificationDecided
  -> PublicationPending
  -> Published
```

| Operation | Native symbol | Source | Semantics |
|---|---|---|---|
| append/replay owner | `LockedFileProductEvaluationAttemptJournalV1` | `src/attempt_journal_file.rs` | locked, checksummed, synced append; bounded full replay |
| lifecycle capacity reservation | `AttemptCapacity::project` | `src/attempt_capacity.rs` | reserves all remaining success phases before new intent admission |
| unresolved index | `AttemptCapacity::pending_page` | `src/attempt_capacity.rs` | bounded lexicographic lookup over unresolved identities, rebuilt from source history |
| independent journal anchor | `AnchoredProductEvaluationAttemptJournalV1` | `src/attempt_journal_anchor.rs` | append acknowledgement follows file sync and anchor CAS |
| checkpoint creation | `LockedFileProductEvaluationAttemptJournalV1::checkpoint_into` | `src/attempt_checkpoint.rs` | canonical reducer snapshot, new file, derived independent anchor namespace; no truncation |
| checkpoint tail recovery | `LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint` | `src/attempt_checkpoint.rs` | validates checkpoint identity/frontier and replays only later frames to the normal journal anchor |
| anchored wrapper recovery | `AnchoredProductEvaluationAttemptJournalV1::recover_with_checkpoint` | `src/attempt_journal_anchor.rs` | uses the normal authority plus a separately supplied checkpoint authority |
| bounded recovery page | `RecordedProductEvaluationRunnerV1::reconcile_pending_page` | `src/attempt_recovery.rs` | validates complete history and advances past unresolved work |

Checkpoint data is not trusted because it is checksummed. Its exact canonical
record digest must be retained by an independently administered authority under a
domain-separated binding. The original append-only journal and normal journal
anchor remain authoritative. Checkpoint substitution, a checkpoint newer than
the normal anchor, stale journal restore and conflicting tail fail closed.

The sustained source profile configures 4,096 attempts and 28,672 lifecycle
events. It creates a checkpoint 64 attempts before each 128-attempt restart so
each recovery exercises a nonempty tail. This is source test configuration, not a
target-host SLO or observed passing result.

## Typed qualification archive and selected-host recovery

| Operation | Native symbol | Source | Semantics |
|---|---|---|---|
| canonical archive encode/verify/persist | `Archive::persist` | `src/qualification_archive.rs` and codec/model/store children | archive is generated from actual typed receipt/context/evidence/timing inputs; create-only; journal-bound |
| archive recovery | `qualification_archive::recover` | `src/qualification_archive.rs` | reloads exact bytes, decodes canonical typed objects and performs current V2/V3 verification inside the module |
| single-outcome selected-host qualification | `RecordedProductEvaluationRunnerV1::qualify_and_persist_on_selected_host` | `src/selected_host_facade.rs` | shared typed archive and publication store |
| multi-outcome selected-host qualification | `RecordedProductEvaluationRunnerV1::qualify_outcomes_and_persist_on_selected_host` | `src/selected_host_facade.rs` | same archive/store semantics, full multi-channel execution digest |
| single-outcome cold recovery | `RecordedProductEvaluationRunnerV1::recover_selected_host_qualification` | `src/selected_host_facade.rs` | no decoder callback or caller-provided decision |
| multi-outcome cold recovery | `RecordedProductEvaluationRunnerV1::recover_selected_host_outcome_qualification` | `src/selected_host_facade.rs` | no decoder callback or weaker fallback |
| publication read reconciliation | `RecordedProductEvaluationRunnerV1::reconcile_selected_host_publication` | `src/selected_host_facade.rs` | validates existing exact durable record; never submits a new write |
| persistent bounded controller | `RecordedProductEvaluationRunnerV1::recover_selected_host_pending_page` | `src/selected_host_recovery_controller.rs` | persistent cursor, current host clock, bounded page/budget, archive re-verification, no provider/estimator rerun |

The archive replaces parallel caller-supplied Debug/opaque byte vectors. Recovery
accepts typed archived inputs and constructs the decision only after current
trust, signature, expiry, revocation, role, objective, scope and V3 timing checks.
`PublicationPending` remains a read-only reconciliation state: absence is not
permission to issue another write. No default cross-crate qualification method
can skip archive persistence and directly append `QualificationDecided`.

## Holdout and publication ownership

| Operation | Native symbol | Source | Semantics |
|---|---|---|---|
| contended final-holdout owner | `FencedFinalHoldoutOwnerV1` | `src/fenced_holdout.rs` | monotonic fence and authoritative CAS |
| concrete file CAS | `LockedFileFinalHoldoutCasStoreV1` | `src/fenced_holdout_file.rs` | one qualified filesystem, independent anti-rollback anchor required |
| copy compaction | `LockedFileFinalHoldoutCasStoreV1::compact_into` | `src/fenced_holdout_file.rs` | writes a new target and proves final state/anchor equality; never truncates source |
| canonical publication adapter | `ReconciledProductQualificationSinkV1::persist` | `src/reconciled_sink.rs` | load-before-write, semantic conflict rejection, read-after-indeterminate |
| write-ahead publication phases | `RecordedPublicationSinkV1` | `src/recorded_publication.rs` | exact request digest in decided/pending before writer call |

Cross-host deployment additionally requires evidence that the actual shared
filesystem or store has linearizable lock/CAS/fsync semantics. A trait
implementation and same-host fixture do not establish that fact.

## Consumers

| Consumer | Path | Required binding |
|---|---|---|
| Agentd ordinary evaluation session | `codex-rs/hepta-agentd/src/intelligence_evaluation.rs` | signed evidence plus exact run/objective/snapshot/predecessor/candidate-set/candidate use |
| governed plasticity | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | proposal, candidate, artifact/evidence frontiers, dataset and generator context |
| evaluated shadow | `codex-rs/hepta-intelligence/src/evaluated_shadow.rs` | sealed product qualification receipt plus current trust/dataset/candidate/evaluator |
| Agentd measured-outcome consumer | `codex-rs/hepta-agentd/src/intelligence_outcome_evaluation.rs` | current owner plus signed exact-use attestation over request, qualification, execution and publication identity |

Every consumer receives authority-free evidence. Eligibility is not selection,
promotion, activation, effect authority or release.

## Qualification mapping and current claim state

Primary source tests include estimator/unit tests, process-kill fault cuts,
`cold_recovery_e2e.rs`, selected-host single- and multi-outcome restart tests,
attempt capacity/checkpoint tests, holdout compaction and the sustained checkpoint
profile. Exact-tree workflows additionally run default and compatibility API
checks, all-target compilation, owner/consumer tests, strict Clippy, rustfmt,
coverage and ordered-parent synthetic-merge qualification.

As of this mapping update, those final-candidate workflows must still provide
passing commit-addressed artifacts. Queued, pending, cancelled, skipped or
infrastructure-invalid runs are not success. `productionImplementation`,
`targetHostQualified`, `independentAcceptance`, activation and release remain
false. Real host identity, anchor administration, provider/publication topology,
future-calendar outcomes, independent measurement provenance,
retention/privacy/unlearning/power evidence and release authority remain separate
external gates.

<!-- BEGIN GENERATED LEARNING.EVAL SOURCE STATUS -->
### Current candidate source inventory

Canonical inventory: `docs/modules/learning.eval/CURRENT_STATUS.json`.
Inventory SHA-256: `75e4ad3b446a79674d258401ef2da2cd0de9e5512ce4c8b2f555e6ae7624ecf9`.

This block is generated from lexical source facts, not test results.
Default ingress: recorded runner with independently anchored journal capability.
Raw runner: explicit `trusted-inprocess-eval` compatibility feature only.
Recovery: durable intent, independently anchored full-history validation, bounded
cursor reconciliation and complete typed qualification artifacts.
Selected-host single- and multi-outcome artifact recovery and publication resume
are present in source, with signatures reverified before final use.
Process-kill fixture cuts: `7`; their execution is separately qualified.
Outcome source: at most `32` preregistered channels and
`100000` batch rows, with separate measured estimates.
A request-bound Agentd multi-outcome receipt consumer is present in source;
deployed execution, authenticated target-host qualification and measurement
provenance are not established by this source inventory.
Sustained profile source: `4096` attempts,
`28672` lifecycle events and anchored
restart every `128` attempts; a passing
exact-source artifact is still required.

Exact-head, ordered-parent merge, coverage and strict lint require immutable
execution artifacts. Real target-host, future-window and independent acceptance
evidence remain external. Production, activation and release claims remain false.
<!-- END GENERATED LEARNING.EVAL SOURCE STATUS -->
