# P0 float32 barrier quantization: fail-closed research oracle

**DRAFT / RESEARCH / DENY_ALL**. This source-only composition uses #4396 at exact base `ec70cf1fb8b6817bae038ab923f7bd9afe5cfd52`, preserving its reflection intermediate guards, and transplants the guard source and tests byte-for-byte from #4398 `993da151fe55b450bf883c7f2cfd7850eca1db9f`. This document is revised to distinguish historical evidence from the unexecuted combination. The original #4385 slice stacked on #4384 `a050736f9a95b280ab3f95433fee3295eb9aad31`; that is historical provenance, not the current composition base. It does not change existing training, production Rust, GPU kernels, authority, deployment, or frozen external benchmark evidence.

## Scope

The old independent test in #4382 deliberately exposes a float32 witness: for `b=64.6251766753` and `asset=b*(1+1e-9)`, `asset>b` in f64, but `np.float32(asset)==np.float32(b)`. Therefore the original sign cannot be reconstructed from the two fp32 numbers alone.

`fp32_cell(v)` builds an outward-rounded real interval from the predecessor and successor of the IEEE-754 binary32 encoding, assuming round-to-nearest, ties-to-even, without underflow/overflow. `classify_fp32_barrier` returns ABOVE or BELOW **only if every pair of real preimages is ordered the same way**. Adjacent ULP bins conservatively overlap because ties are included. Equal or overlapping encodings yield AMBIGUOUS, never a confident event decision.

`guarded_fp32_passage` refuses to evaluate when the side is ambiguous. For an already-stopped real interval it returns F=G=1. For guaranteed-above intervals it computes extremal log-distance first-passage values, using the repaired independent density quadrature from #4384 and monotonicity under coupled Brownian paths. **The F/G ranges are diagnostic estimates, not rigorous interval arithmetic**: scipy adaptive integration's estimated errors are not certified enclosures.

## Current composition: NOT RUN

All eight test methods in the transplanted `test_quantized_barrier.py` are **NOT RUN against this composition**. The command below is a future reproduction instruction, not an execution receipt. Source review and independent scalar endpoint-distance arithmetic do not establish that the combined F/G calculations or tests pass. The author's separate #4398 8/8 and #4396 24/24 reports are not a combined run.

## Historical reproduction evidence (#4385; not this composition)

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_quantized_barrier
```

The original #4385 author reported local testing on Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0: **7/7 tests pass**. Includes one-ULP negative classification, the literal original alias, finite/invalid encoding checks, 200 deterministic true-value-in-cell probes, 80 selected double-precision first-passage bracket checks, and a further 1,500-case seeded guard sweep (1,318 ABOVE, 182 AMBIGUOUS, zero >3e-11 reference bracket overages). The author associated that historical run with these **old blobs**, neither of which identifies the current transplanted source/test:
- `quantized_barrier.py`: `3d94dea54853b898ddfb129461b35ad5e53da31a`
- `test_quantized_barrier.py`: `26d213ccf70aa6888af4fe0835cb89fcce7f80b8`

## Open numerical limitations

The F/G brackets remain diagnostic estimates, **not certified intervals**; adaptive quadrature error estimates are not rigorous total-error certificates. #4396's conservative unsupported-intermediate rejection is retained, not an arbitrary-finite-input guarantee.

The #4396 author also reported a one-ulp reflection result `G > F` at `x=0.003757656910372328`, `drift=0`, `sigma=1.4347739823598538`, `discount=7.308163668621485e-15`, `horizon=0.043062096140339595`: floating-point F `0.9899303452367243`, G `0.9899303452367244`. Their high-precision reference instead has F greater than G by about `3.119e-18`. This is author evidence, not independently rerun here. Although the mathematical discounted-passage quantities obey `0 <= G <= F <= 1`, the reflection implementation does not enforce strict rounded-output ordering. The log1p endpoint correction does not repair that limitation, and the observation alone is not evidence of a quadrature defect. See [author comment](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4396#issuecomment-6531386859).

## Hard boundary: still NOT an fp32/production PASS

This is a Python f64/NumPy reference for float32 input quantization. It does **not** demonstrate a correct or fast fp32/fp16 GPU kernel, a real interval enclosure for F/G, robust derivative/gradient bounds, all-parameter HX obstacle admissibility, or matched P1–P5 neural advantage. Native low-precision inference must retain AMBIGUOUS as a distinct, fail-closed outcome; no hidden coercion to a 0/1 spike decision. Re-run the full upstream integration test and independent numerical/interval certification before considering P0 admission.
