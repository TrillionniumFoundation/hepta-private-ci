# HCSN P0 FPT quadrature: distant-mode and near-barrier regression

**Research-only / Draft / DENY_ALL.** Exact parent is PR #4382, commit `27063d2ab9d72f7cfbbd17fb2d200416b1b24dcd`. Only the independent financial first-passage oracle and its tests are modified; no production Rust, neural training, permission, or runtime changes.

## Reproduced failure before this patch

Original `integrate_passage` can numerically lose the entire probability mass when a strong negative log drift moves the narrow mode far beyond the adaptive quadrature's initial probes. For
`x=3.69821872103264, drift=-0.7997788483837058, sigma=0.07189992168352377, q=4.966000807445653e-5, horizon=85.44911244689267`:

| Route | F (un-discounted hit probability) | G (discounted factor) |
| --- | ---: | ---: |
| Previous unsegmented density quadrature | 1.2633863825343167e-15 | 1.2629731423380866e-15 |
| Fixed independent density quadrature | 1.0000000000000004 | 0.999770395965759 |
| Reflection-CDF cross-check | 1.0 | 0.999770395965747 |

On the 72-case fixed distant-mode stress suite, **8/72** original cases had absolute discrepancy above `1e-8`, including a worst-case discrepancy of **1.0**. The patched 72-case maximum was `1.0647038806155251e-13`.

Second bug: a nearly-zero log distance can make `uend=uc/(x/sigma)` extremely large. A single quadrature from `vcut` to `uend` silently skips the lower-v contribution and can either disagree with the independent reflection route by ~`1e-9` or trigger probability-ordering rejection. The fixed algorithm subdivides this integration into geometric panels of factor 16, with a 512-panel fail-closed cap.

## Change and mathematical rationale

With `scale=x/sigma`, `a=drift*x/sigma**2`, the large-u density exponent at discount `q` is
`-u*u/2-a-(a*a/2+q*scale*scale)/u**2`.
The positive mode is `u*=(a*a+2*q*scale*scale)**(1/4)`, and the exponent has curvature `-4` at that mode. The code uses `sqrt(hypot(a,sqrt(2*q)*scale))` and integrates over explicit panels around `[u*-8,u*+8]`, plus tails. This uses **no** HX Eq. (8) bond formula in the density integration; the reflection implementation is a differential test only.

## Reproduction and evidence limits

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_bond_fpt_independent
python -m experiments.hcsn_hx_unified_v3.bond_fpt_independent
```

Local standalone reproduction on Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0: **9 tests passed, 1 upstream integration test skipped** (the standalone local reference did not include `hx.py`). This includes the new one-case regression, 72 distant-mode cases, and 2,000 deterministically seeded broad-parameter cases. The latter sample had maximum absolute F/G cross-check discrepancy `2.3991919562149633e-12` and zero exceptions. Two additional 2,000-case exploratory seeds also had zero exceptions and maxima below `8e-13`.

The two **patched Git blob SHAs** match exactly the locally tested files:
- `bond_fpt_independent.py`: `34c1b26327295d7573d9103ce428c426d3107a26`
- `test_bond_fpt_independent.py`: `15586aeb971dcb67a5fc991c837a5866383f9210`

**Not verified:** execute the *non-skipped* exact-upstream HX integration case from the full stacked checkout. Approximate quadrature errors from SciPy are not validated interval enclosures. The 2,000-case stress is a bounded numerical suite, not proof over all admissible HX parameters. Global obstacle/equilibrium, fp16/fp32, analytic gradients, P1 ablation superiority, P2 event memory, P3 multimodal, P4 native GPU, and P5 scaling remain blocked. Do not treat this research patch as production admission.
