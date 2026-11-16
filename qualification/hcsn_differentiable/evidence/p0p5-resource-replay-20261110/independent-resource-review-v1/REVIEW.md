# Independent resource-analysis review

**Verdict: passed for the frozen descriptive JSON analysis; no scientific or whole-training admission is granted.**

The reviewer independently reconstructed the tables from the authenticated CURVES JSON and did not import the producer or run any model. It checked 49 report identities, 2,969 confusion matrices with exact rational arithmetic, all 351 historical C1 clock intervals, 56 core/budget/view table rows and all 336 LR/seed member entries. All matched.

## Checked accounting and selection

- Both original-only and original-plus-separate-C1 views retain all 42 original candidates, both learning rates and all three seeds. C1 remains an adaptive additional stage.
- An unavailable observation remains null. A learning rate receives a mean only if all three seeds have an eligible evaluation; the selected common LR maximizes that mean, with the lower LR resolving ties.
- The target uses the first complete-epoch evaluation at or above 0.30. Before-training evaluations are excluded from target crossings; uncrossed seeds retain right censoring.
- Candidate costs include all six original fits and, in the combined view, the corresponding C1 phases. Per-budget charges are min(recorded chain outer wall, cutoff). Controller totals overlap these terms and must not be added again.
- C1 parent CPU gaps remain lower bounds, never a fabricated exact cumulative CPU or a basis for budget-cut inclusion. The RSS column is the maximum over whole attempts, not measured memory at first reaching quality.

## HCSN values independently reproduced

| Wall budget | Common LR | Three-seed mean D macro-F1 | Observed seeds at LR .001 / .003 |
|---|---:|---:|---:|
| 300 | None | None | [0, 0] |
| 900 | 0.003 | 0.025597903164526786 | [3, 3] |
| 1800 | 0.003 | 0.10864534152256881 | [3, 3] |
| final | 0.003 | 0.35758456450861853 | [3, 3] |

The HCSN final selected LR is 0.003, mean 0.35758456450861853 and sample SD 0.03182846299629498. All six HCSN original attempts remain budget-censored and have adequacy false. The all-six recorded process-wall sum is 86261.1154101817 s; maximum reported attempt RSS is 4074352640 bytes. These are descriptive results on reused D and not independent confirmation.

## Evidence and limits

The CURVES exporter was also read statically: it reads hash-pinned raw reports, exports original epoch metrics/clocks without resampling, preserves the C1 early/late wall samples and missing full-parent CPU, and rehashes inputs/sources. This review relies on that separately archived export chain; it does not re-open the native raw reports or checkpoints.

The measured review interval in RESULT `whole_script_wall_seconds` is **main-entry through JSON verification**, excluding standard-library imports and final RESULT serialization; despite that field name, it is not a process-spawn-to-exit wall measurement. `own_process_CPU_seconds` is the process cumulative sample; nested computation CPU is not additional. No model or optimizer work ran.

Main-entry verification interval: 0.351474842 s; computation CPU: 0.351480649 s; cumulative own CPU sample: 0.395616986 s.

No source, plan, original result, or shared repository file was modified.
