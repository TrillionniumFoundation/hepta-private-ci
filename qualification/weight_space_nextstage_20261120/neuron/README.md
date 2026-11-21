# Bounded causal rescue and joint representation/readout editing

**The declared-law analytic control rescue passed; the bounded joint weight
candidate did not qualify. The final decision is KEEP_ORIGINAL_AND_STOP.**

This is a source-only research snapshot. Raw checkpoints, candidate identifiers,
host details, generated worlds and execution evidence are retained separately.
Publishing this harness does not certify a production model or provide a
standalone production evaluation service.

## Scope

The experiment uses five existing, independently fitted research models with an
`85 → tanh(48) → 4` MLP: 4,324 network parameters and eight frozen physical
parameters. The task predicts a sign at a fixed deadline and permits sensor
repair. The latent CTMC has endogenous renewal/reset; sensor repair is not a
latent-reset control. First-passage objectives and separate Call/Put channels
are outside this task.

The oracle uses the declared transition/emission law, currently available
history and public schedules. It never reads realized future outcomes. The
declared law includes the original fitted observation decoder. Its optimality
claim is confined to that finite law.

## Interventions and prospective evaluation

Fourteen arms are fixed before confirmation:

| Arms | Intervention |
|---|---|
| C | Original network and inference |
| S | Declared-law posterior mass and bank features; original network |
| B | Declared-law terminal posterior scores |
| Q | Declared-law optimal continuation scores |
| SB, SQ, BQ, SBQ | Corresponding factorial combinations |
| J_own | Full-state dynamic programming under the checkpoint's own law |
| D | Previously frozen direct-head candidate |
| R, P, RP | Representation component, readout component, joint endpoint |
| K | DEV-selected joint interpolation, or byte-exact C and STOP |

Oracle interventions and J_own change the inference procedure. They are not
deployable parameter edits. R/P/RP/K retain the original graph and input/output
dimensions. P removes the representation component of RP; it is not a separately
optimized best head.

The constructive weight program uses only the original 320 TRAIN worlds and
144,397 states. It selects two residual directions with input ridge `1e-3` and
SVD, attempts to install them into two low-impact existing units, and solves a
four-output readout problem with ridge `1e-4`. The analytic targets are the
checkpoint's own-law optimal Bellman continuation values and clipped posterior
logits. This is teacher-label fitting within a broad weight-programming
protocol, outside WeightCode's main no-label-fitting protocol. There are zero
gradient updates; gradients of the quadratic are computed for numerical KKT
certificates.

Each endpoint changes 172 first-layer coordinates and 196 readout coordinates.
All non-network fields and eight physical parameters remain fixed. Exact
rational checks bind the actual serialized full-network displacement to the
original 147-coordinate continuation-head radius. Belief may change; its
protection is a calibration gate, not functional invariance.

All candidate families are sealed before 40 fresh IID DEV worlds are generated.
The four interpolation coefficients are fixed at `0, .25, .5, 1`. Selection
requires mean utility gain at least `.005` and calibration deterioration no
greater than `.0001`; the highest eligible utility wins, with the smaller
coefficient breaking ties. Failure selects the original compressed bytes.

All five selections are sealed before separate entropy generates 160 fresh
confirmation worlds: five fits, two domains, sixteen worlds per fit/domain.
Historical exclusions include 3,256 known schedules; the known set after this
study is 3,456 schedules. This does not certify unknown external exposure.

Calibration is single-Bernoulli excess Brier on the full legal state DAG. Every
candidate uses the same weights: `.9 × normalized C occupancy + .1/N`. The
statistical units are the five fits, not individual worlds or states. Eight
primary comparisons use paired Student-t intervals with four degrees of
freedom and two-sided Bonferroni familywise 95% coverage. The normality
approximation is explicit; the procedure is not distribution free.

## Confirmation results

Utility and interaction gates require the interval lower bound to exceed
`.005`; calibration requires its upper bound below `.0001`.

| Contrast | Domain | Mean difference | Familywise 95% interval | Gate |
|---|---|---:|---|---|
| K − C utility | IID | +0.005114149 | [−0.042921363, +0.053149660] | Fail |
| K − C utility | OOD | +0.013747745 | [−0.037102030, +0.064597521] | Fail |
| BQ − C utility | IID | +0.122360781 | [+0.078133011, +0.166588552] | Pass |
| BQ − C utility | OOD | +0.177614171 | [+0.092734910, +0.262493432] | Pass |
| RP − R − P + C utility | IID | +0.002797501 | [−0.013650565, +0.019245566] | Fail |
| RP − R − P + C utility | OOD | 0 | [0, 0] | Fail |
| Calibration K − C | IID | −0.000062394 | [−0.000316397, +0.000191610] | Fail |
| Calibration K − C | OOD | −0.000337700 | [−0.001608347, +0.000932946] | Fail |

K fails all four qualification gates. Positive mean utility and improved mean
calibration do not replace the predeclared confidence bounds.

Descriptively, Q alone captures 95.31% of BQ's mean improvement in IID and 72.12%
in OOD. The own-law planner is within `.000774` and `.001240` of the respective
BQ mean utilities. These are exploratory comparisons. They suggest a gap in
compressing complete-state decisions into the fixed representation/readout,
but do not prove that a repair confined to the continuation head is possible.

## Why the representation component had little effect

The radius constraint contracts the proposed representation displacement to
0.1005%–0.2285% of its intended displacement. Achieved preactivation standard
deviations are `0.078765–0.149573`, versus the construction target of `.5`.
The parameter budget was used: representation consumes approximately 25% of the
squared bound, readout 75%, and the joint endpoint almost the full bound.

Saved actions and DAG edges explain the OOD equality without another model
run. Across 35,713 OOD support states, R/C differ at eleven states, all with zero
C occupancy; RP/P differ at six states, all with zero P occupancy. Their
respective reachable trajectories therefore have no first action divergence
in these eighty worlds. In IID, RP/P differ at ten of 38,094 support states;
only one world has a difference reached by P, and the joint endpoint loses
utility there.

This does not establish global representation sufficiency or rule out a
different, explicitly changed parameter/feature contract. It shows that this
bounded feature-installation attempt did not achieve its intended functional
change.

## Failures, numerical erratum and costs

The first scientific child completed and sealed all candidate families, then
failed at the first DEV model-file lookup because of a Path indexing error.
It produced no DEV model scores. Its failure and 40 generated-but-unscored DEV
worlds are retained, and those worlds are excluded from the revision.

An explicitly authorized technical revision corrects the file lookup and
authenticates byte-for-byte reuse of the original families, teacher records and
models. It does not reconstruct TRAIN, repeat a solver, retune a hyperparameter,
change a primary test or reuse a generated world. The original scientific
child costs 38.354773 CPU seconds; the revised evaluation costs 99.471936 CPU
seconds. Their total, **137.826709 CPU seconds**, remains within the original
300-second scientific budget. Combined wall time is 138.280440 seconds.

The originally frozen independent reader failed an exact optimal-action check:
Python's built-in summation and the source's explicit F64 sequential addition
can select different actions at near ties. A separately frozen reader-only
erratum preserves both calculations. It checks strict action identity using the
declared arithmetic order and separately reports every alternate-summation
disagreement under the original oracle tolerance. Across 200 DAGs, fifty
near-tie action disagreements have maximum Q difference `2.22e-16` and maximum
action regret `1.11e-16`. No scientific source, parameter, sample, result,
tolerance or primary gate changes.

The corrected independent review passes on 245 pinned files, 45 parameter
models, 200 DAGs and 91,312 states. The first failed reader, counterexample
diagnosis and corrected reader together consume 5.324846 CPU seconds, below
the original eight-second reader budget. It makes no model or optimizer calls.
It independently recomputes stored-DAG utility, Bellman values, occupancy,
common-support calibration, selection, intervals, model bytes and exact norm
bounds. It does not regenerate CTMC probabilities, model actions, TRAIN labels
or external-label custody.

Five family constructions account for 36.544242 internally measured CPU
seconds; the readout spectral solves alone account for `.172039` seconds.
Reporting only the latter would omit most work. This study does not establish a
matched causal speedup over previous direct-head, PGD or full-MLP runs: targets,
cached data, arm counts and evaluation worlds differ. No resource-to-utility
exchange rate is assumed for NDU.

The original model bytes are verified on restoration. No production model is
changed. Further training, radius expansion or repeated confirmation is not
part of this completed study.

## Source inventory and replay boundary

The source snapshot contains the causal core, candidate-reuse authenticator,
explicit-revision driver and protocol freezer, bounded supervisor, original
independent reader, separately named numerical erratum reader, and two
saved-record descriptive scripts. The original failed reader remains present;
the erratum is not silently substituted for it.

These scripts require the corresponding immutable prior research modules and
private input bundle. `HEPTA_WSP_INPUT_ROOT` identifies that input tree. Frozen
protocols bind actual paths and hashes; they must not be edited to relabel a new
run as an old one. A fresh execution requires a new, explicitly frozen protocol
and newly held-out worlds. Source publication alone does not provide the
private input bundle or authorize another scientific run.
