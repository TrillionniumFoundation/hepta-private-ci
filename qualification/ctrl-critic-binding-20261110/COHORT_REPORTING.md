# Complete-cohort reporting for CTRL replay

The predecessor at `012683fa36de20eae39f8501fde0b613d46e9fcf` retained unknown
context counts, but its primary mean and contrast fields still summarized only
the supported observations. Missing difficult contexts could therefore leave a
positive primary value even when the entire input cohort was not evaluable.

`ndu.real.metacontrol-study-report.v3` now returns a primary mean and bootstrap
interval only when every context in the pinned future input is evaluable and,
for a contrast, paired. Otherwise those fields are null. The original source
equal-weighted descriptive statistics remain under `observed_subset`, alongside
their context and source denominators. The scope is the pinned input cohort;
completeness relative to any external source registry is not asserted.

Three manufactured regressions reproduce the original acceptance behavior:

| Missingness | Original primary value | Corrected primary value |
| --- | ---: | --- |
| Difficult contexts lack an action; every source still represented | 0.18 | null |
| One source has unsupported policy predictions | 0.09 | null |
| One context is unpaired; both sources have other pairs | contrast 0.5 | null |

The new three tests fail on the exact predecessor. The repaired tests and seven
existing study tests pass: **10 executed, zero failures, zero skips**, Python
3.12.14. Original logs are retained in `COHORT_REPORTING_RED.log` and
`COHORT_REPORTING_GREEN.log`. The source-head workflow now requires the new
suite separately with a minimum of three executed tests. Ruff 0.15.13 formatting
and selected correctness lints pass; `just fmt` and `git diff --check` pass.

This changes reporting only. Policies, fit/calibration data, source weighting,
freeze order, future inputs and the underlying descriptive bootstrap are
unchanged. Synthetic reporting regressions add **zero independent real tasks**.
The native macro, prospective full-cost policy comparison and independent
implementation/effect labels still require their own evidence. The decision
remains **HOLD_NO_GO / NoUpdate**.
