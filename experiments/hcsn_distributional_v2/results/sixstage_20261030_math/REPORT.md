# Independent long-horizon regenerative audit

This new diagnostic preserves the frozen kernel and content protocols. It compares the finite model with independent renewal/occupation equations and dense matrix exponentials. It does not measure content quality.

| Case | Dtype | First original mass-contract violation | Final mass error | Final state L1 error | Final event error |
|---|---|---:|---:|---:|---:|
| central | torch.float32 | 88 | 0.00144743919 | 0.00144742802 | 0.333250083 |
| central | torch.float64 | 1684 | 2.43749465e-12 | 2.44484294e-12 | 2.54254928e-09 |
| negative_drift | torch.float32 | 148 | 0.000884413719 | 0.000884421054 | 0.000151204418 |
| negative_drift | torch.float64 | None | 0 | 2.39087206e-13 | 1.48314694e-12 |
| fast_cycle | torch.float32 | 858 | 7.17043877e-05 | 7.17407116e-05 | 0.119252664 |
| fast_cycle | torch.float64 | 2528 | 1.62003744e-12 | 1.73158363e-13 | 1.30021363e-08 |
| rate_domain_corner | torch.float32 | 308 | 0.000406622887 | 0.000406604263 | 0.579702629 |
| rate_domain_corner | torch.float64 | None | 3.55271368e-15 | 7.23988577e-13 | 1.29948603e-08 |

Renewal algebra passed: True. Its comparison separately checks the inverse mean regenerative-cycle time, the stationary marked-event rate, and per-phase refractory occupation.

Prepared recurrent updates do not call the checked propagator at each token. The reported violation is of the existing checked API's unit-mass tolerance, not a newly selected success threshold. Snapshots retain whether that API accepts the recurrent state, and every step is saved in the NPZ traces.

The count-error columns include floating-point accumulation. RESULTS.json also reports double accumulation of the same per-step increments, separating part of that error. Analytic Poisson-tail bounds exclude these roundoff effects.

Self CPU 2.151099s; wall 6.662979s; peak RSS 296396 KiB. No GPU or energy measurement.
