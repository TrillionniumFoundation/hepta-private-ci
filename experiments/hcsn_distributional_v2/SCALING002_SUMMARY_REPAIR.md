# SCALING002 summary reconstruction

All30 registered worker processes completed successfully with the original
frozen benchmark. The suite then failed in `scaling_eval.summary_report` because
it divided by a T16 forward CPU median recorded as0. The original
`results/scaling002/SUITE_EXECUTION.json` remains returncode1 with no
`COMPLETE.json`, and its full99.448615 CPU seconds plus separate supervisor
0.260789747 seconds remain charged.

`scaling_summary_repair.py` independently verifies those existing30 workers and
writes only to `results/scaling002_summary_repair001`. It imports no Torch or
NumPy, reruns no timing or model, and changes no original file. The original
protocol/source/admission identities, constructor counts, synthetic input and
initial-weight archive hashes, all eight raw measurement records per worker,
three-repetition medians, four Adam steps and successful optimizer changes are
checked. `INPUT_BINDINGS.json` binds every original file by its repository-relative
path, byte count and SHA-256.

The new `COMPLETE.json` uses schema
`hcsn-v2-scaling-summary-repair-complete.v1`; it certifies30 original successful
cases while explicitly retaining `original_suite_failed: true`,
`original_case_timings_modified: false`, and `new_timing_or_inference: false`.
Its `original_suite` object binds the failed original receipt and returncode1.
The separate measured-support receipt in
`results/scaling002_summary_repair001_execution/EXECUTION.json` has returncode0.
The reconstruction cost is0.233307 CPU seconds for the complete child plus
0.037437467 seconds for its separate supervisor. The inner repair self clock is
nested and must not be added again.

## Zero CPU observations and presentation

There are11 forward CPU medians and one optimizer CPU median recorded as0.
The latter is the Transformer at T32, width32, depth1. All corresponding wall
medians are positive. These are **CPU clock unresolved** observations; they do
not establish free computation or an infinite speed advantage. The raw zero
values remain unchanged and are listed individually in `zero_timing_medians`.

The reconstructed `SUMMARY.json.rows` preserves the original table interface.
Ratios with a zero T16 denominator are `null`; each reason appears in
`undefined_ratio_reasons`. No epsilon or replacement measurement is inserted.
The Transformer T32 optimizer has a zero numerator with a positive denominator;
its arithmetic observed ratio is0 in the preserved-value reconstruction, but
the `zero_timing_medians` flag means that it must also be presented as CPU clock
unresolved in any comparative interpretation. The same-run wall medians can be
shown separately with their own units and scope.

Completion of this reconstruction certifies evidence coverage, not successful
exit of the original suite. The panel remains random-weight CPU implementation
evidence at batch1, up to about105k parameters, with no new content-quality,
GPU, energy, equal-quality or foundation-model claim.
