# Final closure with an independent scaling summary repair

`archive_closure_final.py` is the final archive entry point. It subclasses the
previously validated and actually normalized `archive_closure.py`, whose SHA-256
remains `a73cdcadf0164a83c1355cce17bec9e38e0991e9155b9a4c52c243cb8e4d0209`.
The original LIF normalization, its source bindings, and the base auditor are
unchanged. Main, LIF, source, archive-part, selection, restore, and whole-run
inventory checks are inherited.

The final consumer replaces the scaling completion check for one explicit
engineering failure. All 30 original SCALING002 workers exited successfully,
but their enclosing suite exited with code 1 while the frozen summarizer
divided by an observed zero timing median. The original suite receipt and log
remain failed and unchanged. No original `SUMMARY.json`, `REPORT.md`, or
`COMPLETE.json` is inserted into `results/scaling002/`.

The independent read-only repair is at
`results/scaling002_summary_repair001/`, with its complete-process measurement
at `results/scaling002_summary_repair001_execution/`. Its completion is a
different schema: `hcsn-v2-scaling-summary-repair-complete.v1`. The final auditor
requires the original suite exit 1 and the repair's outer exit 0, the exact
same 30 original worker receipts, the original 71-source registration, and an
input-binding map covering every original scaling file. It independently
checks all raw operation timers, their three-repeat medians, preserved actual
parameter counts, the zero-timing inventory, and every reported ratio.

An original zero timer difference stays zero. A ratio whose T16 denominator is
zero must be JSON `null` with an explicit reason. It cannot be replaced by an
epsilon, another clock, or a newly measured value. These observations do not
mean that computation was free. This remains a descriptive CPU implementation
diagnostic with no equal-quality, energy, GPU, foundation-model, or asymptotic
claim.

The closure also requires the complete repair and enclosing-measurement file
trees in the archive union. Its `scaling_case_coverage` records both execution
identities, `original_suite_succeeded: false`,
`summary_repair_succeeded: true`, unchanged original timings, and the counts of
zero medians and undefined ratios. The preserved original main strict 175/1
failure and separate producer-exact 176/0 supplement remain explicit under
`main_analysis_admission`.

After all final bundles are ready, run this module under the existing
`measured_support` wrapper:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_distributional_v2.archive_closure_final --output experiments/hcsn_distributional_v2/results/archive_closure001
```

The final completion artifact retains schema `hcsn-v2-archive-closure.v1` and
is published exclusively and atomically at `artifacts/ARCHIVE_COMPLETION.json`.
Its own receipt and outer measurement remain outside the sealed payloads.
The final consumer and this document are published directly in Git; their
validation source snapshots remain in the auxiliary evidence bundle.

The pre-change planner and actual normalized base are preserved under
`results/scaling_summary_consumer005/before/`. The corresponding narrow tests
exercise real completed metadata and reject a relabeled suite success,
fabricated zero-denominator ratios, altered ratios, and incomplete panels.
They do not rerun training, inference, timing, or archive packing.
