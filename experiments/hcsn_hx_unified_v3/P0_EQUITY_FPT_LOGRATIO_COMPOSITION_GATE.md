# HCSN P0 / exact-sibling composition: financial equity + near-barrier first passage

**DRAFT / RESEARCH ONLY / DENY_ALL**. Keep `all_blockers_closed=false`,
`production_activation_allowed=false`. This does not authorize any worker,
spike, finance, model, CPU/GPU, or deployment path.

## Precise parents, conflict policy, and scope

- This branch starts from **#4468 exact HEAD**
  `f4a7db47a95ca36ec097951df91df7a604314149`. Its small-discount bond,
  finite-equity and renewal upper-endpoint guards remain unchanged.
- The additional near-boundary log-ratio condition is a narrowly composed
  sibling **#4467** fix from exact HEAD
  `8fd8a72d73daf802aef339e8268735d768cf4b58`.
- Only the existing `_log_asset_ratio` helper in `hx.py` was modified.
  Its ordinary-domain quotient, overflowing-ratio fallback, strict F/G
  ordering rejection, boundary and closed equity behavior remain otherwise
  byte-for-byte unchanged. The regression module is copied from the
  previously inspected sibling source without a new scientific assertion.
- This is not a merge of unrelated branches nor a production integration.

## Adversarial numerical reproduction, not source-exact CI

A local Python 3.13.5 / SciPy 1.17.0 / NumPy 2.3.5 / mpmath 1.3.0 probe
reconstructed the inspected helper and first-passage expressions and compared
against a separate 110-dps Brownian first-passage evaluation. **It was not a
full repository checkout or full module import**.

For four positive barrier scales `0.1, 0.3, 0.7, 1e308`, the one-nextafter-UP
asset and `tau=1e-30,1e-29,1e-28` gave 12 independent comparisons:

| Reproduction | Inherited helper | Composed helper |
|---|---:|---:|
| Largest absolute F error among old admitted cases | 0.08184136868438352 | 2.7755575615628914e-16 |
| Largest absolute G error among old admitted cases | 0.08184136868438352 | 1.1102230246251565e-16 |
| Old 1e-30 F/G ordering failures across four scales | 4 explicit refusals | 0 refusals for these 12 |
| 1,200 seeded 1-ULP log ratios over broad exponents | not measured as a gate | max relative error 2.220446049250313e-16 |

Concrete admitted false result: at boundary `0.1`, nextafter-UP asset,
`tau=1e-29`, the inherited F is `0.7788126597698866`, whereas the
independent reference and composed result are `0.8606540284542701`.
Do **not** count old ordering refusals as numeric errors or a passed response.

The selected patch retains fail-closed ordering semantics: other finite-input
regimes still raise `ArithmeticError` when binary64 cannot establish
`0 <= G <= F <= 1`.

## Exact-branch tests required before merge or gate promotion

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_near_barrier_log1p
python -m unittest -v experiments.hcsn_hx_unified_v3.test_p0_equity_renewal_composition
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_bond_small_q_nonunity
```

The tests are present on this branch but **have not been executed against a
full, exact-HEAD checkout in this session**. This local slice neither proves
the coupled financial endogenous boundary/QVI nor a global numerical
enclosure, derivative theorem, native fp32/fp16/GPU equivalence, mechanism
advantage, memory, four-modal quality, 4096-cell resource envelopes or matched
compute-budget superiority. Until each independent gate is evidenced,
`DENY_ALL` remains mandatory.
