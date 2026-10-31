# HCSN P0: resolved-f64 characteristic-root scale audit

Status: **DRAFT / RESEARCH ONLY / DENY_ALL**. This repair does not close HCSN P0, qualify production, or change the historical neural performance results.

## Parent, scope and precise source

- Single immutable parent: #4424 head `8edb08246673a7c78e8bc9d96b8662220be3bff6` (scalar Lambert-W branch-point repair).
- Parent `stopping.py` Git blob: `d6b81e7ce61000611983b16a300c5d6cea7e2da8`.
- Patched `stopping.py` Git blob: `cd76744cdd67afd3fec8c71e087ceb704c23cc10`.
- New adversarial tests Git blob: `bcdf7637a3201d5f71fdf26345fb5ad5e57b4e46`.
- Unchanged parent `test_stop_branchpoint.py` Git blob: `7a0ecf72658165d14d945784d1b193f0ef21ca53`.
- Only one scalar research Python source, this one new test and this evidence note are changed; no HX financial kernel, Rust runtime, model training, checkpoint, permission or deployment edits.

## Independently reproduced negative witnesses

The former formula `hypot(mu, sqrt(2*rho)*sigma)` followed by `(scale-mu)/(sigma**2)` for negative drift, or `2*rho/(scale+mu)` for nonnegative drift, is mathematically rationalized but numerically fails even when the positive root is representable:

| Drift | Diffusion | Discount | Parent outcome | 180-digit Decimal oracle |
| ---: | ---: | ---: | --- | ---: |
| -1 | 1e200 | 0.1 | `OverflowError` at `sigma**2` | 4.47213595499958e-201 |
| 1e308 | 1e308 | 0.1 | `0.0` from overflowing denominator | 9.54451150103324e-310 |
| 0 | 1 | 1e308 | `NaN` via `sqrt(2*discount)` | 1.414213562373095e154 |

The new kernel scales drift by diffusion, forms `sqrt(2)*sqrt(discount)`, uses separate algebraically equivalent branches, and refuses non-finite/non-positive roots or roots with `ulp(kappa)/kappa > 1e-9`. This ULP check is only a necessary floating-point resolution check, **not a certified relative error bound or full parameter proof**.

## Executed local CPU evidence

Relevant research source was reconstructed byte-for-byte from GitHub blob `d6b81e7ce61000611983b16a300c5d6cea7e2da8`; pre-existing test file was reconstructed byte-for-byte from `7a0ecf72658165d14d945784d1b193f0ef21ca53`. The patched source and new test Git blob hashes above also match the locally tested bytes.

Before replacement, the six new test methods on the **exact original parent source** produced 8 assertion failures and 6 errors. After replacement:

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale
```

**14/14 tests passed, zero skips** (8 historical + 6 new); measured 1.18s process wall time and 122,508 KiB maximum RSS in the local reconstructed relevant-module environment. The deterministic 1,024-input extreme-exponent sweep (seed `2026103106`): **800 accepted, 224 explicitly refused**, maximum observed accepted relative error **1.676995e-10** versus independently evaluated Decimal roots. This is sampled evidence, not an all-domain bound. Accepted/refused counts are not substitutes for trained-model quality.

The tests additionally exercise one resolved huge-diffusion renewal boundary, finite-difference sigma elasticity, ordinary scalar QVI regression, Lambert-W branch point and explicit refusal cases.

## Deliberately unclosed gates

- **P0:** HX finance obstacle/fixed-point global admissibility, full-domain interval certificates, all low-precision barriers and gradients, coupled high-dimensional QVI; large-scale downstream `qvi`/value evaluation remains unqualified.
- **P1:** no Call/Risk/Margin causal incremental-quality success; retained prior negative 0/4 mechanisms.
- **P2:** no new independent long-memory or repeated physical-event quality evidence.
- **P3:** no independently trained four-modal paired content and robust OOD advantage.
- **P4:** no native Rust/GPU HCSN neural kernel, 64/256/1024/4096 Cell, joule or end-to-end recovery proof.
- **P5:** no budget-matched superiority against Transformer/SSM; expansion not admitted.

This was exact-blob source reconstruction of the **relevant module**, not a full Git checkout or full GitHub Actions run. Do not merge as production-ready or infer that failed/queued/skipped CI is green. `all_blockers_closed=false`; `production_activation_allowed=false`.
