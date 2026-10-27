# V3 training design proposal: terminal control and retention

Status: **design only; not a frozen protocol; no V3 target labels, model outputs,
training trajectories, or new evaluation outcomes have been inspected.** Root
must settle the remaining choices, allocate identities, and commit executable
source and protocol before the corresponding labels are opened. This document
does not authorize a run or change any V1/V2 source, criterion, or result.

## Question and prior evidence boundary

The proposed new study addresses B03, B04, and B07. V2 established a positive
ordinary-training task difference, but did not establish that ordinary endpoint's
independent retention noninferiority. V2's H7 local decision gates passed while
the complete terminal C−B and E−G contrasts did not pass. The next intervention
therefore changes the training objective, continuation target, and prospective
qualification test. It is not a rerun of V2 with new favorable samples.

V2 remains immutable: no change to its six primary contrasts, nine retention
comparisons, 0.01 margin, unsuccessful results, or inactive conditional D1 audit.
Directional measurements can be a prospectively declared V3 feature treatment;
they are not a retrospective activation of V2 D1.

Relevant prior sources are V2 `PRIMARY_PROTOCOL.json`, `learning.py`,
`directional_features.py`, review `BLOCKERS.json`,
`PRIMARY_INTERPRETATION_REVIEW.md`, and `SOURCE_ALLOCATION.json`.

## Minimal proposed intervention

Keep the recovered historical models, upstream rank-eight actuator, 288-microstep
horizon, batch scheduling discipline, learning-rate range `[0, 0.25, 1, 2] × 0.2`,
SGD momentum 0.9, and gradient clipping at 1.0. Use **six decisions of 48 steps**
at times 0, 48, 96, 144, 192, and 240. This gives the target model exact training
examples at every decision time and makes full-tail continuation labels feasible.
It deliberately changes V2's eight-step decision interval and must be described
as a new treatment, not an isolated comparison to the V2 controller.

For a complete optimizer state `s = (theta, momentum, time, schedule)`, define:

`Q_ref(s, a) = hard task utility at step 288 after action a for the next 48 steps,
then continuation under the frozen reference policy for every remaining block.`

The reference is a constant multiplier selected from the four registered
ordinary candidates using a dedicated reference-selection panel. Its empirical
clean eligibility rule and tie order are frozen before those outcomes. Select
the reference before constructing any continuation targets; do not update it
after policy development. The strongest final ordinary comparator may be a
different constant selected on the common policy-development stage.

Each branch starts from an exact clone of parameters, complete SGD state,
schedule position, and RNG convention. Each future minibatch and corruption
schedule is the same across actions. Terminal targets use actual hard decoded
UTF-8 / quantized eight-bit image outputs and the frozen reward observer. Save
per-example values and output identities, not only their scalar mean.

`Q_ref` is a reference-policy continuation target. It is neither optimal Q nor
the true value of the ultimately deployed receding policy. This remaining
distribution mismatch is addressed by prospective complete-policy rollouts,
not by naming the fitted predictor a value function. No Riccati, HJB, FBSDE, or
global sufficient-state theorem is being reproduced by this construction.

## Common train-only retention mechanism

Every training method receives the same clean rehearsal examples, objective,
hard-output guard, and rollback semantics. A proposed single fixed objective is

`L = (L_adapt + 0.5 L_clean)/1.5 + 0.1 (D_adapt + 0.5 D_clean)/1.5`,

where each supervised component is the current model's mean joint loss and D
is the already defined original-model anchor. Use 64 adaptation and 32 clean
rehearsal examples per microstep. The 0.5 and 0.1 constants are proposed now;
they must be accepted or replaced before labels, not selected after outcomes.
The next-gradient directional features must use this exact weighted, clipped
objective, including rehearsal, rather than the old V2 objective.

At every 48-step boundary, measure the candidate's hard clean utility on its
registered **training guard** panel. Accept the candidate only if its mean
paired change from the original model is at least zero. Otherwise restore the
entire pre-block parameter and optimizer state. The schedule clock advances by
48 in either case; the next decision is a new decision at that time. There is
no unregistered search over smaller rates after a rejection. The same guard
operates inside all reference continuations used to construct terminal targets.

The zero action is an exact parameter-and-momentum hold. Its gradient/probe
execution convention must be identical across methods and declared explicitly.
For direct continuity with V2, compute the common gradient schedule even for a
zero action and charge it, without stepping SGD or updating momentum.

The guard is an empirical training constraint. Repeatedly using that panel makes
it training data, and passing it is not a population noninferiority guarantee.
The ordinary comparator receives precisely the same mechanism; thus an eventual
C−B contrast isolates the controller under a common retention intervention.
Count every rejected gradient, original-model teacher call, probe, observer call,
and clone/restore operation. No discarded work disappears from the cost ledger.

## Methods and comparison scope

| Method | Training decision | Purpose |
| --- | --- | --- |
| Original checkpoint | No parameter adaptation | Baseline for gain and clean retention |
| Ordinary constants | All four complete constant-multiplier schedules with the common rehearsal/guard | Strong ordinary parameter-training comparator; no curtailed search |
| Prospective H12 terminal controller | H7 plus five momentum-direction features; one common terminal-return head per action | Predeclared V3 field candidate |
| Generic12 terminal controller | Fixed-seed 12-dimensional projection of the same full diagnostics | Equal-dimensional, equal-target adaptive comparison |
| Richer terminal controller | All registered diagnostics, including the same direction features | Strong adaptive comparison with full measured information |
| H7 terminal controller | H7 alone, same targets and fitting rules | Diagnose value-target repair separately from the five directional features |

All adaptive methods share exactly the same branch bank, feature acquisition,
training labels, action range, admissibility guard, candidate grid, and fit-only
normalization. A minimal common head grid is ridge alpha `[1e-4, 0.01, 1]`, with
grouping by whole trajectory during any fit-side selection. Fix all feature
coordinates, projection seed, centering/scaling, objective, tie order, and
selection rule prospectively. Retain every candidate and endpoint.

The proposed H12 candidate is chosen from prior mechanistic evidence, not by
opening several fresh audits and keeping their winner. H7 and richer/generic
results must remain visible even if H12 fails. A gain over ordinary constants
supports an adaptive-training intervention; a claim that the named field
representation contributes beyond ordinary adaptive methods requires the
corresponding generic/richer comparisons as well. Direct candidate rollouts are
charged reference planning; they cannot be relabeled field sufficiency.

Preserve the original six primary deployment contrasts if root carries the
study to its full evaluation. B04 still needs C−B under the same literal fixed
deployment action and E−G under the registered native deployment procedure.
The latter includes checkpoint-specific readout mediation; report it as such.
The native agent owns any additional causal runtime control design.

## Source roles and a feasible allocation budget

Exclude **all 29,000 image identities in V2's expanded source allocation**,
including unused registered suffixes, using pixel hashes. The allocation has
25,000 official-train-derived and 4,000 official-test-derived identities. The
unfiltered remaining upper bounds are therefore 35,000 and 6,000 respectively.
Root must verify actual unique, nonconflicting capacity before freezing counts.
Simply increasing the old loader's train count shifts downstream splits; use
explicit exclusions and new named roles instead.

The following budget is a proposal, not an allocation or label-access grant.
Pair counts consume two disjoint source images; corruption conditions reuse a
pair only within its own registered role.

| Role | Source images | Label use |
| --- | ---: | --- |
| Fit adaptation gradient pool | 6,000 | Parameter updates and fit trajectory generation |
| Fit clean rehearsal pool | 1,024 | Parameter updates |
| Fit response probe | 256 | Training-state features and terminal fitting targets |
| Fit clean guard | 512 | Repeated training admissibility checks |
| Reference-selection task panel | 512 | Select frozen ordinary continuation reference |
| Reference-selection clean panel | 512 | Reference empirical eligibility |
| Policy-development adaptation / rehearsal / response / guard | 2,000 / 512 / 256 / 512 | Complete policy rollouts; each pool disjoint from fit |
| Policy-development endpoint task / clean | 1,024 / 1,024 | Selection/gating; never online decisions |
| Independent rollout audit adaptation / rehearsal / response / guard | 2,000 / 512 / 256 / 512 | Frozen-policy complete rollouts on a new adaptation population |
| Independent rollout audit endpoint task / clean | 1,024 / 2,048 | One prospective gate; no refit or candidate selection |
| Runtime fit / development | 1,024 / 512 | Separately registered runtime readout training/selection |
| Final clean retention | 4,096 | 2,048 untouched pairs, both observers, fixed 0.01 margin |
| Final primary task | 2,048 official-test images | 1,024 untouched pairs, all registered conditions |

This provisional plan uses 26,128 new official-train-derived images and 2,048
new official-test images. It fits the broad known capacity without touching any
V1/V2 source role. Allocation must verify the exact total and hash intersections.
All roles in this table are mutually disjoint. Fit, policy development, and
independent audit also use distinct gradient data, not merely different random
schedules on the same labeled pool. This is the clearest repair of literal B09.

After the controller is frozen, final checkpoint training may reuse the fit
roles. It need not consume a fourth new adaptation population. Final evaluation
and retention remain unopened until all checkpoints and runtime policies are
frozen. This is freshness relative to the recorded registry, not a new-writer
claim or proof of no unknown pretraining exposure.

## Gates and access sequence requiring root/reviewer agreement

1. Commit source allocation, the whole finite development candidate set, gradient
   and measurement schedules, clean mechanism, terminal labels, and development
   stopping rules before opening V3 development labels. Predeclare the later
   confirmation sample counts, margin, contrast family, and no-reuse rule now.
2. Build the bounded fit bank and all ordinary/adaptive candidates. Then execute
   complete 288-step policy-development rollouts on the new development pools.
   Fit-side MSE or local action regret is diagnostic only. Qualification must
   include terminal utility against the strong ordinary and adaptive controls,
   with terminal clean outcomes measured separately from the online guard.
3. Freeze the chosen source, coefficients, comparator, action/guard conventions,
   and all gate thresholds before one independent complete-rollout audit. That
   audit must use its own adaptation, probe, guard, and endpoint pixels. Its
   outcomes can accept/reject the frozen candidate, not choose a new candidate.
4. Only if the registered training/runtime qualification rules pass, train final
   checkpoints on the fixed fit role, fit runtime readouts under their registered
   development plan, and commit the complete pretest freeze. Open the fresh final
   primary and retention labels exactly once. Keep null and negative outcomes.

The numeric development/audit gates, trajectory count, exact primary comparison
family, bootstrap resampling unit, and runtime qualification are deliberately
unresolved here. The independent reviewer owns their critique; root must freeze
one concrete choice before labels. Retention's final absolute margin stays
0.01. The proposed 2,048 final clean pairs are a prospective precision choice,
not a post-result increase. Uncertainty remains conditional on the three fixed
historical model seeds unless new models are independently trained.

## Compute and evidence contracts

With six decisions, one complete trajectory supplies six branch states. Four
actions with exact reference tails cost
`4 × (288 + 240 + 192 + 144 + 96 + 48) = 4,032` gradient microsteps per seed and
exploration trajectory, before its 288-step executed path. Eight fitting paths
and three fixed models would therefore consume 103,680 total gradient
microsteps for branch labels plus executed fitting paths. This is an explicit
proposal to budget, not an authorized run; fewer predeclared paths or decisions
may be needed before protocol freeze. Guard, probe, teacher, observer, clone,
predictor fitting, policy development, audit, runtime, and final evaluation add
work and must be counted separately. Shared exploration is counted once at
study level and attributed transparently to methods.

Required implementation contracts include exact optimizer clone/continuation,
zero-action hold, full rollback including momentum and optimizer hyperparameters,
correct weighted/clipped directional derivatives, teacher/gradient RNG invariance,
decision commitment before future outputs, actual hard-output readback parity,
source-role separation, trajectory grouping, and candidate/probe resource counts.
Save source identities, all candidates and head coefficients, endpoint hard
values/hashes, accepted/rejected decisions, complete final optimizer checkpoints,
and predefined replay receipts. No best-step checkpoint selection is introduced.

## Proposed ownership

Root owns source allocation, protocol freeze, persistence, publication, and later
primary evaluation. The training-design agent can implement isolated V3 learning,
continuation-bank, and closed-loop training modules after agreement. The native
agent owns runtime mechanisms. The independent reviewer owns gate/identity/cost
critique and audits. Existing V1/V2 source files are imported read-only or pinned;
their module globals must never be mutated to configure V3.
