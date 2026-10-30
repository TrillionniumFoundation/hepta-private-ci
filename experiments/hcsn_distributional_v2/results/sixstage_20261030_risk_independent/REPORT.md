# Independent first-event risk audit

The column generator is killed by subtracting the complete marked reset inflow, including self-reset. Boundary-jump mass is removed before propagation. Existing refractory phases may release and then fire within the observation window. The survival operator is never normalized.

| Case | Dtype | Risk | Expected event count | Dense survival row L1 error |
|---|---|---:|---:|---:|
| phase_mixture | torch.float32 | 0.277411669 | 0.278923064 | 1.13461419e-14 |
| phase_mixture | torch.float64 | 0.277411675 | 0.278922984 | 1.16175651e-14 |
| repeated_event_window | torch.float32 | 0.964144469 | 4.81165266 | 3.90094207e-13 |
| repeated_event_window | torch.float64 | 0.964144481 | 4.8116507 | 3.90873098e-13 |
| self_reset | torch.float32 | 0.922672577 | 3.99439788 | 5.35816183e-12 |
| self_reset | torch.float64 | 0.922672577 | 3.99439365 | 5.36105535e-12 |
| zero_duration_shrink | torch.float32 | 0.476756684 | 0.476756752 | 0 |
| zero_duration_shrink | torch.float64 | 0.476756722 | 0.476756722 | 1.38777878e-16 |
| zero_duration_expand | torch.float32 | 0 | 0 | 0 |
| zero_duration_expand | torch.float64 | -1.3758312e-16 | 0 | 1.66533454e-16 |

The risk is an expectation of a first-event indicator. The ordinary regenerative event output is an expected repeat-event count and may exceed one. For an already active initial state, reset and refractory parameters do not influence the first event; their gradients must vanish. For existing refractory mass they may matter.

Poisson truncation bounds exclude floating-point roundoff. Values within a few epsilons of zero are retained rather than clipped, and reported explicitly. Risk plus surviving mass equals incoming mass; an input's final float32 casting error is not counted as an event.

Passed: True. Self CPU 0.782883s; wall 1.480137s. No GPU/energy measurement.
