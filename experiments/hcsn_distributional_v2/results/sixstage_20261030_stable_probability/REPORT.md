# Bounded regenerative probability correction

This new profile retains the failed uncorrected diagnostic and frozen sources. It validates inputs and operator semantics, rejects excessive defects and any negatives, then divides by the observed mass in float64 with a differentiable denominator. It never applies to killed/no-event transitions.

| Case | Dtype | Maximum mass error after correction | Final state L1 error | Event error (double sum) | Event error (dtype sum) |
|---|---|---:|---:|---:|---:|
| central | float32 | 2.98023224e-08 | 3.68683786e-07 | 0.000402693215 | 0.00739055029 |
| central | float64 | 1.11022302e-16 | 7.50094431e-15 | 1.98389216e-09 | 1.98389216e-09 |
| negative_drift | float32 | 3.24107532e-08 | 3.85914663e-07 | 4.1118179e-07 | 8.44023961e-07 |
| negative_drift | float64 | 1.11022302e-16 | 2.38824246e-13 | 1.48320245e-12 | 1.48320245e-12 |
| fast_cycle | float32 | 3.16649675e-08 | 8.81127223e-08 | 0.000164303404 | 0.0246012913 |
| fast_cycle | float64 | 0 | 1.44664315e-12 | 1.04009814e-08 | 1.04009814e-08 |
| rate_domain_corner | float32 | 2.88709998e-08 | 1.9728799e-07 | 0.00111299293 | 0.0157780023 |
| rate_domain_corner | float64 | 1.11022302e-16 | 7.27333124e-13 | 1.2995315e-08 | 1.2995315e-08 |

The actual per-step and cumulative corrections are saved, as are raw mass defects. The helper restores the unit-mass contract, but does not prove exact finite-grid dynamics or prevent separate error in float32 accumulation of thousands of expected event counts. Double accumulation is tested explicitly; per-step event vectors retain their original semantics.

The moving-boundary test includes zero-duration observation jumps and 128 regenerative steps. Eight parameters are differentiated through the full recurrence and compared with central finite differences of independently assembled dense generators, physical-overlap maps and value solves.

Passed: True. Self CPU: 14.766404s; wall: 35.499185s. No GPU/energy measurement.
