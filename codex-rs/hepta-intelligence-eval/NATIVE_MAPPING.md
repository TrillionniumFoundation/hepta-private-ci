# `learning.eval` native implementation mapping

This file maps point, sequential, temporal, signed and product evaluation design
to concrete Rust symbols. Estimation, evidence eligibility, selection, activation
and release remain separate authorities. The normative surface and ownership
rules are in [`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md); generated source
truth and caller inventory are in
[`CURRENT_STATUS.json`](../../docs/modules/learning.eval/CURRENT_STATUS.json).
Recovery semantics and migration limits are in
[`RECOVERY_CONTRACT.md`](RECOVERY_CONTRACT.md). Source references below do not
assert execution success for the current candidate.

## Estimator primitives

| Evaluation operation | Native symbol | Source | Bound |
|---|---|---|---:|
| point IPS/SNIPS/DR and exact ESS | `estimate_ope` | `src/ope.rs` | `1,000,000` rows |
| conservative cluster intervals | `estimate_cluster_intervals` | `src/ope_confidence.rs` | point-estimator bound |
| finite-horizon history-conditioned PDIS/DR | `estimate_sequential` | `src/sequential.rs` | `4,096` trajectories / `65,536` steps / horizon `128` |
| one label-isolated temporal fold | `fit_temporal_fold` | `src/temporal_fold.rs` | `100,000` training or target rows |
| composed temporal holdout | `evaluate_temporal_holdout` | `src/temporal_evaluation.rs` | `16,384` held-out rows |
| complete measured-outcome batch | `evaluate_outcome_comparison` | `src/outcome_runner.rs` | `32` channels / `100,000` aggregate input rows |

The stage ceilings are intentionally different. A point-estimator capacity is not
the capacity of the composed temporal pipeline. These functions validate bounded
deterministic arithmetic, support, outcome watermarks, weight limits, exact ESS,
lineage separation and canonical digests. They do not authenticate a caller,
prove causal exchangeability, select a candidate or establish future-calendar
efficacy. Finite-horizon sequential point estimation is not a trajectory confidence
interval or an anytime-valid confidence sequence. The cluster confidence engine
retains its fixed-analysis assumptions and multiplicity requirements.

## Public and internal operation map

| Design operation | Native symbol | Source | Source scope |
|---|---|---|---|
| freeze complete V2 cross-fold, metric-role and product-source plan | `freeze_cross_fold_plan_v2` / `freeze_product_evaluation_plan_v1` | `src/metric_roles.rs`, `src/product_runner.rs` | public plan freeze |
| single-host cooperative holdout journal | `DurableFinalHoldoutJournalV1` | `src/durable_holdout.rs` | compatibility owner |
| contended holdout owner | `FencedFinalHoldoutOwnerV1` / `FinalHoldoutCasStoreV1` | `src/fenced_holdout.rs` | production ownership contract |
| concrete locked-file CAS, anti-rollback recovery and copy-compaction | `LockedFileFinalHoldoutCasStoreV1::{create,recover,compact_into}` | `src/fenced_holdout_file.rs` | cross-process backend; topology qualification external |
| capacity state and compaction evidence | `LockedFileCasCapacityV1` / `LockedFileCasCompactionReceiptV1` | `src/fenced_holdout_file.rs` | public diagnostics and integrity-bound receipt |
| durable evaluation-attempt file lifecycle | `LockedFileProductEvaluationAttemptJournalV1` | `src/attempt_journal_file.rs` | locked-file persistence; not sufficient alone for default product ingress |
| independent attempt anchor | `AnchoredProductEvaluationAttemptJournalV1` | `src/attempt_journal_anchor.rs` | default sealed durable capability |
| attempt-recorded product evaluation | `RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison` | `src/recorded_runner.rs` | default product evaluation ingress |
| product signed qualification and publication | `RecordedProductEvaluationRunnerV1::qualify_and_persist` | `src/recorded_runner.rs`, `src/product_runner.rs` | signed qualification ingress |
| idempotent publication and accepted-unknown reconciliation | `ReconciledProductQualificationSinkV1` / `ProductQualificationPublicationStoreV1` | `src/reconciled_sink.rs` | publication-store contract and adapter |
| durable publication phases | `RecordedPublicationSinkV1` | `src/recorded_publication.rs` | crate-internal decided/pending/published sequencing |
| bounded recovery sweep | `RecordedProductEvaluationRunnerV1::reconcile_pending_page` | `src/attempt_recovery.rs` | advances cursor past unresolved work; no external-owner writes |
| reconcile existing consumption/publication | `reconcile_product_attempt_holdout_v1` / `reconcile_product_attempt_publication_v1` | `src/attempt_recovery.rs` | validates full attempt history and exact owner records |
| verified prewrite publication resume | `resume_decided_qualification` / `resume_decided_outcome_qualification` | `src/attempt_publication_resume.rs` | rechecks sealed result and current V2/V3 signatures |
| raw prewrite publication helper | `resume_decided_publication` | `src/attempt_publication_resume.rs` | crate-private; not an external signed-decision ingress |
| frozen measured outcome contracts | `freeze_product_outcome_plan_v1` / `ProductOutcomeChannelContractV1` | `src/outcome_channels.rs` | bounded typed channels and preregistered measurement semantics |
| canonical measured input binding | `product_outcome_inputs_digest_v1` | `src/outcome_payload.rs` | full payload and lineage commitment |
| one-consumption multi-outcome estimation | `RecordedProductEvaluationRunnerV1::evaluate_outcome_comparison` | `src/outcome_runner.rs` | private path-attributed submodule of recorded runner |
| signed measured-outcome qualification | `RecordedProductEvaluationRunnerV1::qualify_outcomes_and_persist` | `src/outcome_runner.rs` | full outcome execution, not a placeholder carrier |
| consumer-bound signed eligibility | `admit_signed_eligibility_v2` | `src/signed_admission.rs` | public authority-free non-product admission |
| signed V2 decision primitive | `decide_with_signed_evidence_v2` | `src/signed_evaluation.rs` | crate-internal only |
| signed observed-time V3 decision primitive | `decide_with_signed_longitudinal_evidence_v3` | `src/longitudinal_time.rs` | crate-internal only |
| trusted direct compatibility | `trusted_inprocess::decide_independently{,_v2}` | `src/lib.rs` | feature-gated; never production ingress |
| legacy threshold comparator | `trusted_inprocess::evaluate_legacy_inprocess_v1` | `src/lib.rs` | deprecated trusted-only compatibility |
| storage recovery/capacity profile | `learning_eval_storage_profile` | `src/bin/learning_eval_storage_profile.rs` | qualification executable; no authority |

The raw `ProductEvaluationRunnerV1` is crate-private in default builds. Only the
explicit `trusted-inprocess-eval` feature makes it public. Default recorded
operations and reconciliation require `DurableProductEvaluationAttemptJournalV1`,
whose production implementation is the independently anchored wrapper. Test or
compatibility builds deliberately admit fixture journals; production builds must
exclude that feature, including through transitive feature unification.
A trait implementation still cannot prove independent physical storage.

## Frozen plan and estimator binding

`freeze_cross_fold_plan_v2` preserves complete V1 lineage and holdout invariants
while binding preregistered metric roles and margins. Two to thirty-two folds are
canonicalized and checked for training/holdout leakage. The final holdout never
enters training and is covered exactly once. `freeze_product_evaluation_plan_v1`
adds candidate and baseline temporal plan digests plus the registered IPS, SNIPS
or doubly-robust metric source to the estimand digest.

Candidate and baseline estimates are computed over the same authenticated cohort.
Private receipt seals bind the temporal and cluster results. Final `MetricGateV1`
values are derived from those receipts; callers cannot replace intervals after
seeing the holdout. Cohort authentication is supplied and qualified at the host,
not inferred from a nonzero digest.

`ProductMetricSourceContractV1` selects estimators of one outcome stream; it does
not create separate measured results by renaming metrics. The additive
`ProductOutcomeChannelContractV1` binds metric and channel identity, schema, unit,
normalization, subgroup, window and start/end times, provenance, complete input
commitment and candidate/baseline temporal plans. The frozen outcome plan enforces
complete metric coverage, unique channel/input commitments and multiplicity.

`FinalOutcomeHoldoutProviderV1` releases one complete batch after one final-holdout
consumption. Native temporal estimation is performed separately per channel.
Candidate and baseline use paired logged observations; all channels bind the
same nonempty snapshot set. Substituted, missing, duplicate or relabelled frames
cannot produce a partial sealed comparison. The multi-outcome digest is recorded
as `ComparisonSealed`; its internal single-stream carrier remains private.
The source caps and digest checks do not constitute independent measurement,
normalization or outcome-provenance authentication.

## Holdout ownership, recovery and compaction

`DurableFinalHoldoutJournalV1` is suitable only when a host guarantees one
exclusive local namespace. Contended composition uses
`FencedFinalHoldoutOwnerV1`, whose record binds scope, owner, monotonic fence,
lease digest, complete replayable journal and state digest. A newer generation
can take ownership only through CAS; stale writers fail on their next transition.
An accepted-or-unknown write returns `Indeterminate`, poisons the handle and
requires reload and reconciliation.

`LockedFileFinalHoldoutCasStoreV1` holds an OS file lock, appends checksummed
frames, fsyncs committed transitions and requires an independently retained
minimum anchor on recovery. `compact_into` never truncates the source. It writes a
new target, emits the current fence, replays every retained plan through the
normal CAS path and proves that final state and anchor are identical before
returning. Cross-host use still requires external evidence that the chosen shared
filesystem provides linearizable lock and fsync semantics. Holdout compaction is
not automatically an attempt-journal rotation or long-running capacity result.

## Attempt lifecycle

The default recorded lifecycle is:

```text
IntentPersisted -> HoldoutConsumed -> ComparisonSealed
ComparisonSealed -> QualificationDecided -> PublicationPending -> Published
IntentPersisted -> RejectedBeforeHoldout
HoldoutConsumed -> Failed
```

The intent is durable before provider lookup or consumption. `HoldoutConsumed`
is acknowledged before released observations reach estimation. A complete
comparison and its execution digest are sealed before returning. Decided and
pending phases persist the canonical publication-request digest before the
external publication call. Comparison sealing is not publication completion.

Exact transition acknowledgements are idempotent. Changed plans or holdouts,
conflicting terminal transitions, truncated frames and concurrent second writers
fail closed. A consumed-but-failed attempt remains auditable and cannot be
interpreted as permission to reuse the final holdout. Existing attempts are
recovery cases, not evaluation retries.

Attempt replay is streaming; append updates only the addressed history rather
than cloning the global map. The independent anchor binds a global event count
and rolling digest and rejects old complete backups as well as truncated frames.
Uncertain file/anchor acknowledgements poison the wrapper. Recovery validates
and advances any legitimate complete post-anchor tail without deleting evidence.

Reconciliation validates the entire per-attempt history and its latest pointer,
not just individual checksums. Bounded cursor sweeps advance past unresolved
attempts. External owners are read only; the attempt journal is advanced when
matching authoritative records exist. A host must persist the sweep cursor and
coordinate recovery with live owners. No provider is accepted by the sweep API.

`QualificationDecided` can resume its first publication through the public
signature-reverified methods when the original sealed result and evidence are
recoverable. The reconstructed request must equal the durable preregistration.
Pending/Published attempts are rejected by that write path; an absent pending
publication is not permission to retry. Complete evidence-object persistence and
ambiguity-resolving submission recovery remain distinct repository obligations.

## Signed admission and product qualification

`decide_with_signed_evidence_v2` authenticates generator frozen-plan evidence and
evaluator exact-request bytes against host-owned trust. It verifies role, scope,
objective, epoch, lifetime, revocation and principal/key/credential/controller
separation before running the bound V2 statistical decision.
`decide_with_signed_longitudinal_evidence_v3` adds an independent observer and
observed-time contract. Both functions are crate-internal and compiler-negative
fixtures require that they cannot be imported from another crate.

`admit_signed_eligibility_v2` is the only public non-product facade over the V2
primitive. It requires a digest of the complete concrete consumer context and
returns a private-sealed, `DENY_ALL` receipt. Agentd binds run, objective,
snapshot, predecessor, candidate-set and selected-candidate context. Governed
plasticity binds proposal, candidate, artifact/evidence frontiers, dataset,
eligibility and generator context. Neither path consumes a final holdout or mints
a product qualification receipt.

Product qualification builds the bundle internally from the sealed product
execution, invokes V2 or V3 and publishes through
`ProductQualificationEvidenceSinkV1`. The canonical reconciled sink loads before
write, rejects semantic conflicts and reads back an indeterminate commit. It
never interprets a missing pending record as permission for a duplicate write.
Success is reported only after the exact committed record is observed.

Every decision remains one of:

```text
EligibleForIndependentSelection
Ineligible
InsufficientEvidence
```

Even the first state retains `DENY_ALL`. The repository product consumer
`codex-rs/hepta-intelligence/src/evaluated_shadow.rs::run_evaluated_shadow_v1`
accepts only a sealed `ProductQualificationReceiptV1`; it rechecks current trust,
dataset, candidate and evaluator bindings and does not rerun a low-level decision.
That existing caller does not establish a consumer of the additive
`ProductOutcomeQualificationReceiptV1` or a deployed selected-host runtime.

## Identity, causal and statistical obligations

A signature proves that an authorized key attested exact bytes. It does not prove
unbiased measurement, organizational independence, correct confidence coverage,
exchangeability, privacy or future learning gain. Causal identification remains
conditional on the frozen assumptions: consistency, positivity, propensity
validity, cluster/dependency validity and absent or bounded confounding. An
outcome model cannot repair zero support.

System-longitudinal source checks require independent snapshots, multiple future
windows, retention and unlearning receipts, but source fixtures and virtual time
are not real future-calendar evidence. The external target-host packet is defined
in `docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md`.

## Caller inventory

The generated source inventory recognizes these repository consumers:

| Consumer | Path | Surface |
|---|---|---|
| agentd evaluation session | `codex-rs/hepta-agentd/src/intelligence_evaluation.rs` | `admit_signed_eligibility_v2` with request binding |
| governed plasticity proposal | `codex-rs/hepta-intelligence/src/plasticity_product.rs` | `admit_signed_eligibility_v2` with proposal binding |
| evaluated shadow | `codex-rs/hepta-intelligence/src/evaluated_shadow.rs` | sealed `ProductQualificationReceiptV1` |

`scripts/hepta-learning-eval-status.py` checks complete Rust identifiers rather
than confusing the raw runner with the longer recorded-runner identifier. It
fails on external references to low-level V2/V3 symbols. This is a conservative
lexical inventory, not a compiler-derived call graph or runtime invocation proof.
The implementation map retains its named-operation scope explicitly.

## Qualification mapping

Core tests remain in:

- `src/ope_tests.rs`, `src/ope_confidence_tests.rs`, `src/sequential_tests.rs`;
- `src/temporal_fold_tests.rs`, `src/temporal_evaluation_tests.rs`;
- `src/closure_tests.rs`, `src/longitudinal_time_tests.rs`;
- `src/durable_holdout_tests.rs`, `src/fenced_holdout_tests.rs` and
  `src/fenced_holdout_file_tests.rs`;
- `src/product_runner_tests.rs` and `src/signed_qualification_e2e_tests.rs`;
- tests in `signed_admission.rs`, `reconciled_sink.rs`,
  `attempt_journal_tests.rs` and the compaction module.

Additional source regressions are in `src/outcome_tests.rs`,
`src/attempt_recovery_tests.rs`, `src/recorded_publication_tests.rs`,
`src/recorded_runner_process_tests.rs` and
`tests/attempt_anchor_acknowledgement.rs`. The process fixture actually terminates
an isolated child at seven boundaries, including decided-before-pending. It
checks retained anchors, no final-holdout re-release and no duplicate publication.
Its publication half uses fixture decisions to isolate persistence; public
signature-recovery and full signed outcome E2E coverage remain separate tasks.

`scripts/hepta-learning-eval-api-surface.sh` supplies compiler-positive and
compiler-negative API fixtures, including E0624 for the private resume helper.
`scripts/hepta-learning-eval-faults.sh` runs the established fault matrix.
`learning_eval_storage_profile` records attempt write/recovery and holdout
compaction measurements. The 1,024-attempt/512-fence source profile is not
near-capacity or sustained selected-host qualification.

Cross-crate composition remains exercised by
`hepta-shadow-qualification/src/lane_e_closure_tests.rs`. The focused
`Hepta learning.eval convergence` workflow requires `>=85%` measured line
coverage. The `Hepta learning.eval exact trees` workflow separately addresses the
exact head and ordered-parent synthetic merge, records command/log/output digests,
preserves failures and performs no source/status repair. The Lane E workflow is
an additional closure gate, not interchangeable evidence from another SHA.

The status generator explicitly writes canonical status and marked guide/native
projections only in authoring mode. Its `verify` mode checks the inventory,
implementation map, identifier/projection regressions and projection drift
without changing tracked files. Python projection tests are not Rust execution.

## Remaining external gates

No source or CI artifact self-issues:

1. selected-host authentication and durable namespace binding;
2. cross-host filesystem qualification when applicable;
3. real future-calendar outcomes and independent observation provenance;
4. retention, change-point, power, subgroup/privacy and unlearning evidence;
5. independent semantic/operator acceptance;
6. selection, canary, promotion, activation or release authorization.

These states remain false in `CURRENT_STATUS.json`. A structural target-host
packet check alone cannot authenticate its issuer, prove its measurements or
issue independent acceptance. Authentic external evidence and its separate
acceptance authority are required.

<!-- BEGIN GENERATED LEARNING.EVAL SOURCE STATUS -->
### Current candidate source inventory

Canonical inventory: `docs/modules/learning.eval/CURRENT_STATUS.json`.
Inventory SHA-256: `293088082dd4adf7ea208af37cd17a7e36a4f199416308262ac0cb65bd6165e7`.

This block is generated from lexical source facts, not test results.
Default ingress: recorded runner with independently anchored journal capability.
Raw runner: explicit `trusted-inprocess-eval` compatibility feature only.
Recovery: durable intent, full-history validation, bounded cursor reconciliation,
and signature-reverified decided-only publication resume.
Process-kill fixture cuts: `7`; their execution is separately qualified.
Outcome source: at most `32` preregistered channels and
`100000` batch rows, with separate measured estimates.
A deployed outcome-receipt consumer and authenticated measurement provenance
are not established by the source inventory.

Exact-head, ordered-parent merge, coverage and strict lint require immutable
execution artifacts. Real target-host, future-window and independent acceptance
evidence remain external. Production, activation and release claims remain false.
<!-- END GENERATED LEARNING.EVAL SOURCE STATUS -->
