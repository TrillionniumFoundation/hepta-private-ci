# Independent V3 protocol review and analysis contract

Status: **prospective design review; no V3 model outcomes inspected**. The
source-allocation audit and synthetic source/statistical contracts pass. This
supports registering the design. It does not authorize an unfrozen phase or
establish any scientific gain.

Reviewed inputs are the V3 [protocol](../field_bridge_v3_20261027/PROTOCOL.json),
[source allocation](../field_bridge_v3_20261027/SOURCE_ALLOCATION.json),
[training proposal](TRAINING_DESIGN_PROPOSAL.md), and the unchanged V2
[blocker ledger](../field_bridge_v2_20261027_review/BLOCKERS.json). Protocol bytes
read for this review had SHA256
`fa44d375cd5633e21e32b958a63a91b08f0f994e6f0e78afca5705fe6c3bb5dc`.
Later pre-label edits must be identified by the eventual registration/freeze;
this document is not a substitute for that executable source boundary.

## What this new study can answer

V2 retains its original **0/6 joint primary acceptance**. Ordinary B−A task gains
were positive under both observers, while B retention noninferiority was not
established. The local H7 trajectory gates passed without establishing complete
endpoint superiority over ordinary training. The native/history comparison
established neither superiority nor equivalence. V3 changes the intervention
and, for runtime, the task; it cannot retroactively change those conclusions.

| Existing question | Required new evidence | Remaining claim boundary |
| --- | --- | --- |
| B03: ordinary learning | New complete ordinary versus frozen endpoint gain and independent clean noninferiority; eventual registered B−A confirmation if reached | Best of the four registered constants is a bounded comparator, not the strongest conceivable conventional training method |
| B04: field training increment | Fixed H12 must beat ordinary and the development-selected eligible adaptive control in the independent complete-rollout audit; final C−B and E−G remain separate confirmations | H12 is fixed before labels; Q-ref is a reference-continuation target, not a sufficient-state theorem or deployed-policy Q |
| B05: runtime control | Selected-path native versus the strong fixed plan, with equal legal actions, feedback schedule, scoring and clean gate | A positive result would concern the new simulated-feedback task, not the old V2 two-preview task |
| B06: contribution beyond history | Native versus an independently fitted full-public-history control with equal raw information, head capacity, candidate opportunity and targets | Current-only and reset variants are diagnostics; state sensitivity alone is not a superiority result |
| B07: retention | Train-only rehearsal/guard, disjoint clean development and audit endpoints, and untouched final clean outcomes with the fixed 0.01 margin | Passing an empirical training guard is not population noninferiority; a failed NI test does not prove excessive damage |
| B09: source/access independence | New disjoint gradient, rehearsal, probe, guard and endpoint roles across fit/development/audit, plus frozen access enforcement | V2's shared response-panel limitation remains recorded; new-source identity is relative to the recorded registry, not unknown pretraining or writer identity |

There are two explicitly different objectives. Learning qualification uses the
historical fixed single-action output task. Runtime and the full six-contrast
confirmation use the new three-decision feedback task. Transfer between them
is tested, not assumed. Final single-action diagnostics may clarify that
boundary but cannot replace the registered new-task primary comparisons.

## Source allocation and access boundaries

The independent [source receipt](SOURCE_ROLE_AUDIT.json) reconstructs allocation
directly from all 70,000 checked original IDX images and the exact complete
29,000-image V2 registry. It reproduces the salted ordering, original indices,
pixel hashes, role summaries, exclusions and capacity accounting. It verifies
23 roles and all 253 pairwise role intersections, with zero cross-role or prior
pixel overlap. No model, task, observer or outcome was computed; original class
bytes were used only for conflicting-duplicate exclusion.

The accepted allocation manifest is
`9bfcb279d5efdc7bd6c14af41c64c04a78fc97f7827f7464280d8997d8fead41`.
It assigns 26,000 new official-train images and 2,048 new official-test images,
leaving 9,000 and 3,952 respectively unassigned. Final task and clean retention
contain 1,024 and 2,048 source pairs. Runtime audit was prospectively enlarged
from 128 to **512 pairs**, without opening model outcomes. Runtime fit/selection
remain 128/64 pairs.

The loader materializes only explicitly named roles. Its registry checks do not
themselves enforce study phases: every runner must validate the phase freeze
and its exact role allowlist before constructing task labels or model outputs.
The audit gradient/rehearsal/probe/guard roles are adaptation inputs to a frozen
policy, not untouched evaluation outcomes. Only that audit's separate task and
clean endpoint roles provide independent endpoint evaluation. Reusing the
registered fit roles for the final fixed-schedule training is allowed after
policy freeze; reusing final task/retention outcomes for a revised study is not.

The [11 synthetic source/API contracts](SOURCE_ROLE_CONTRACTS.json) cover
same-label deduplication, conflicting duplicates, cross-origin exclusion,
incomplete prior coverage, altered indices/hashes/role order, source capacity,
and explicit role-only loading. An initial test-fixture expectation mistakenly
discarded both copies of a same-label duplicate; the first-copy-retention
expectation was corrected and the failed receipt was preserved. The allocation
and independent reconstruction algorithms were unchanged.

## Gates, comparator selection and stopping

Reference selection precedes all Q-ref branch labels and uses its declared
reference panels. The selected constant and its complete checkpoint identities
must be frozen before continuation labels. Every branch uses the same future
minibatch schedule, exact parameters and complete optimizer state. Guard
rejection restores all trainable state and momentum while the schedule clock
advances. The zero action holds parameters and momentum exactly; its declared
gradient work is still charged.

H12, generic12, richer30 and H7 are all fixed prospectively. Three ridge values
are selected using whole-fit-trajectory cross-validation with normalization
fitted inside each fold. Four fit paths provide only **24 correlated branch
states per historical seed**, not 24 independent trajectories. All four action
targets and all candidates remain available for inspection. Directional
features must use the same clipped rehearsal/anchor objective as actual updates.

Development uses four complete rollouts per historical seed and source-disjoint
development roles. Ordinary chooses one of four constants per seed by reward
utility, after clean eligibility under both observers. The adaptive comparator
is selected once among generic12/richer30/H7 by pooled reward utility after
each-seed clean eligibility; ties follow registered order. H12 is never replaced
by whichever representation happens to win. No eligible comparator means
qualification failure, not an implicit fallback.

Development requires ordinary pooled gain at least 0.005 and no negative seed
under either observer; H12 must have positive pooled advantage over ordinary
and nonnegative advantage over the selected adaptive method. Ordinary and H12
must each satisfy the registered per-seed clean change threshold. These are
screening rules, not independent statistical confirmations.

After comparator and predictor freeze, one independent four-rollout audit must
pass all three gains and all three clean noninferiority comparisons under both
observers. No audit-based refit, family switch, threshold change, sample-size
increase or retry is allowed. A failed learning qualification leaves its final
training/combined claims unestablished. The separately prespecified frozen-model
runtime scope may proceed through its own gate. If that alone reaches final
evaluation, unrun primary contrasts remain unestablished and keep the original
six-comparison denominator. That final run consumes the entire primary and
retention roles for later learning studies too.

## Executable statistical contract

[analysis_contract.py](analysis_contract.py) implements the independent array
contract. Its [17 synthetic contracts](ANALYSIS_CONTRACT_TESTS.json) test paired
covariance, complete-rollout uncertainty, fixed-seed weighting, shared source
clusters, task/clean rollout coupling, dual-observer conjunction, strict
boundaries, missing/nonfinite input rejection, retained family denominators,
deterministic draws and clean-eligible development selection.

Input arrays have axes **[fixed model seed, complete rollout, source pair,
condition]**, separately for each named method and observer. All identities,
conditions, rollout IDs, scoring randomness and batch shapes must be aligned
before calling the statistics. The training implementation confirms endpoint
panels do not depend on rollout schedule ID. Method decisions may differ;
endpoint examples and scoring marks do not.

For each bootstrap replicate, `numpy.random.default_rng(registered_seed)` draws
four rollout indices independently within each of the three fixed seeds. The
same indices are applied to every method, observer, task and clean endpoint.
It then draws one task source-pair index vector and one clean index vector,
each shared across all methods, seeds and conditions in that panel. Conditions
and historical seeds retain equal fixed weights. Runtime and final arrays have
one rollout, so no rollout draw occurs. The implementation records the complete
draw-stream digest and uses `numpy.quantile(method="linear")`.

| Family | Number in correction | Two-sided interval per observer | Acceptance |
| --- | ---: | ---: | --- |
| Independent learning audit: three gains + three NI tests | 6 | 99.1667% | All lower bounds pass; gains additionally positive in every historical seed; both observers |
| Runtime audit: native−fixed, native−history, native/history clean versus fixed | 4 | 98.75% | Frozen profile alone, or conjunction across all three profiles; no favorable-profile selection |
| Final task gains | 6 | 99.1667% | Registered contrast lower bound >0 and each-seed mean >0 under both observers, plus candidate final NI |
| Final clean retention, every non-A arm versus A | 10 | 99.5% | Lower bound strictly >−0.01 under both observers |

Every family has alpha 0.05 and 4,000 draws. Learning audit seed is 271032;
runtime audit 271034; final task 271035; final retention 271036. For runtime,
the clean comparison is the clean condition of the same registered audit
source pairs, so it must reuse that audit's source-index draws rather than
pretend to be an independently sampled retention population. Final clean
retention uses its separate source role and draw stream.
The executable contract represents runtime NI as `condition_indices=[3]` on
the same task panel, not as a second independently resampled panel.

The two observers are a **conjunction criterion**. Both enter development
selection or gates; the audit observer is a distinct measurement model, not a
development-blind outcome. Per-observer intervals are not claimed to have joint
simultaneous coverage across both entire observer families. Statistical
uncertainty is conditional on the three historical models and the declared
source populations; four optimizer schedules do not create new independently
trained base models.

## Precision and total work

The new sample counts improve precision but cannot guarantee gate passage.
Using V2 paired-source dispersion solely as a planning anchor, a 0.005 C−B
effect required about 1,000 pairs for approximate 80% power with a six-comparison
normal approximation. A 0.0015 E−F effect required roughly 1,500–1,600 pairs;
V2's much smaller native/history point differences would require substantially
more. These estimates do not establish the new feedback task's variance and do
not include added optimizer-path uncertainty. The 2,048 final clean pairs are
a reasonable fixed precision choice for the 0.01 margin; they do not guarantee
all ten candidates and both observers pass. No final-result-driven sample
increase is permitted.

Exact reference tails are expensive. Four fit paths × three seeds cost
`3 × 4 × [4 × (288+240+192+144+96+48) + 288] = 51,840`
gradient microsteps before directional probes, guard scoring and teacher work.
Reference constants add 3,456; all four ordinary plus four adaptive development
methods over four paths add 27,648. The implementation retains all four frozen
adaptive heads plus selected ordinary during audit, adding 17,280 microsteps
if qualification is reached; only the preregistered selected adaptive comparator
enters its acceptance family. Retaining those five final trained methods adds
4,320 microsteps across the three seeds. These are declared invocation counts, not FLOPs or
wall time. Shared search is charged once at study level and attributed openly;
rejected updates, zero actions, failed candidates and all continuation tails
remain in the ledger.

For all three profiles and three seeds, full runtime fit/selection trees cover
6,912 episodes, 580,608 non-stop tree transitions and 587,520 output nodes.
These 85-node trees are repeated outcomes of one source episode, not 85
independent episodes. Qualification/final evaluation executes only chosen paths.
The frozen controller sees at most three decisions, six native ticks and four
delivered-output decodes per episode under the declared initial action rule.
Record actual generator/teacher/verifier/observer, feature/head, state,
serialization and persistence work separately; do not infer measured total
latency from these counts.

No wall-clock acceptance threshold remains. CPU and wall timings are descriptive
with host/runtime/thread and workload metadata. The native kernel's original
`requires_calibration=true` state must remain visible; local readout fitting
does not clear production calibration or owner-integration requirements.
Authority remains DENY_ALL. No positive small-task result would prove the
paper's sufficient-state assumptions, HJB/FBSDE equations, LLM scaling,
long-horizon production behavior, or owner integration.
