# P0/P2: exact-knot piecewise-linear barrier slope admission

**DRAFT / RESEARCH ONLY / DENY_ALL.** `all_blockers_closed=false`; `production_activation_allowed=false`.

## Precise problem

The moving-boundary first-hit envelope requires a **proved global derivative bound** during the observation interval. Sampled per-token barriers do not prove such a bound for an arbitrary differentiable neural function between tokens. Using sample-estimated slopes as if globally valid may return false probability bounds.

This strictly additive reference admits one explicitly declared class: a **continuous piecewise-linear** barrier constructed by linear interpolation of 2–4096 finite binary64 `(time, barrier)` knots, starting at `time=0`, strictly increasing in time, ending at `T>0`. For all segments, exact rational slopes of the *stored binary64 knots* are computed using `Fraction.from_float`. Their extrema are independently rounded outward with `math.nextafter`. If no finite binary64 enclosure exists, the oracle raises `ArithmeticError`; malformed knots raise `ValueError`.

For a segment slope `s_i=(b_{i+1}-b_i)/(t_{i+1}-t_i)`, the exact bounds `c_lo<=s_i<=c_hi` imply for every `t in [0,T]`:

    b(0)+c_lo*t <= b(t) <= b(0)+c_hi*t.

The curve need not be differentiable *at* the knots; the pathwise inequality holds by absolute continuity. With frozen arithmetic Brownian drift and volatility, its first lower-barrier hitting time is sandwiched pathwise between those for the two straight-line barriers. The first-hit CDF and nonnegative discounted first-hit weights are therefore ordered. The existing independent `moving_boundary_enclosure.py` implements those outer analytical values; this patch establishes a source-checkable **slope precondition** rather than accepting an unsupported caller claim.

## Explicit non-claims

- This does **not** certify a learned nonlinear neural boundary between supplied samples, nor imply that a moving-boundary HCSN itself uses linear interpolation.
- Outward binary64 slope **parameters** are exactly enclosed, but the `mpmath` probabilities are approximations, not directed-rounding interval-certified outputs. No complete HX coupled obstacle/fixed-point, all-domain gradient, fp32/fp16/GPU guarantee, or production neuron certification.
- It does not validate stochastic/state-dependent boundary paths, changing diffusion, correlated cells, or recurrent dependence. It does not establish P1 mechanism superiority, P2 memory, P3 paired four-modal quality, P4 native GPU/energy, or P5 matched scaling.
- Standalone evidence must not be attributed to existing HCSN training checkpoints. Historical negative HCSN results remain binding.

## Reproduction

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_piecewise_boundary_certificate

Gate cases: exact linear parity; nonmonotone segment slopes; rational outward rounding; one-ULP time knots; subnormal slope; overflowing slope denial; malformed/frozen-physics rejection; exact-rational pathwise comparison on 303 segment points; initial absorbed state; knot-count cap. Test results must be recorded for the *exact pushed files* before asserting execution success.
