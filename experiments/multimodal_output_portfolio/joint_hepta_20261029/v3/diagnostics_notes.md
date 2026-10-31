# Frozen-prefix generation diagnostics

This module extends the existing joint generator experiment. It does not change
v1/v2, their task definition, gamma=2 objective, or qualification thresholds.
Results are development evidence and are never an automatic promotion.

## Conditioning and interventions

`evaluate_prefix` encodes and executes the requested nonterminal prefix once.
The v3 runtime snapshot contains content, feedback, exact remaining budget,
prefix cost, model/input identities, and named actor/emission RNG states.
Every candidate branch receives a clone of the same snapshot. Independent
future tapes are drawn across repetitions; the complete tape is paired across
candidate actions within a repetition. This changes future simulation noise,
not conditioning content or its sunk cost. No prefix is regenerated with a
slightly different measured budget.

Primary interventions are immediate STOP, one shared update, one update of each
of the four modalities, and one verify. Continuation can be the sampled policy,
the greedy policy, or immediate STOP after the intervention. `verify_twice` is
an additional challenge and is excluded from the seven-action ranking. An
intervention forbidden by the actual policy/horizon is recorded as skipped;
the diagnostic does not bypass a repeated-verification guard.

The STOP reference is legal at the encoder state. With continuation `stop`, the
other arms answer the concrete question: does one more update improve actual
delivered utility enough to repay its costs? With continuation `dynamic`, they
include the subsequent choices of the learned policy. These are different
estimands and must be reported separately.

## Readback and separation of labels

The backend calls the unchanged media writer/reader to emit real PNG, PCM WAV,
timed GIF, and UTF-8 files. The observer callback receives independently read
decoded tensors. It writes `READBACK.npz` and `READBACK_SCORE.json` before
returning its score; that storage work is inside the charged observer interval.
The target is only closed over by this observer. Encoder, transitions, actor,
critic, verification, and future randomness never receive the callback or
target. This is a dataflow separation, not a process-security boundary.

Per-branch outputs, original numerical readbacks, observed utility, complete and
suffix costs, action traces, seeds, parameter identity, and payload hashes are
retained. `PREFIX_STATE.npz` and `PUBLIC_INPUT.npz` retain conditioning values.
The parent runner must retain the matching model checkpoint and profile. The
readback artifacts are evidence of execution, not proof of semantic adequacy.

## Risk, uncertainty, and calibration

All reported CEs use `-log(mean(exp(-2 R)))/2`. A candidate improvement is
`CE(candidate) - CE(STOP)`, never `CE(candidate - STOP)`. Complete returns include
the identical sunk prefix cost. Critic targets use suffix returns, so the sunk
cost is removed exactly once. Conditional diagnostics do not replace the
population objective by an average of conditional CEs.

Within one frozen prefix, paired bootstrapping estimates uncertainty over future
draws only. For cross-task comparisons, `paired_ce_difference(..., source_ids=)`
assigns each original source equal mass and resamples whole source clusters,
retaining all paired draws. These plug-in CEs and percentile intervals have
finite-sample error/bias. One independent unit supplies no interval. Repeated
draws are not new independent tasks.

Critic predictions are conditional exponential moments. The proper loss is
`exp(v) - exp(-2 R_suffix) * v`; fitting realized log returns would target a
different statistic. The planner approximation adds registered service tariffs
to its suffix critic. Unknown future physical cost remains prediction error;
the diagnostic does not quietly remove it from realized returns. A greedy
continuation evaluated with a critic trained on the sampled policy is explicitly
marked as a policy mismatch. STOP-after-intervention uses the delivery critic
at the pre-STOP state; its target already includes STOP and delivery costs, so
the predictor does not add the STOP tariff twice.

The reported action-ranking gap is relative to the *empirically* best action on
the same finite draws. It is neither an exact oracle regret nor permission to
feed future outcomes into the deployed controller. Multiple candidate actions
also create selection optimism; no significance or qualification gate is added.

## Verification information

The public verifier compares its draft against arrived input observations.
`verify_information` checks content, feedback, and an actor comparison with the
clock held fixed. Content can remain unchanged while feedback changes the
next decision. Repeating deterministic verification without an intervening
content change can return identical feedback; this does not establish that the
first verification is useless. The actual paired readback/cost experiments
measure its downstream value. Clock changes and additional expense alone are
not called new observations.

## Focused verification

Run from the repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.test_diagnostics
```

Tests expose the CE-of-differences error, pseudoreplication by source, the wrong
critic target, a deliberately wrong action ranking, unpaired randomness, and
nonfinite outcomes. An actual v3 generator test emits and rereads the four media
types, changes only observer targets, and verifies identical generation with
different scores and exact cost reconstruction.

## Critic fit and independent analysis cohort

Each row also retains the public state features at the actual pre-critic
boundary, after the forced intervention's measured cost has been incurred.
The matching target removes that incurred cost from the future suffix exactly
once. Immediate delivery uses the pre-STOP head; a dynamic continuation uses
the continuing-policy head. Targets remain observer-only, detached supervision.

`fit_validate_critics` fits only these two heads using the proper moment loss.
It rejects overlap of original source IDs or exact public-input hashes between
training and validation, requires one frozen behavior model/objective, keeps
actor and generator tensors unchanged, and retains the numerical fit data,
fixed protocol, before/after metrics, optimizer log and critic checkpoint.
Validation cannot choose the number of updates or select a checkpoint.
Calibration improvement alone does not establish better generated content or a
better deployed policy.

Before reading the calibration cohort results, the v3 execution is specified as:

- checkpoint: seed 17, width 32, dual joint dynamic arm;
- fit namespace: `joint-v3-calibration.fit.20261030`, sources 0 through 7;
- analysis namespace: `joint-v3-calibration.analysis.20261030`, sources 0 through 7;
- nonterminal prefixes: empty and one shared update;
- continuation cohorts: immediate STOP and sampled dynamic policy;
- four independent future draws per source/prefix/continuation, paired across
  seven primary actions and the additional repeated-verify challenge;
- total: 2,048 executed continuations if every intervention is legal;
- fit: 100 full-batch Adam updates, learning rate 0.001, gradient norm cap 5;
- 400 paired bootstrap replicates for conditional development diagnostics;
- source namespaces here are neither the previous held-out data nor a reserved
  confirmation cohort. Four draws provide limited conditional risk precision.

Any missing, illegal, or failed execution must remain in the raw report. These
cohorts diagnose and fit the value heads; they do not relax any existing gate.

Reproduce the frozen cohort with the actual checkpoint:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.diagnostics_study --checkpoint MODEL.pt --output diagnostic-study
```

`STUDY_PROTOCOL.json` is written before any cohort outcome is inspected. The
runner retains all 64 prefix/source/continuation group reports, performs
source-cluster comparisons against paired STOP, fits only the critics, and
writes `STUDY_SUMMARY.json` plus a separate calibrated candidate checkpoint.
