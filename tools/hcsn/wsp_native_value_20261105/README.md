# WSP: value-oriented edits, exact native certificates, and actual Pocket4 evidence

This package continues the already published Hepta WSP work with a new frozen
value experiment, a Rust certificate implementation and fresh actual-checkpoint
inspection. **The new pure-weight efficacy experiment failed its primary gate.**
No live Trader improvement, global neural-network optimum or general replacement
for gradient training is claimed.

The research parent is
[85f507f](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/85f507fb2e1c9e8ad9941451641bb4ec3f1dccb4),
whose scientific payload is the earlier
[9f2d00f package](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9f2d00f79bfe7abc334e51f52a0d16f685656e5d/tools/hcsn/wsp_followup_20261105).
The present results must not be conflated with that predecessor's experiments.

## 1. New controlled experiment: objective alignment helps some behavior, not the acceptance result

The incumbent is the same five previously trained 85-to-tanh48 checkpoints
(fits 11, 23, 37, 53, 71). Each has 147 editable continuation coefficients and
a protected Belief row. No new model training fit was produced. Instead of
uniformly copying an optimal teacher's Q values, the new E edit uses a terminal
anchor and the incumbent policy's own-law occupancy:

    Y_a = T_pred + Q_C(s,a) - T_own.

Targets use the original 64 TRAIN worlds per fit and the checkpoint's law.
The fixed mixture gives 90% weight to normalized incumbent occupancy and 10%
to uniform legal support. The constrained direct solver and a matched projected
gradient control G fit the same quadratic and original coefficient ball.
Both select from alpha = 0, 0.25, 0.5, 0.75, 1 on full TRAIN own-law utility.
Zero editing is an explicit candidate. This is fitting without backpropagation,
not optimization without data or computation.

The protocol and source were frozen at 03:54:55 UTC on 2026-11-05, before any
candidate fit or new holdout generation. Protocol SHA256 is
226713c4ceab5ebf4da08e62d495a529ddb41a461bec1ce3f7f6ffbecab981dd.
All candidates preceded validation; all validation gates preceded TEST.
The new scenarios contain 160 validation and 320 test worlds, excluding all
2,416 accessible historical unique schedules. Unknown external history remains
unknown. The independent unit remains the five old training fits.

### Frozen primary result

| Gated E minus unchanged C | Mean utility difference | Familywise 95% conditional interval | Required lower bound | Result |
|---|---:|---|---:|---|
| IID | +0.00483765144 | [-0.01207190410, +0.02174720698] | >0.005 | FAIL |
| OOD | -0.00248379186 | [-0.01116565267, +0.00619806895] | >0.005 | FAIL |

These are paired fit differences with Student-t df=4 and Bonferroni correction
for the two predeclared primary contrasts. Their interpretation is conditional
on the model assumptions for those five reused fits; they are not a
distribution-free guarantee or new-fit replication. Both domains had to pass.

The validation gate accepted E and G only for fit 23. Its validation differences
were +0.00266126 IID and +0.03897440 OOD, while TEST differences became
+0.02418826 IID and -0.01241896 OOD. The four rejected fits were restored to
the entire original C file. Eight restored E/G gzip files are byte-identical to
C; the two accepted files are byte-identical to their frozen raw candidates.
Correct restoration establishes recovery behavior, not efficacy.

### All predeclared controls, including failed arms

The following are descriptive means on the same new TEST scenarios. They are
not substitute primary endpoints selected after seeing the results.

| Arm | Meaning | IID utility | OOD utility |
|---|---|---:|---:|
| C | Unchanged incumbent | 0.226522241 | 0.127536708 |
| E | Raw anchored, occupancy-weighted direct edit | 0.249064080 | 0.125325955 |
| G | Matched gradient solution and finite path | 0.249192589 | 0.125325955 |
| E gated | Frozen validation gate with C restoration | 0.231359892 | 0.125052916 |
| G gated | Same gate for G | 0.231359892 | 0.125052916 |
| EU | Anchor retained, uniform state weighting | 0.226522241 | 0.127536708 |
| EA | Occupancy weighting retained, anchor removed | 0.239293117 | 0.128289038 |
| M | Previously frozen uniform optimal-Q MSE head | 0.199290098 | 0.088370382 |
| R | One fixed random direction matched to selected E norm | 0.155183256 | 0.080142255 |
| P | Zero-edit analytic terminal-posterior program | 0.228037709 | 0.141914408 |
| J | Zero-edit complete own-law Bellman program | 0.365472143 | 0.312819986 |

EU chose alpha zero in every fit. E and G chose the same alpha in each fit,
but are not asserted to be identical parameters or policies: fit 11 has a
small actual IID behavioral difference. Raw E's IID improvement does not
qualify its OOD behavior and cannot be substituted for the failed gated primary
test. The large J difference belongs to a structural program control, not
neural weight editing. In this experiment it is secondary evidence; its prior
finite-task qualification belongs to the predecessor protocol.

The sole science worker used 535.948697 complete child CPU seconds,
537.594690 wall seconds and 260,947,968 bytes peak RSS. Direct E endpoint
solving summed to 0.216799992 CPU seconds and matched G to 4.370659790 seconds.
The approximately 20.16-fold endpoint ratio excludes shared construction,
selection and acceptance work and is not an end-to-end or equal-useful-quality
speedup. Independent verification and preparation costs are separately retained
in value_edit. Historical training, agent inference and energy are not measured
as zero. See that directory's final acceptance and cost records for the complete
execution accounting.

### Bounded post hoc diagnosis of the failed accepted fit

After the primary result was frozen, a separate read-only diagnostic covered
all 16 validation and 32 TEST OOD worlds of the sole accepted fit 23. It did
not create a candidate, change a threshold, resample a world or claim a new
confirmation set. The diagnostic source/protocol were frozen before that
execution. It cost 3.130104 complete child CPU seconds.

On validation, its mean utility difference is +0.0434262 under the checkpoint's
own law and +0.0389744 under the evaluator law. On TEST, **the own-law difference
also becomes negative, -0.0139610**, while the evaluator gives -0.0124190.
Environment-law mismatch alone cannot explain this particular failure.

The full E-occupancy performance-difference decomposition on TEST assigns
-0.0463161 to states where the fitted head violates its own C-based one-step
improvement target, and +0.0338972 to the other states. Their sum is the observed
-0.0124190. Three global identity residuals are at most 1.11e-16, the local
delta-head dot hidden decomposition residual is at most 2.43e-16, and the
replayed utilities equal the frozen run exactly.

This identifies a concrete action-selection failure of the projected affine
head on those exposed scenarios. It does not identify a unique universal
neuron, prove that all environment modeling is correct, establish a replacement
weight edit, or authorize reusing these scenarios as new confirmation data.
The complete 48-world records and selection/aggregation rules are retained in
value_edit/posthoc and its execution records. This is diagnosis of a negative
result, not a newly accepted model repair.

The prespecified illustrative-example rule chooses the worst E-minus-C TEST
world among the complete 32, rather than treating it as a representative random
sample. It is test_006, with difference -0.421749882. At its sole first-divergence
state (tick 5, no pending request, budget 3), C scores READ 0.23369728 above WAIT
0.21995356; E scores WAIT 0.24773133 above READ 0.24411275. The WAIT-minus-READ
margin changes from -0.01374372 to +0.00361858 solely through the stored head
edit, a +0.01736230 shift. Both the own-law one-step value (READ 0.55862085 versus
WAIT 0.08706211) and evaluator value (READ 0.56810825 versus WAIT 0.14635837)
strongly prefer the last available read. The edited head instead waits. All 49
coordinate contributions are retained; no individual coordinate is declared a
unique causal culprit. Tuning an additional patch to this exposed example
would require a new, independent confirmation design.

## 2. Native exact continuation certificate

The new native code is
[hepta-runtime PR #94](https://github.com/TrillionniumFoundation/hepta-runtime/pull/94),
source commit
[bc38fb8](https://github.com/TrillionniumFoundation/hepta-runtime/commit/bc38fb82244b946907886704b3c677bf00761cb9),
stacked on the earlier Bellman/journal PR #93. It adds the read-only MCP tool
weight_continuation_certificate. All nine published source/document blob hashes,
the commit parent, tree and remote branch ref were independently read back.

For a fixed affine continuation head C, radius R=0.5||C|| and supplied weak
ordering constraints A(C+delta)>=0, a nonnegative witness y gives v=A^T y and
d=-v^T C. Strict positive separation d>0 and d^2>R^2||v||^2 proves those
orderings cannot all be attained in that ball. Rust evaluates the comparison
with exact integer units for the actual binary64 encodings and separately
checks a conservative conditional F64 roundoff relaxation.

The tool binds original checkpoint bytes and all extracted coefficient bits,
validates bounded feature rows, supplied first-maximum actions, nonnegative
multipliers and consistent duplicate source rows. Requests, results, rows,
worker count and cooperative time are bounded. No new or upgraded dependency
was introduced: the already-locked num-bigint 0.5.1 is now direct.

The certificate is deliberately narrow. It does not authenticate caller-supplied
source digests, reexecute hidden/teacher semantics, prove actual hardware
rounding behavior, rule out valuable partial edits, or claim whole-network
impossibility. The old five-fit witnesses exclude one already-unsuccessful
full-cloning objective. The current value experiment tests a different,
potentially feasible partial-improvement objective and nevertheless failed its
own efficacy gate.

The source PR was initially created as a draft while local no-default gates,
actual five-fit MCP qualification and official CI were pending. Both feature
configurations have since passed their focused suites (87 passed, zero failed,
two existing ignored entries each) and strict all-target Clippy. The executed
native corpus has returned successful results for the five complete witnesses
and 21 controls. Final independent record review, source/binary identities and
CI qualification must be read from the submitted acceptance records; executor
success alone is not substituted for independent acceptance.

## 3. Actual Pocket4 inspection

At the 03:29:57 UTC status observation, the resident trainer service was active
but no training job was running. It reported 114 completed jobs, two failed,
zero admitted and zero pending evaluations. A candidate awaited original-source
forward admission because of freshness/continuity/quality holds. The completed
job count is not a count of cumulative optimizer epochs.

The actual six-tensor adapter contains 2,379 finite F32 parameters. Its hash is
94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0.
The complete 643,835,514-byte base checkpoint was hashed and only its six head
weight/bias tensors loaded. Source-extracted actual adapter classes executed
16 predetermined synthetic CPU inputs for each of three heads. The masks,
independent effective-matrix reference and in-memory parent restoration passed.

**The original fixed forward gate failed.** scorer.1 parent and child each
exceed the fixed reference tolerance on five coordinates of the prespecified
1,000-scale input. A second, identically thresholded diagnostic completed all
layers and retained that failure. Conservative F32 roundoff estimates contain
the errors, but they are not outward-rounded certificates or proof of a
candidate-independent cause. The other inputs/heads passed. The two complete
child attempts cost 4.058811 CPU seconds in total.

The effective matrices changed at 3,968 F32 coordinates. Their combined
relative L2 is 0.000331335034, whose denominator includes only the three inspected
head matrices. The encoder, original accelerator path and prospective trading
task were not executed. ACT/ESCALATE predicts frozen-parent answer correctness;
it is not a financial Call/Put pair or trade permission. Training-only CE/Brier
changes and calibration do not establish future value. No production weight,
service, guard setting or trading order was modified. Full scope and failed
receipts are in pocket4/README.md.

## 4. Updated primary-source literature

The MIT report and source identify GPT-6 Astra as the editor and demonstrate
target-weight editing without gradient training under specific search/data
budgets. The exact p50c update is a sparse direction-selective transformation
of layers 15 and 19, not merely a deleted projection. The source distinguishes
131,072 addressed positions from 130,188 actually changed BF16 entries.
The original loops/truncation and generation settings matter to attribution.

A pinned independent no-edit audit provides a stronger generation-configuration
baseline: 7.20%, 22.25% and 43.95% conservative whole-sample MATH-500 accuracy
under three settings, with different token limits and thinking/sampling modes.
The grader differs from MIT's. The edited-by-configuration factorial is
incomplete. We independently reaggregated all 6,000 supplied sample verdict
records, but did not regenerate their answers or independently regrade them.

Two November 3 preprints are included. The clinical small-network study reports
localized repairs, but also faster gradient repairs, false edits on healthy
networks, missed triggers and FP16 failure of large-magnitude edits. The image
restoration manuscript explicitly provides conjectures rather than new measured
improvements. REA's official program-inspection workflow informs interface
design; it is not evidence of arbitrary neural circuit understanding.

All immutable source identities, exact numerical tables, attribution and limits
are in literature/RESEARCH_UPDATE.md and SOURCES.json. No external author score
is labeled a model execution from this package.

## 5. Acceptance and open scope

Start with ARCHITECTURE_AND_ACCEPTANCE.md for the subsystem-to-checkpoint map,
proof derivation, native tool composition and cost requirements. In particular,
the audited finite task has a fixed-horizon sign label, not a first-passage
target; REPAIR changes a sensor, not the latent-state reset; and no independent
Call/Put tensor pair exists. Creating those mappings requires new task contracts,
not relabeling existing outputs.

The predecessor already rebuilt the published Qwen edit and qualified a short
F32 cached-vs-uncached execution. Its 36 short forwards are not a complete
MATH/GSM8K/IFEval benchmark, original BF16/vLLM reproduction, or fresh Astra
discovery. Those larger claims remain open. Likewise, the Trader-to-Neuron
semantic binding, fresh original-source evaluation, new independent training
fits, representation-level repair, global economic net value and general
autonomous neural optimization remain unqualified.

The package preserves executable code, original candidate and gate records,
failed attempts, independent checks and explicit limitations. A negative,
reproducible experiment and a validated mathematical guard can guide the next
research decision, but neither is reported as a successful live model repair.
