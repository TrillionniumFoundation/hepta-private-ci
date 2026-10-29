# Round 5: equal-information candidate-range study

This is a fresh study on pinned Round 1–4 scientific code. It does not recreate
the missing original Round 4 execution artifacts, alter their acceptance rules,
or promote a production owner. It tests a development-selection mechanism, not
a new neural function class, first-passage cell, or downstream utility claim.

## Hypothesis and matched inputs

Round 4's zero-context mixture selector uses 21 priors `s*pi_fit`, where
`s=0,.05,...,1` and `pi_fit` is fitted on balanced retained/current training
queries. Its largest candidate is the fitted prior. A full-range selector uses
21 priors `0,.05,...,1` on exactly the same fitted component pair. This can expose
more adaptive candidates without giving the model additional observations,
labels, context histories, parameters, or development candidates.

The grids need not be nested: enlarging the range changes the spacing. A full
grid can omit a useful legacy candidate. No monotonic improvement is assumed.
The primary hypothesis concerns the complete candidate-range change, including
its resolution tradeoff; it is not an isolated upper-endpoint intervention.

Every prediction receives the same query's six scheduled noisy sensor slots,
physical times, masks and sensor variances. No extra public histories are
acquired. Model features exclude future targets, hidden regime labels, window
indices and query identifiers. The inherited public-history extraction and
conditional-law formulas are reused unchanged. Training uses the inherited
four correlated acquisition stages; these do not multiply the independent
trajectory count. No selected-action information is invented at prediction time.

| Arm | Fitting and development selection |
| --- | --- |
| `frozen` | Fresh old-environment anchor; no adaptation |
| `replay_legacy` | Anchor to balanced replay Gaussian, 21 physical-parameter interpolation candidates |
| `gaussian_full_range` | Anchor to current-only online Gaussian, same 21 interpolation strengths |
| `mixture_legacy` | Exact mixture with fitted prior, then 21 `s*pi_fit` candidates |
| `mixture_full_range` | Same exact component pair and fitted-prior preparation, then 21 full-range priors |
| `moment_legacy` | Gaussian projection fitted on its own prior objective, then 21 `s*pi_fit` candidates |
| `moment_full_range` | Same projected component pair and fitted-prior preparation, then 21 full-range priors |
| `same_weight_moment_full` | Project the selected exact full-range mixture at exactly its selected weight |

The exact/projected family comparisons each share their fitted prior and
component parameters. The full-range heads retain the prior-fit receipt even
though their grid does not depend on its value. The Gaussian comparison changes
the interpolation endpoint as explicitly declared; it is a secondary comparison
and does not isolate only the scalar-prior range. Architectures, arithmetic cost
and parameter counts across families are not identical. All heads use the same
training/development labels and query information. Six selectors each evaluate
21 candidates per window; frozen and same-weight projection add no selections.

The unchanged anchor is the first candidate. All six selectors retain candidates
whose old-development mean density-NLL increase plus `1.645 * paired SE` is at
most `.02`, then choose the smallest new-development density NLL, resolving ties
by candidate index. This guard is a finite-sample selection heuristic, not a
simultaneous, pointwise or population guarantee.

## Fresh data, identity and freeze

Registered training seeds are `2131,2377,2539,2791,3011`. Each seed fits a fresh
anchor on 512 trajectories and retains its first 256 as replay data. Twelve
windows alternate `gaussian` and `drift_shift`. Each window acquires 256 current
training trajectories and 256 old plus 256 new development trajectories. The
inherited old and shifted drift values are `.12` and `.32`.

Generator seeds are SHA256-derived 53-bit integers from the complete tuple
`namespace|phase|training_seed|window|role`. The registered namespace is
`hepta.aen.r5.selection.confirmation-study.v1`; all planned identities are listed
and checked for collisions. Deriving seed identifiers does not generate data.
The separate `hepta.aen.r5.selection.development-smoke.v1` profile has one seed,
two windows, 64 anchor rows and 32 rows in each subsequent collection. Its API
refuses confirmation identities and it cannot be frozen for confirmation.

The full preparation has 48,640 unique labelled query trajectories, 245 optimizer
fits, 360 selectors and 7,560 candidate evaluations. Retained old training rows
are reused, not counted anew. Initial/final parameters, objective traces,
optimizer statuses, candidate losses, selected indices, raw arrays and dataset
digests are retained. Checkpoints are reopened and their forecasts compared
exactly. No optimizer failure qualifies for confirmation. Every interrupted or
failed invocation keeps its partial directory and a failure receipt when the
process can write one; never overwrite an attempt directory to hide a failure.

The Round 4 freeze itself is pinned by SHA256
`e7fd9c474e0c4a0ad56ad910a643ab84970da430600e6f8caccae2849c824c2d`.
Its 102 scientific source identities are checked, and the Round 5 selection
code, tests, package initializer and this contract are bound separately.
Python implementation/version/executable, NumPy and SciPy versions and build
configuration, platform/machine and declared numeric thread settings are recorded.
Preparation, freeze, confirmation and recovery summary reject any difference
in this numerical-environment identity; dependency changes require a new attempt.
Preparation must complete before `freeze` is invoked with the explicitly
reviewed registration digest. Confirmation verifies source hashes, every
prepared artifact, the exact roster, the registration and the freeze before
constructing any confirmation arrays. This is an ordinary execution/dataflow
contract, not protection against a hostile process rewriting all evidence.
Local identity freeze does not assert remote publication or durable storage;
those require their own actual receipts.

An accepted recovery summary independently rechecks that same freeze, sources,
environment and every prepared model, then verifies the complete raw/score file
inventory, scope records, checkpoint hashes, dataset digests, seed/row identities,
score shapes, labels/targets and within-query averaging. Hashing score files alone
does not qualify a detached or incomplete result for acceptance.

## Confirmation and statistical endpoints

Confirmation uses 256 fresh old queries per seed reused across all windows,
plus 256 fresh new queries per seed/window: 16,640 independent query
trajectories. Three scored horizons `.5,1,2` remain correlated within each query.
There are no context paths. Every arm is evaluated on the same rows. Repeated
old probes and eight arm executions do not increase the independent sample size.

The two primary contrasts are full-range minus legacy density NLL for the exact
mixture and for the fitted Gaussian moment family, averaged over the six fixed
drift windows. Negative values favor the full-range selector. Each receives a
97.5% two-sided hierarchical bootstrap interval, a Bonferroni family of two;
training-seed clusters and complete queries within each window are resampled.
There are five independent training-seed clusters, with independent query
trajectories conditional on each fitted model. With only five clusters, interval
and family coverage are nominal/approximate, not an exact finite-sample guarantee.
The bootstrap has 4,000 replicates. The primary range-benefit indicator requires
the upper endpoint below zero and is sign evidence only; no minimum meaningful
range-effect margin is claimed. Expanded-profile acceptance is reported separately.

Per-arm profile gates require worst cross-seed-mean old density-NLL increase at
most `.02`, final-new mean no worse than the anchor, final-new improvement at
least `.005`, improvement for every training seed, a descriptive 95% final-new
upper endpoint below zero, drift classwise ten-bin ECE at most `.04` and 95%
interval coverage in `[.92,.98]`. Their conjunction is an empirical gate, not
a familywise confidence statement. Report every worst individual seed/window
degradation independently. Strong-Gaussian, same-weight shape and cross-family
comparisons have descriptive 95% intervals; they add no new superiority gates.

Density, event probability and interval scores remain terminal-law quantities.
Moment projection does not inherit an exact marginalized diffusion semigroup.
No packet, Q24, native execution, action-value, energy or latency benefit is
inferred from this prediction study. Complete component-fit calls, prior fits,
selectors and per-arm old/new scoring calls record wall and parent CPU time.
Preparation and confirmation-generation/scoring have aggregate timers; the outer
summary timer covers verification, metrics and all bootstrap calculations and
excludes its final JSON write. Invocation-wrapper costs include interpreter
startup when that wrapper is used. Shared fits are counted once and nested
timings are not additive. No financial cost or native energy is inferred.
