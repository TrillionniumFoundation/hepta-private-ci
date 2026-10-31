# Independent interpretation of the Round6 continuation and finite execution domain

This receipt adds an interpretation to the frozen study. It changes no primary source, prepared artifact, policy, threshold, seed or model, and uses no confirmation data. It binds the exact prepared identity and relevant frozen source hashes in `INTERPRETATION.json`.

## What the continuation computes

The paid-wait value is the expectation of `(posterior_mean_after_sensor squared minus repair_cost)+`, minus wait cost. This is the value of an **unconstrained continuous repair** after one future sensor. The mixture quadrature integrates that stated mathematical quantity. It does not incorporate future codec distortion, the selected learned readout's future choices, or the finite parameter/action domains below.

The squared-error gain loss bound `1/(4*2^48) = 8.881784197001252e-16` covers nearest-Q24 rounding of the continuous optimum. It does not bound clipping/refusal, future transport/parameter errors, or learned-policy deviations. The wait computation therefore remains a shared planning approximation. It is not a Bellman optimality certificate for the implemented bounded runtime.

## Exact finite bounds in the frozen implementation

| Layer | Accepted domain |
| --- | --- |
| Conditional law | One or two components; finite positive weights summing to one within `1e-12`; strictly positive finite variances. |
| Shared codec/native law | Each **decoded** mean lies in `[-8,8]`; each decoded variance lies in `[2^-24,8]`. A source value can be refused if codec quantization moves its decoded coordinate outside this interval. |
| Typed native head | All four ordered inputs `(mean, variance, lower, upper)` are finite and have absolute value at most `8`. The raw head supports zero variance or variance at least `2^-24`; the study's shared law excludes zero variance. |
| Thresholds | `lower < upper` must hold before and after signed Q24 ties-to-even quantization. The study uses `(-sqrt(c), sqrt(c))`, which must also satisfy the absolute native bounds. |
| Codec state | Fixed component count per owner; accepted frame sequence `1..16`; nonfloat packed and accumulated integer magnitudes strictly less than `2^48`; finite, nonnegative, nondecreasing times. The study uses only one or two acquired observations. |
| Acquired public information | Exactly the six declared fields. Initial output and residuals are finite; costs and sensor variances are positive finite. Public observations have no additional general absolute bound. |
| Terminal broker action | Repair amount is finite in `[-8,8]`; stop requires amount zero; `initial + amount` must be finite. The broker refuses invalid values rather than silently clipping them. |

These bounds are conditions on accepted actual executions. They are not truncations of the Gaussian posterior distribution inside the continuation integral. In particular, a future Gaussian sensor has unbounded support and can mathematically induce a conditional state outside the implemented finite domain.

## A refusal remains a failure

Any actual codec, native or broker refusal must remain in the recorded failure/partial-execution evidence. It cannot be converted into a successful observation, silently clipped, dropped from confirmation, or repaired by replacing the seed or regenerating a sample. Complete registered inventory, real final deliveries, scoring and independent replay are required before a successful study-completion claim. A negative scientific gate is separately a valid experimental result.

## Storage scope

The migrated tmpfs workspace performs actual writes, image/text readbacks and fsync calls. These support the measured process-level execution and replay scope. They do not establish persistent-disk or host-reboot durability. Preparation has the separately recorded mixed storage history; all confirmation uses the declared migrated storage environment.
