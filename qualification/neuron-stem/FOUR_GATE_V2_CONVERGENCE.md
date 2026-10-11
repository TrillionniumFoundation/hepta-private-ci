# Four-gate V2 convergence and physical-model execution

This extends PR #1526's existing `four_gate_review.py`, not a third reviewer.
The historical import `88d248277e853b96613f6b442386c25921ad2372` remains unchanged.
Its old review CLI is replayed only in an isolated historical checkout. Its raw
exploratory traces lack some current identity/chronology/cost fields and must not
be converted to an accepted observation by inventing those fields.

## Profile and source compatibility

`hepta.four-gate.plan.v1` retains its historical interpretation. Current campaigns
use `hepta.four-gate.plan.v2`. Both pass through the same existing CLI and original
SHA-pinned evidence bundle reader. `current_acceptance_profile_passed` is true only
when all V2 diagnostics pass; a V1 diagnostic PASS does not satisfy the new profile.
No profile grants production promotion, NDU selection or independent authenticity.
Observed evidence still requires at least 200 source clusters and two genuine
chronological windows. Synthetic tests cannot establish those empirical premises.

The existing seven lifecycle phases and original prequential Head lineage, frozen
control, retention and prediction checks remain. V2 retains the old OOD descriptive
report but no longer mistakes all shifted-input acceptance for answer error.
The current/head and prospective-merge suites run independently. Historical 62
protocol tests and 13 CPU tests run against their original immutable source in a
separate checkout; they do not certify that the new implementation is byte-identical.

## P1: real pretrained capture, and the limits of that observation

`four_gate_pretrained.py` invokes the existing `four_gate_capture.capture_cpu`
interface with physically loaded `jhu-clsp/mmBERT-small` at immutable revision
`abc32620dd4f6ab06f5fbe905dc25f310618e09f`. Downloaded bytes are checked against exact
revision LFS SHA-256 or Git blob identity before deserialization. Native ModernBERT
loads locally with remote code disabled and restricted PyTorch `weights_only`.
MLM output tensors may be unused; missing or mismatched Encoder weights fail.

The dedicated read-only CPU workflow executes two arms at three repeat ratios in
fresh processes with 64 distinct Heads. Inputs are unchanged public repository
excerpts. Heads are random and untrained; no label or real current-model no-change
is supplied. The physical smoke is NOT the complete 36-setting, three-arm scientific
gate, native Worker integration, a task-quality comparison or evidence of learning.
Requested larger workloads fail when there are insufficient distinct real excerpts;
appending fake unique IDs is not permitted. Genuine supervised/native data must be
supplied through the original experiment interfaces before scientific acceptance.

The first actual successful run is `38124642631`, exact source
`3954be218e67184b1920ac87144f78bda787cb8f`, artifact `11696890951` with ZIP SHA-256
`4e4a15ec25bb252b81c4799ca2998b0e5ce77fecfb99b60fc6dff5c3e21b9b97`.
It contains 384 successful Head executions across six runs. Joint batches encoded
64 rows per workload; reuse encoded 64, 32 and 6 at 0%, 50% and 90% requested repeats.
These are original-source observations, not automatic evidence for later commits.

Two measurement fixes require a new exact-head run: all queued requests now use
the capture's original arrival time (rather than starting the clock at each batch),
and joint inputs put question/options BEFORE a possibly truncated state. The earlier
64-token capture could truncate the trailing question; preserve its original output
but do not use it to assert question-conditioned equivalence. Pipeline identities
include this changed input profile. CPU/GPU/latency are distinct quantities. RSS is
Linux whole-process high-watermark including load/warmup, not a resettable serving
peak. Setup, download and warmup remain separately observed costs.

## P2: label-aware selective prediction sidecar

V2 `learning` references add `selective`, an original-byte-pinned JSON sidecar:
`schema=hepta.four-gate.selective.v1`, `trial_sha256`, fixed `objective_sha256`,
`calibration_sealed_at`, `detectors`, `calibration` and `evaluation` arrays.
The sidecar augments, never replaces, the original five learning evidence files.

`detectors` contains `confidence`, `feature_support`, `learned_rejector`, each with
artifact and common approved training-data SHA-256 and `fit_completed_at`.
Every prediction binds `detector_bundle_sha256=digest(detectors)`, probabilities,
model revision, actual Head/weight digest, generation, producer, time and the three
acceptance scores. Confidence is checked against actual maximum probability.
Other scores must come from their real fitted producer; this reviewer does not
train a support model or rejector, nor authenticate their claims.

Rows bind case/scope/Cell/source-cluster/input identities, event time, kind,
answerability and label. Evaluation binds independently observed outcome receipt,
observer and time. Strata are `in_domain`, `benign_shift`, `difficult_in_domain`,
`unknown_task`, `changed_rule`, `missing_evidence`. Unknown or insufficient evidence
has no invented class label. Correct benign-shift acceptance is not a failure.

Historical calibration predictions must use the SAME immutable final trained Head
as the later selective evaluation; frozen and no-change identities are also checked.
New Heads without compatible calibration fail. Thresholds use only historical
calibration. Source/input overlap, detector substitution and later threshold tuning
are rejected. The plan freezes `calibration_reject_fraction`,
`max_accepted_error`, `min_answerable_coverage`, `max_unknown_acceptance`,
`max_benign_rejection`, and `selected_detector`. Report all three detectors, but do
not select a winning detector after reading held-out labels. Reject-all has undefined
accepted-answer error and cannot pass a positive coverage floor. Source-cluster
bootstrap diagnostics include per-denominator support and multiplicity adjustment;
cluster IDs and bootstrap intervals are not independent truth certificates.

## P3: stronger fixed-depth and deterministic controls

V2 reasoning adds `fixed_12`, `best_fixed`, `nonrecursive`, `exact_algorithm` to the
original three arms. Fixed-depth validation tests all 1/2/4/8/12/16 depths on paired
historical cases. Gate config binds `validation_sha256`, `validation_depths`,
`selection_cost_weights`; evidence includes original `fixed_depth_validation`
(`hepta.fixed-depth.validation.v1`, `job_id`, `rows`). Each row binds case/source/input,
depth, actual cost, external fixed-objective score, producer/observer/outcome receipt
and historical observation time. Selection is recomputed with equal source-cluster
weighting and a shallower tie-break, not trusted as a supplied winner. The existing
training/evaluation, information, resource and novelty checks remain unchanged.

The validation grid's measured additive costs must be covered by `best_fixed`'s
original search-phase job; validation is not free tuning information.

`exact_algorithm_applicable=true` registers a bounded deterministic comparator.
A false value requires a preregistered `exact_algorithm_assessment_sha256` and
`exact_algorithm_inapplicability_reason`; that assertion is not independently
validated by the script and cannot excuse omitting an applicable cheap method. The helper `capture_exact_reachability` executes actual BFS on the
supplied bounded graph and records time and a zero-learned-depth guard trace. No
path on an incomplete edge inventory returns abstention, not a negative label.
The prediction is not its own independently observed outcome. Other task types
need an applicable comparator/profile, not a fake BFS receipt.

Every V2 episode has an explicit stop reason. Actual fixed-12 and best-fixed depths
are checked against the trace, and depth histograms flag constant-depth controllers.
More nodes/parallel branches or repeated transport do not manufacture learned depth.
These changes are controls and a deterministic algorithm, not a newly trained
System 2 or a proof of general reasoning. Real task episodes are still needed.

## P4: per-generation lifecycle cost and cheap controllers

V2 NDU additionally compares `fixed_12`, `best_fixed`, `cost_aware_exit`,
`stopping_router`, `generic_nested_risk` against deterministic and stochastic NDU.
The same original validation envelope chooses best fixed depth. Generic mathematically
equivalent recursion is a control, not an exclusive NDU advantage claim.

Each arm supplies `lifecycle_generations`: entries with exact fields `binding`,
`case_ids`, `lifecycle`. Binding contains `model_sha256`, nullable `critic_sha256`,
`objective_sha256`, `scope`, `generation`; each episode binds its canonical digest
in `cache_binding_sha256`. The model must match the actual selected Stem metadata.
Case IDs partition actual observations. The seven phase costs sum to the arm's
existing summary, inference reconciles with episode charges, and physical job IDs
cannot be reused across generations/arms. Calibration, selection and refresh belong
to their actual training/search/evaluation jobs, not an eighth uncharged phase.
No `planned_uses` or hypothetical future amortization is admitted. Cache/critic/model
revision changes cannot inherit an old generation's amortization identity.

This preserves the existing fixed external score-minus-lifecycle-cost review
profile. It is NOT a general FBSDE, preference diffusion or Z-gradient implementation.
Both lifecycle savings and incremental stochastic benefit remain empirical questions.

## P5 and scope still requiring independent execution

No new runtime authority owner, selected model, checkpoint, grant, CAS record,
Supervisor/CNS cutover or production route is written by these scripts. Physical
pretrained CPU execution does not establish native Worker dispatch, current no-change
quality, learned real Heads, a complete 4096-Cell matrix, signed final-use, unclean
recovery, canary, future-calendar outcomes or independent selection. Those remain
with the existing inference, Neuron, artifact, ledger, evaluator and selector owners.
The next scientific run must provide those actual inputs rather than setting flags.

## Additional real public-data replay, not a replacement for Hepta outcomes

`four_gate_public_replay.py` reuses the pinned real mmBERT loader and existing
`make_head`, `prediction_precommit`, scoring helpers. Its separate producer workflow
uses the original CLINC150 human-labelled data at immutable Git revision
`828f8093932c8fe6ca7936c3d2e52903b1c523de`, with exact source-file Git blob checks.
Attribution and CC BY 3.0 publisher license are retained. Four supplied domains
(home, utility, work, meta), each 15 intents, define four Cell tasks. The domain is
GIVEN for the per-Cell learning statistic. A separate group evaluation receives
all four Cell predictions and learned domain-support scores, never the true domain.
It reports 60-intent routing and genuine unknown-input coverage/risk separately.
Four parallel Heads still have sequential learned depth one, not System 2 depth four.

Each Cell starts from eight labelled training utterances per class, with the same
trained initialization copied to its frozen control. The publisher test slice is
replayed in a source-bound seeded order. Candidate/frozen predictions are file-synced
before each publisher label is used for two Head-update steps. Unchanged validation
subsets provide calibration and old-task retention. Real publisher out-of-scope
examples train/test a small rejector; confidence and feature-support controls are
also measured. Actual Head/detector tensors, input/model identities and original
prediction/update/output records are retained, not just a success boolean.

All selected rows are preserved. Cross-partition duplicate inputs are disclosed;
no filtered result is marketed as a clean independent sample. The public data
were already available historically and model pretraining contamination is not
assessed. Recorded timestamps are ACTUAL REPLAY CLOCKS, not original collection or
genuine future windows. Four domains and hundreds of utterances do not establish
200 independent source clusters. There is no actual current-model no-change arm.
This producer cannot pass the existing three-way/future/independent-owner gates,
even if candidate accuracy increases. It advances real-model/head execution only.
