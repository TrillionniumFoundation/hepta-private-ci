# Cell V4: causal state-closure test

Status: source/protocol preparation, before any new final-label access. This file
and `cell_field_closure_protocol.json` must be committed and published before the
new cohort is prepared. The executed source commit is recorded by the runner.
Authority is research `DENY_ALL`; no production or deployment permission follows.

## Question and fixed comparisons

V3 found that a two-loss, memoryless projection lost multi-step action-ranking
information. V4 compares that exact projection with two- and four-step causal
loss/input windows, the existing four-observable optimizer summary, and the
complete Adam tangent state. `Full` means the complete small-head optimizer
state, not a full language model. Every arm uses the same full-state calibration.

The six V3 fitted trajectories are rebuilt from their exact original training
features and labels: linear/gated heads, seeds 7/17/29, 64 old-context updates,
then current-context anchor offsets 0/8/16. These are reused development
trajectories, not six new independent training tasks. Each anchor has one zero
action and eight fixed antipodal Rademacher pairs, unrelated to either optimizer's
preferred direction. There are 18 anchors and 306 distinct real action branches.
Every action is one post-Adam impulse followed by seven zero-action updates.

All five predicted response maps, objectives and selected action indices are
sealed before any real action branch is executed. Action selection uses the first
exact minimum in frozen action order. All real branch predictions are then sealed
before an arithmetic/provenance audit and the single final-label access.
The audit requires the complete pre-execution file census and no branch outputs
inside it. From the pinned original V3 inputs it reconstructs the 480 warmup and
anchor-training steps and replays every one of the 2,448 branch Adam steps,
checking states, receipts and recalculated probe observations. This replay uses
the existing optimizer implementation; common-cost arithmetic is implemented
separately. Neither is third-party attestation.

## Sources and external evaluation

The byte-pinned official UCI archive and full story/title union graph determine
source components. All legacy cohorts and all V1/V2/V3 source components are
excluded, including their previously unselected aliases. Conflicting classes,
cross-month components and the existing OOD publisher partition are excluded.
The fixed salt selects 32 April and 64 July sources, balanced over four classes.
All other eligible component identities are reserved without emitting their
labels or titles into the final payload. The changed time scope is explicit:
V3 exhausted eligible June health components and almost exhausted August health.

The existing real Granite 97M snapshot stays frozen. Before encoding the new
sources, the first eight original old-train sources must reproduce their cached
384-dimensional features within absolute tolerance 1e-6. This bridge detects a
material cross-environment feature change; its calls, tokens and time count as
cost. The model inventory, all input/feature bytes and environment are recorded.
The label-independent original eight-dimensional QR projection is reused.

Primary external evidence is six comparisons at anchor offset 16: history2,
history4 and moment4 versus Loss2, separately for the two head architectures,
using July NLL. Each source difference is first averaged over the three fixed
seeds. A 10,000-replicate class-stratified paired source bootstrap uses the
registered seed and Bonferroni percentile endpoints for six comparisons.
An upper endpoint strictly below zero is the predeclared passing condition.
This is conditional source uncertainty, not a training-seed/task-population
inference or finite-sample coverage guarantee. Every comparison is reported.

April retention, accuracy, Full/zero/warmup and other anchors are secondary point
estimates. They cannot replace failed primary comparisons or choose the next
method. Once accessed, these final sources are unavailable for later model or
topology selection. Foundation pretraining exposure remains unknown.

## Interpretation and integrity

Mechanism metrics cover the complete finite action pool: per-step response MAE,
common-cost MAE, equal-radius directional Kendall tau-b, and realized regret of
each predicted minimum. Anchors and antipodal actions are correlated; they are
not treated as independent tasks. A causal history is exact while the known
impulse remains inside its window; its later error is measured, not assumed away.

Report full-state reference construction, closure maps, retained action/output
scalars, branch execution, feature extraction, audit/evaluation time and artifact
bytes. A history representation can cost more than the full small-head state.
The common calibration prevents a claim that low output dimension alone makes
the whole system lightweight. No cell splitting, autonomous topology growth,
general intelligence or broad agent superiority is tested here.

The single registered source owner is
`/home/qian-qi/work/hepta-architecture-20261025/cell-v4-evidence-v1`.
Preparation and all source consumers accept only its `data` directory, without
symlink aliases. Preparation creates that directory once; a changed feature,
run or evaluation output directory cannot create another copy of this cohort.
The final-access ledger is create-only in that same registered source directory.
Preserve the directory and ledger after every failure. These checks bind this
published protocol and local source owner; they do not claim protection against
deleting evidence or changing the published protocol.

Other stage commands create fresh output directories. Any failure is preserved.
Missing registered branches block final access. Unit-test fixtures verify
mechanisms and integrity only; they are never counted as new task results.
Numerical and encoder workloads are limited to two CPU threads.
