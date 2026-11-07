# Independent training fits and prospective inference

This extension is stacked on `006e744fbb10a6ee393166eed2e5d1e91f2fab1f`.
It does not convert the disclosed bee-image probe into a real factorial trial.
Scientific admission and model adoption remain **HOLD / unauthorized**.

## Executable interface

`scripts/ndu_portfolio/replication.py` wraps the existing v1 factorial auditor.
A `ndu-replicated-factorial-v1` plan is pinned externally by its canonical JSON
SHA256. It fixes registration time, the common `design_digest`, independent
`fit_id` / `training_seed` pairs, bootstrap settings and prospective power inputs.
`design_digest(protocol)` excludes only joint fitted model/policy identities and observed
research usage; tasks, source groups, episode seeds, objectives, initial content,
capacity, budgets and opportunities stay fixed across fits. Frozen model weights
also remain identical across fits; independently fitted controller policies may vary.

Each fit record contains its own immutable execution identity, training receipt
digest, full v1 protocol, validation-only comparator lock, terminal episode rows
and complete training/search/evaluation attempt inventory. `seal_fit(record)`
binds the training receipt, comparator selection and all pre-evaluation attempts.
Save and externally pin this seal before confirmation. The Python module checks
consistency; an authenticated native owner must establish actual chronology and
immutability. Self-reported receipts and different SHA strings do not prove that
independent fits really occurred.

The roster cannot omit failed, unresolved or not-started fits. A not-started fit
needs no fabricated execution receipt and does not become measured zero cost.
Their observed costs and raw
partial rows remain bound in the records digest. Any incomplete fit prevents
complete-case inference for the whole study. Unknown costs stay unknown; known
lower bounds remain visible. Complete fits reconcile all profile research costs
against the attempt ledger, including failed attempts. Observed complete or partial
episodes require evaluation charges covering their known deployment-cost lower
bound; omitted evaluation receipts make the total unknown. Evaluation already belongs
to research expenditure: do not add the inference ledger to it again.

## Statistical estimand and limits

Episode randomness is averaged within each source group. All A/B/C/D contrasts,
joint/frozen differences, retention and validation-selected strong comparators
are computed within each paired fit/source cell. The analysis then resamples
training fits and source groups independently, with equal weight per axis.
It retains all 20 contrasts and applies the same Bonferroni family throughout.
Research-cost amortization uses each fit's own comparator and research charges.

This crossed percentile bootstrap is an approximate method, not exact finite
sample coverage. Its rationale is independent factor resampling in crossed
random-effects arrays; see [Owen and Eckles (2012)](https://doi.org/10.1214/12-AOAS547).
Few training fits, non-exchangeable sources, estimated variance uncertainty and
selective reporting require independent statistical review and calibration.
The software never authenticates the pilot, training fits or evaluator.

The prospective normal planning model uses
`Var(mean) = fit_variance/R + source_variance/G + interaction_variance/(R*G)`.
The supplied variance components must conservatively cover the complete contrast
family; `effect_above_margin` is the desired true distance above the decision
threshold, not the threshold itself. Inputs also specify desired power, alpha,
the fixed family size 20, a prior pilot digest/time, pilot source groups and pilot
fit execution IDs. Pilot sources cannot enter confirmation, and pilot executions
cannot be renamed as new training fits. Increasing episode seeds does not increase
R or G. An infeasible fit-variance floor returns `MORE_INDEPENDENT_FITS_REQUIRED`.
The existing 20-group floor remains a structural minimum, never a power analysis.
No real pilot estimates or study defaults are supplied by this extension.

## Run and review

```bash
PYTHONPATH=scripts python -m ndu_portfolio.replication \
  --plan plan.json --expected-plan-digest "$PLAN_DIGEST" \
  --records fit-records.json --output replicated-audit.json
PYTHONPATH=scripts python -m unittest -v ndu_portfolio.test_replication
```

Omit `--records` to inspect the prospective sample-size calculation only. The
tests' four-fit, 10,240-row example is explicitly synthetic, fully reconstructible
from `replicated_example()` and its fixed seeds. It exercises evidence accounting
and arithmetic; it supplies no real five-family task, training-method efficacy,
retention, native owner, independent evaluator or physical-cost qualification.

At this stage even favorable complete arithmetic returns `Inconclusive`, with
`native_receipt_authentication` and `independent_fit_authentication` both
`NOT_IMPLEMENTED`. It cannot create a learning `NoUpdate`, authorize an update,
or bypass V5 no-op rejection or positive-gain requirements.
