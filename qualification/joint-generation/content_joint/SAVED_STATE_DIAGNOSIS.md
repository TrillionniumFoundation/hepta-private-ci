# Read-only diagnosis of f5f99; no qualification is reopened

The original result remains failed: coupling and native N−A failed their fixed
TRAIN mean criteria, and S/H/N exceeded the promised10-second full scope. Positive
A−H numbers are not upgraded. This separately authorized independent research
review reads retained tensors/receipts only. There is no neural/decoder forward,
optimizer update, sampling, new image or formal evaluation. Its main process
used2.328523 CPU seconds before its final descriptor; it does not append to or
subtract from the old method ledger. Source/input hashes and all286 saved-state
curve rows are retained under
[`content-joint-readonly-diagnostics-v1-20261023`](../runs/content-joint-readonly-diagnostics-v1-20261023).

## N−A is not explained by step count or clipping alone

Native A updates are511/511/511; N updates490/511/511 for seeds11/23/47. The
final768-row N−A CE differences are−.000306389/−.001616886/+.001153570. Seed23
is negative despite equal511 clocks, whereas seed47 is positive with the same
equal clocks. All24 original models have zero clipped steps. A missing21 updates
for N11 can affect that seed, but cannot explain the complete pattern. There is
no saved A490 or N511 neural state for seed11; none is reconstructed or trained.

The following use the exact same saved128 fit and128 inner rows, eight complete
physical sources each, at the exact same post-update checkpoint. CE here means
the original rho1.5 reward certainty equivalent, not cross entropy. Positive is
better. Every available checkpoint is retained; no row is selected as a winner.

| Seed | Update | N−A fit CE | N−A inner CE | N−A inner joint success |
|---|---:|---:|---:|---:|
| 11 | 1 | −.000183434 | −.003972670 | −.003413049 |
| 11 | 128 | +.012636036 | +.071252006 | +.068202334 |
| 11 | 256 | −.000066692 | +.006367036 | +.004274011 |
| 23 | 1 | −.000027345 | −.002004690 | −.001534286 |
| 23 | 128 | +.000056926 | −.012282481 | −.005274750 |
| 23 | 256 | +.001501816 | −.007355817 | −.003702544 |
| 47 | 1 | −.000710617 | +.000439521 | +.000442376 |
| 47 | 128 | +.002226914 | +.005466445 | +.004335792 |
| 47 | 256 | +.000776703 | −.005514921 | −.004522618 |

Seed23 has better N fit but worse inner reward CE at128/256; seed47 shows that
split at256 but not128. Seed11 shows a different direction, including a large
temporary A deterioration at128. This supports a **local, seed-dependent
fit/inner separation**, not a universal representation or capacity explanation.
The128-row inner cohort is only eight physical sources; its values are not the
final768-row primary mean. The two cohorts are never spliced into one curve.

## Both own training objectives improve; trajectories are not monotone

The retained arrays satisfy the actual loss equation `L=.2*C−U` to1e−12.
For A, U is expected decoded R; for N, U is the categorical entropic value at
rho1.5. Their absolute loss values cannot be compared as one common loss.
Matched64-step training-prefix windows decrease strongly in each objective:

| Seed | A own loss, updates1–64 → last common window | N own loss, same windows |
|---|---|---|
| 11 | −.988930704 → −.999739732 (449–490) | −.983778301 → −.999712728 |
| 23 | −.985207952 → −.999634505 (449–511) | −.981161080 → −.999522022 |
| 47 | −.986927330 → −.999558714 (449–511) | −.982560591 → −.999547661 |

These are recorded mini-batch windows, not evaluations on a constant cohort.
The frozen RNG gives matched A/N batch prefixes; captured indices agree at
updates1/128/256. Individual unrecorded batch indices are not resampled here.

The saved fixed-cohort probabilities allow both original objectives to be
computed algebraically without a model forward. For N23, its fixed-fit
`L_N` improves from−.994078 at1 to−.997587 at128 and−.999137 at256. On the same
fixed inner cohort it moves−.938668 →−.930146 →−.925908: worse despite better fit.
A23 also has nonmonotone inner values. Thus "the original objective did not
optimize at all" is unsupported; stable inner optimization is also unsupported.
All own/cross-objective values and entropy are in `all_saved_curves.csv`.

## A risk-gradient scale difference is observable, but it is not a cause proof

Native A/N have identical initial parameters and the same first batch. From
the saved pre-update probabilities and the fixed original R diagonal, this
review derives the exact logit components:

    g_C=.2*(s−onehot)/n
    g_Autility=−s*(Rdiag−E_s Rdiag)/n
    g_Nutility=(tilted−s)/(1.5*n)

These are newly derived mathematical diagnostics, not claimed original logit
gradient captures. At the common first state, N/A total-logit norm ratios are
1.5466/1.3791/1.8051, with cosines.9940/.9885/.9996. N utility norm alone is
1.6837/1.4880/1.9868 times A. Across every saved1/128/256 batch/state examined,
anchor and utility logit directions are aligned; the lowest N cosine is.96343.
This is evidence against an observed early logit-level sign conflict, not proof
about all iterations or parameter-space component gradients.

At first step, recorded encoder-gradient N/A norm ratios are1.511/1.390/1.796.
Actual first encoder-displacement norms are nearly equal (~.804), while their
cosines are.9705/.9461/.9797 and gradient-sign disagreement fractions are
1.50%/2.71%/1.05%. The coordinatewise Adam update therefore does not turn a
larger norm into a proportionally larger step; there are still real direction
differences. The validated Adam implementation and zero clipping do not identify
an optimizer bug. Intermediate Adam moments and the pre-update batch hidden/
Jacobian were not captured, so encoder CE-versus-utility conflict cannot be
recovered retrospectively.

N's scale difference is not a single global multiplier: in the initial saved
batches, requests with target probability>=.99 have mean N/A utility norm ratios
~2.16, versus~1.42–1.53 for the populated.5–.9 bins. Those fixed diagnostic bins
describe risk reweighting at the same state, not a fitted controller or an
alternative loss. Its causal contribution to final N−A requires a new prospective
experiment; it cannot be inferred from these correlations alone.

## Native did not start behind log2; training reversed its relative advantage

At zero updates, native is the independent base law conditioned on agreement.
Its complete768-row CE advantage over the base's fixed log2 is
+.005581545/+.005868973/+.006555276 for seeds11/23/47; mean+.006001931. Its joint
success is also higher in all three. Native joint entropy is lower in every
seed (.06878/.08002/.07200 nats versus log2 joint entropy.08772/.09888/.09152).
That establishes a sharper initial law and an initial advantage under the
actual scorer; it does not establish that sharpening caused later harm.

| Family | Initial native−log2 CE | Final native−log2 CE | Change in relative gap |
|---|---:|---:|---:|
| S | +.006001931 | −.006513516 | −.012515447 |
| H | +.006001931 | −.007760141 | −.013762072 |
| A | +.006001931 | −.002454187 | −.008456118 |
| N | +.006001931 | −.005983624 | −.011985556 |

Both architectures improve in absolute quality, but the trained independent
heads plus fixed repair improve more. This is a training-path/conditional-law
comparison in the same portfolio, with different final update counts. Native
has more updates in almost every paired slot, so the aggregate cannot be
explained simply as native receiving fewer steps. Equal-update fixed-row
comparisons, every single-recipe-only extra checkpoint and every final state
are retained; A independent23 has no256 state and none is substituted.

All native families share the same initialization, so sharpening is not an A/N
initial-condition difference. There is no alternate-initialization trajectory,
temperature intervention, head-capacity experiment or hidden representation
metric here. A changed initialization, different supervision weighting or larger
head remains a hypothesis, not a mechanism established by this review.

## The resource evidence supports a prospective boundary change

Recorded CPU permits exact training/initialization totals and an aggregate
export/observation/service residual, not separate timing for every tail phase:

| Family | Training including checkpoints | Initialization | Other core tail | Core tail incl. init, scheduler and outer summary |
|---|---:|---:|---:|---:|
| S | 3.246911253 | .005525592 | .906298713 | 1.120075114 |
| H | 3.366470257 | .005274185 | .870037051 | 1.083562045 |
| A | 3.257330901 | .006255038 | .863264259 | 1.077770106 |
| N | 3.393459501 | .006700714 | .865891751 | 1.080843274 |

Full method-tail units after the shared preparation and recorded training range
149.196M–149.255M. Checkpoint work is separately110.401M–123.715M units but its
CPU is inside training and was not separately timed. Compiler CPU is separately
known: original.382784261, native.190958011; those are subsets of common costs,
not additional sums. New common preparation1.437362976 has operator substage
receipts, but no finer CPU split. No missing phase timing is invented.

The old promised independent output audit plus report adds exactly1.156 CPU
seconds in the retained numeric receipts. The worst old complete tail is thus
2.276075114, beyond the old2-second reserve. Those charges and all old failures
remain. The new boundary proposal below uses a2.5-second method tail reserve
and.5-second untouched global guard, with500M operator units; it offers either
less training under10 seconds or a separate, uniform11-second design. It is not
implemented in or applied retroactively to the old runner.

See [prospective boundary and fairness rules](../content_budget/BOUNDARY_DRAFT.md),
[all retained derived evidence](../runs/content-joint-readonly-diagnostics-v1-20261023/diagnosis.json)
and [runnable allocation result](../runs/content-joint-readonly-diagnostics-v1-20261023/proposed-boundary.json).
