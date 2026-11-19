# Prospective operator development protocol — HOLD_NO_GO

Freeze these tasks, truth explanations, exposure exclusions and protocol before
any new model output. This is a development study using the already-trained
SmolLM2-135M base and eight original V2 adapters. No weights are trained, selected
or adopted. The original adverse B2 and exposed24 results remain unchanged.

## Cohorts and selection

Ninety-six new operator questions have four disjoint, label-balanced panels:
16 calibration, 16 old-domain development, 32 fictional context-world questions
in eight worlds, and 32 old-capability probes in 16 related-fact clusters.
Every declared source cluster belongs to one panel. Related questions are not
independent sampling units. The excluded registry contains the original20 public
fixture questions (matching its training archive SHA), B2_60, exposed OOD24 and
eight original C questions. Normalized exact exclusion is not exhaustive
semantic independence or pretraining-contamination certification.

Only the base's16 calibration questions select between two preregistered native
chat wrappers: original question plus Answer suffix, or an explicit request for
exactly YES/NO. Choose greater valid count, then greater correct count, then the
original wrapper on a tie. Freeze the winner before any old-development or main
question is generated. The primary parser remains leading standalone YES/NO;
invalid/empty outputs count incorrect. No fitted decision threshold, label
inversion or post-result task replacement is permitted.

Run the base on16 old-development questions, then the same64 main questions
(32 context +32 retention) once for each of the nine frozen conditions. This
totals624 actual generations:32 calibration +16 development +576 main. Every
attempt has an eight-token, greedy CPU allowance. Exact runtime and all model,
adapter, source and input hashes are checked; source publication precedes the
first generation. Full sequences, text, flags, chronology and partial failures
are retained with one run identity. Base calibration/development costs are
separate from each common64-question primary cost.

## Fixed interpretation

Format calibration is adequate locally only if the selected wrapper has at
least14/16 valid outputs. Base retention competency requires at least24/32
correct and28/32 valid; otherwise the unchanged retention panel is descriptive
and uninformative about preserving a demonstrated capability. These are
predeclared development gates, not confidence bounds or production thresholds.
Report all eight adapter-minus-base and four paired bursty-minus-interleaved
differences. No winner, equivalence or causal scheduling benefit is inferred.

The data and labels are investigator-visible and operator-authored. They are
**not independently held future B**, regardless of disjoint IDs, hashes, code
review or task counts. Authenticated independent curator/Owner custody remains
an external prerequisite; original sealed-input/effect/adoption/cold-recovery
gates remain separate. The study can close bounded format and fresh-task
diagnostics while every scientific/production selection remains HOLD_NO_GO.
