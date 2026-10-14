# Common-Head uncertainty without resampling a model at every event

Continuation of #1550 at `ad65f404a79934f089c8b3dbec1376ac4a0276ec`.
The existing entrypoint gains `--tracking-control-profile shared_head_mixture_v2`.
All old profiles, model/CPU/source thresholds, exact controls and native owners
remain. This is a Bayesian finite-belief research extension, not a new reviewer,
production policy, dynamic-preference model or general continuous FBSDE.

## Which probability problem is being solved

For members m with prior w_m and conditional event distributions q_mi, use

    p(o_1,...,o_T) = sum_m w_m * product_i q_mi(o_i).

The SAME unobserved member is shared by the whole story. The cheaper ablation
pools each event first and uses product_i sum_m w_m*q_mi(o_i). It has the same
initial one-event marginals, but a different joint law. A verification history h
updates the member weights by w_m(h) proportional to w_m product_(i,j in h) q_mi(j).
All unverified event laws must then use those updated weights. Histories are
recomputed from the original prior, not multiplied repeatedly into mutable state.
Duplicate observations and jointly impossible histories reject. Positive separate
marginals do not imply positive joint support. Log-space weights avoid product
underflow; this is ordinary floating point, not interval-certified arithmetic.

`SharedHeadBelief` implements this law for up to four members, sixteen events and
seven actors. The existing `plan` calls a conditional-outcome port instead of
reading a fixed event distribution. V1 implements the same port by its original
independent law. The two-check horizon, 20,000-node and 100ms process-CPU limits
remain. A rejected solve retains costs but no returned action. There is no
independent worst-case model choice at each node and no hidden future information.

Within a member, event outcomes are STILL conditionally independent. Deterministic
members express exact repeated-error dependence, but probabilistic members do not
in general tie repeated identical inputs perfectly. Three bootstrap Heads are not
three independent evidence sources or a calibrated sample of all plausible models.
Shared encoder bias, out-of-support hypotheses and posterior calibration remain
open. This implementation corrects declared probability semantics, not reality.

## Actual learning and matched controls

Keep the existing frozen Encoder and trained base Head. Fit two more small Heads
with fixed seeds on whole-event bootstrap samples from the same 720 simulator
actor labels, preserving 160 AdamW steps and the original learning rate. All three
reuse the SAME feature cache; no pretrained model is copied. The lexical profile
has 3 x 2,073 = 6,219 Head parameters. Additional fitting and all three forward
computations are charged, not hidden in the original model's timing.

Each member's temperature is selected on the separate 360-event simulator set.
Member weights remain the preregistered uniform prior. BBH inputs and targets are
opened only after fitting and calibration. All nine arms remain matched: single
Head with zero/two checks, pooled ensemble with zero/two checks, common-member
ensemble with zero/one/two checks, verify-all, and the cheaper exact reverse
algorithm. Verification obtains an original source operation AFTER the action.
The surrounding parser already reads the full constrained story; modelled check
fees are not physical parsing savings or CPU prices. All outputs are sealed before
final label scoring. This remains a task-specific grammar, not a general BBH score.

## Exact controls and independent recomputation

Two identical unknown swaps drawn ONCE from a common hidden member cancel with
probability one. Independent per-event pooling instead gives holder probabilities
(1/2,1/4,1/4) and pays for two checks at cost .1. With three repetitions, one
check resolves the common model and gives value .9; the independent approximation
still abstains with a two-check horizon. A 54-case grid varies prior, repetition,
price and horizon and matches complete-world enumeration. Random soft-member
controls, single-member reduction, impossible histories, log-underflow and bounded
failure are separate tests. These are mechanism facts, not learned-language gains.

The saved-file audit imports neither planner nor neural model. It independently
propagates forward holder matrices, recomputes joint posterior weights, conditional
choices, source revelations, temperatures, probability laws, original targets,
decoded answers, feature slots and physical sums. Mutation tests reject changed
member identities, fake posterior weights, altered text and unpaid work. Hashes
establish consistency, not independent execution, source independence or authority.

## Observed local outcome and failure

The first complete generated run answered all 192 stories correctly in every arm.
The mixture needed zero checks; the exact algorithm was still cheaper. This solved
grammar offers no added efficacy opportunity. It does not justify a new ensemble
for every Cell, nor a claim that correlated modelling always improves accuracy.

The first original-BBH attempt failed on source `seven:223` (task 724). The planner
retained a 121,309,590 ns CPU rejection with one visited node. Each arm has only
723 completed outputs; no complete benchmark result is reported. All 3,928 actual
proposal rows and the failure are retained. The observed timing alone establishes
neither garbage collection nor threading as its cause. No budget was raised or
run repeated until green. Final failure metadata also names the active policy.

The physical workflow retains all eight earlier entries and adds a separate
mixture entry for each backend. New-source mmBERT, full-repository/native tests,
independent future performance and risk qualification must run independently.
Riccati-Newton remains a numerical solver for appropriate continuous subproblems,
not a substitute for these probability assumptions or semantic verification.
