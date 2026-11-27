# Train-only opportunity model and non-myopic investment

Research only / DENY_ALL. Additive continuation of PR #2319 at
`c679eebb9d30732bacae8ff921d7bb88154c94d9`. The original synthetic controls,
five-parameter Reader, archival news experiment and slope-stopping results are
not modified or reinterpreted. No production execution or model selection.

## New mechanism, not a guaranteed-return claim

Fit four actual 1540-parameter Head learning curves using only the original64
training records. Each hash-defined fold trains48, validates16, uses training48
normalization and records0/8/32/128 checkpoints. Four overlapping training folds
are not four independent tasks. The opportunity model gives these four curves
equal prior probability, with rate `(correct+1)/18`. This empirical model is not
an independently validated neural preference model. Transfer from48-row fits to
the final64-row fit, IID binomial observations, and the empirical prior's support
are assumptions, not proved learning laws or future-accuracy confidence bounds.

A zero-step Head is available before any online gradient. For each next block,
a finite observation tree compares stopping with continuation through ALL future
checkpoints, including future information and stopping. The 8/8/16 calibration
slices are disjoint and purchased only after real8/32/128 training. Unexecuted
checkpoint parameters and future observed labels are absent from the controller.
Binomial observations update the finite curve posterior. Terminal choices use the
posterior value of already available Heads, not an inaccessible future Head.

At any state define `rho_alpha(v)=(1-alpha)*E[v]+alpha*min_supported(v)`.
Stopping maximizes `H*rho_alpha(curve_accuracy_of_available_head)`. Continuing
uses `rho_alpha(child_values)-next_training_tariff-next_calibration_tariff`.
Neutral alpha is0, fixed alpha1/4; NDU-inspired alpha begins1/4 and after an
observed batch changes by `(1-2*batch_accuracy)/8`, clipped to[0,1/2]. Parent
alpha aggregates child values and child alpha is determined by child observations.
This is a registered finite recursive profile, NOT the continuous neural FBSDE.
The posterior spreads reflect the chosen empirical model, not certified uncertainty.

An independent rational implementation enumerates the same finite model. Source
uses float64 with a1e-12 stop-tie tolerance; measured choices/values must match the
rational reference at1e-9/1e-10 numeric tolerances inherited from the original
scalar audit. This establishes model-relative conformance, not real-world global
optimality. A delayed-gain construction retains a flat early curve followed by
improvement and tests that lookahead need not stop simply because the slope is0.
Such a construction demonstrates a mechanism, not new natural-task reasoning.

## Cost and information boundaries

The opportunity prior physically costs512 training updates and16 fold-scoring
calls. Every belief method's cold-start report adds that entire cost ONCE to its
own online result; hypothetical H does NOT amortize it. The formal script builds
one shared immutable prior and reports that actual physical acquisition once,
separately from attributing cold-start cost to each counterfactual method. Repeated
run/scenario counts are not independent customer reuse. Physical inference and
synchronous journal CPU are measured, not treated as free planning. Tests and the
scalar/rational auditor have separate measured work; audit full128 reference fits
are not executed by policies which stopped at0 or8.

All rows are the SAME archived64/32/32 AG News panel examined earlier. This changes
the control information protocol (disjoint sequential calibration and empirical
prior instead of repeated full32 calibration). Do NOT compare its numerical
values as an equal-information improvement over prior turns. Fixed8/fixed32/no-op
and a same-observation local-slope comparator are executed in this new protocol.
The slope starts a bounded pilot and is explicitly heuristic, not Bellman-optimal.
Cold-start and online-only costs are both reported. Tariffs are declared utility
units, not dollars or measured CPU prices. Local CPU is not full online Encoder/
Reader serving cost. No fresh Encoder or Reader call, no new source or future
calendar window, no production efficacy or NDU-specific superiority is assumed.

## Reproduce

Python3.13, NumPy2.3.5, one BLAS thread. `NEWS_ARCHIVE` must point to the original
ZIP SHA256 `195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`.
Use new output paths and retain failed attempts. From repository root:

```sh
N=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news
D=$N/opportunity
python "$N/material_news.py" --archive "$NEWS_ARCHIVE" --output /tmp/op-material
python "$D/study.py" train-input --material /tmp/op-material --output /tmp/op-train.npz
python "$D/study.py" fit-prior --training /tmp/op-train.npz --output /tmp/op-prior.json
python "$D/study.py" run --material /tmp/op-material --prior /tmp/op-prior.json --output /tmp/op-run
python "$D/review.py" --archive "$NEWS_ARCHIVE" --material /tmp/op-material --training /tmp/op-train.npz --prior /tmp/op-prior.json --run /tmp/op-run --output /tmp/op-audit.json
python -m unittest discover -s "$D" -p test_opportunity.py -v
python -O -m unittest discover -s "$D" -p test_opportunity.py -v
```

Predictor input has no holdout labels. Prior-fitting input has only original
training features/labels/IDs; source coordinator separates files. This is data-flow
separation, not OS sandboxing or independent signed custody. Source hashes provide
reproducibility, not independent observations. Same author/separate implementation
reviews every fold, actual checkpoint, decision, calibration slice, journal and
heldout probability. Train-fold leave-one-curve-out errors are diagnostic, not
independent calibration of future ROI. Negative outcomes remain publishable.

## Admissible computational pruning

After the first unpruned measured run, a performance-only bound was added without
changing data, fit, tariffs, priors, preferences or decision objectives. For next
fee q every continuation value is at most `H*max(all supported curve rates)-q`.
The recursive aggregator never exceeds its largest child and subsequent fees
are nonnegative. A branch whose bound does not exceed stop value is pruned. It
records an UPPER BOUND, not a fabricated evaluated continuation value. Exact
rational replay checks both admissibility and unchanged optimal choice; unpruned
records and source are retained. This optimizes the planner's compute, not NDU
learning ability. Repeated finite-tree regressions include a deliberately delayed
gain curve so pruning cannot discard a profitable later gain merely for a flat
recent slope. Float stop ties retain the declared1e-12 tolerance.
