# Scientific plots and the chat cost chart

`plot_results.py` is an independent publication tool outside the scientific
source freeze. It reads only explicitly supplied, completed JSON artifacts.
It does not import the experiment, load checkpoints or NPZ files, execute a
policy, select a model, recompute confidence intervals, or discover live runs.

## Final invocation

After `build_report.py` has produced the completed acceptance review, run:

```bash
python -B publication/plot_results.py render \
  --review PATH_TO_COMPLETED_REPORT/ACCEPTANCE_REVIEW.json \
  --online-index PATH_TO_COMPLETED_RUN/FULL_ONLINE_CONFIRMATION_INDEX.json \
  --output NEW_FIGURE_DIRECTORY
```

The alternative input is the existing completed online summary plus the exact
registered protocol:

```bash
python -B publication/plot_results.py render \
  --online-summary PATH_TO_COMPLETED_RUN/FULL_ONLINE_CONFIRMATION_SUMMARY.json \
  --protocol PATH_TO_COMPLETED_RUN/PROTOCOL.json \
  --online-index PATH_TO_COMPLETED_RUN/FULL_ONLINE_CONFIRMATION_INDEX.json \
  --output NEW_FIGURE_DIRECTORY
```

Both forms require a new output directory and produce:

- `forest_actual_utility.png` and `.svg`: two task panels, all 15 task/domain
  rows, with primary actual D−B and the difference against the ordinary family
  selected on validation. Each point and endpoint is copied from stored
  `metrics.utility.mean` and `metrics.utility.fit_t95`.
- `plot_data.json`: the exact 30 displayed estimates, their source JSON
  pointers, fit seeds and frozen validation-selected family identities.
- `chart_spec.json`: the complete `charts_widget_v2` argument object, including
  its required outer `content`. Pass this object as the widget arguments; do
  not move `chartType` or `data` outside `content` or stringify the content.
- `cost_aggregation.json`: all 96 selected cost rows and 12 task/family means.
- `PLOT_PROVENANCE.json`: input hashes, helper hash, output hashes and scope.

## Forest interpretation

The solid zero line is a descriptive equality reference. The dashed −0.02 line
is drawn **only across the five registered pressure rows in each task**:
`long_distractors`, `blank_retention`, `irregular_dt`, `clock4x`, and `query_swap`.
It is the registered tolerance for primary D−B **means**. It is not an interval
endpoint criterion, an acceptance rule for validation-selected-comparator
effects, or an IID/missing-modality threshold. Changing the reference or
pressure-domain list is refused.

The missing-modality domains form a visibly separate negative-control section.
Negative effects and intervals crossing zero remain visible. All supplied
paired-fit intervals are nominal t95 with eight fits and df 7, with no new
multiple-comparison correction. Plotting does not establish the broader
quality, cost, numerical, recovery or foundation-core acceptance claims.

## Cost calculation and accounting

Per-condition actor CPU is not available in the online summary; it comes from
`FULL_ONLINE_CONFIRMATION_INDEX.records[].execution.actor_cpu_seconds`.
Only IID, value-trained, value-executed rows are selected. The tool requires
every task × six families × eight registered seeds exactly once, all 512
objects in every row, and the same `data_sha256` for all IID rows within a task.
Where the report includes the online registration hash, the index must match.

For each fit, milliseconds per object are `actor_cpu_seconds * 1000 / 512`.
The chart displays the arithmetic mean of those eight fit values. These are
descriptive whole-cohort execution costs, not microbenchmark estimates or new
confidence intervals. The cohort is reused across fits; 8 × 512 executions do
not become 4,096 independent objects. Group/worker CPU is never added to nested
actor CPU. GPU time, physical energy/Joules and provider billing are absent.

## Artificial layout check

The selfcheck requires an explicitly artificial acceptance-review fixture:

```bash
python -B publication/plot_results.py selfcheck \
  --fixture-review publication/report_fixture_03/ACCEPTANCE_REVIEW.json \
  --output publication/plot_fixture_02
```

It writes a separate artificial input, manually varies interval widths to
exercise layout, and constructs synthetic full-cohort CPU records. Those
intervals are illustrative ranges, not measured confidence intervals. Both
the forest and chart specification prominently say **TEST FIXTURE**. The
production renderer copies the stored values without recomputing intervals.
An input `artificial_fixture: true` automatically forces these labels even
without `--test-fixture`.

The selfcheck verifies interval passthrough, all controls and pressure rows,
the 96-row/512-object cost denominator, ignoring huge worker and unrelated-row
sentinels, equivalent summary/review extraction, and rejection of duplicate or
missing rows, changed cohorts, short object counts, omitted domains and changed
pressure thresholds. `PLOT_SELFCHECK.json` preserves those mechanical checks.
Only artificial inputs were used to develop and inspect the candidate figures;
the root agent must run the completed real inputs and inspect those figures.
