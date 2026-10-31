# HCSN P0: actual fixed-barrier debt-PDE error from rational time-first-hit enclosures (2026-10-31)

**RESEARCH_ONLY / DENY_ALL / NO_GO**. This is an additive P0 research increment on draft #4520, exact parent HEAD `1d9794c9458a787d54a0d8c1848b90e6acdfd884`. Does not change HX financial equations, the numerical debt PDE, prior data, any CI workflow, a trained model, native authority, or production.

## Mathematical construction (not the HX formula being verified)

For log distance `y>0`, downward Brownian first-hit density is `f(t)=y/[sigma sqrt(2 pi t^3)] exp[-(y+mu t)^2/(2 sigma^2 t)]` for `dY=mu dt+sigma dW`. We independently enclose the first-hit integral `F(T)=int_0^T f(t)dt` and discounted integral `G(T)=int_0^T exp(-q t)f(t)dt`, with no imports of HX bond Eq.(8), financial smooth-fit Eq.(12), equity Eq.(A7), financial Green resolvent, nor the PDE solver into the first-hit module.

- All finite input binary64 values convert exactly to `fractions.Fraction`; `pi` is bracketed using alternating rational Machin arctan series. Square roots use integer-isqrt floor/ceiling; exponential uses alternating Taylor rational bounds, halving and outward rounding on a `10^-35` grid. `x>=100` safely uses the proved `exp(-x)<10^-40` envelope.
- The time density and discounted density each have a unique maximum, identified by the sign of `y^2-3 sigma^2 t-(mu^2+2 q sigma^2)t^2`. Exact-rational endpoint/mode envelopes yield Darboux lower/upper integrals. Separate certified trapezoid bounds use the explicit log-density first and second derivatives, then intersect with Darboux bounds.
- `[0,epsilon]` missing first-hit mass is bounded through reflection and the Chernoff Gaussian upper bound. If the requested integral width cannot be attained within `max_cells`, the algorithm **refuses**. At `y=0,T=0`, default/maturity corner semantics must be supplied by the financial owner; unsupported interior integral inputs refuse.
- The independent finite-maturity financial bond at each fixed-barrier grid node is enclosed by the exact affine expression in `F,G` and outward `exp(-qT)`, including **surviving maturity principal**. This is a different integration algorithm from the HX normal-CDF closed form and the existing financial PDE.

The all-node auditor invokes the inherited, independent backward-Euler debt PDE from #4499 and builds one rational bond interval **per numerical log grid node**. For every stored floating PDE output `D_i`, the exact continuous **fixed-barrier** bond `B_i` lies in `[l_i,u_i]`. Therefore, at these discrete log coordinates only, with the supplied binary64 parameters treated as exact physical inputs:

`max_i max(0,l_i-D_i,D_i-u_i) <= max_i |B_i-D_i| <= max_i max(|D_i-l_i|,|D_i-u_i|).`

These inequalities include the stored PDE floating-output discrepancy; no unverified grid-refinement rate is inserted. Input `mu=r-payout-sigma^2/2` and `q=r+shock*sale` are formed from **exact** binary64 rational parameters for the reference. The PDE may round those intermediates; that discrepancy is included.

## Actual local all-node measurements

Fixed candidate HX default barrier from the existing Eq.(12), `log_upper=3.6`, first-hit `F/G` width `<=0.005` per node, `max_cells=5000`. All nodes were evaluated with no omissions. Columns are mathematical *bounds on maximum absolute error over these stored nodes*, **not** continuum PDE error bounds for arbitrary state/time.

| sale_fraction | nodes / time steps | lower on max error | upper on max error | canonical full panel SHA256 |
|---|---|---:|---:|---|
| 0.015 | 101 / 250 | 0.00002281979464 | 0.04271943424 | `73fb3c0f28352811cc263e8c129d03f7bfe61e0e1c71b8942f8fb7781266b3f4` |
| 0.015 | 201 / 500 | 0.00001141118852 | 0.04310115223 | `584fe425b699bee348d4a9c1b7baf018b95aa5417ae7e6d01759fadc576f5751` |
| 0.015 | 401 / 1000 | 0.00000570573523 | 0.04301238690 | `386b2ce2fe09ca9308efcf0092ed3e4fccd76ba7a6bc33b866fa09935dfa3368` |
| 0.200 | 101 / 250 | 0.006664487854 | 0.09688956983 | `7aafd7f11db3cbcae3a7facad1448db9bdba55b9d1c6dd52efc3186cec34b540` |
| 0.200 | 201 / 500 | 0.003334032091 | 0.09910185107 | `00adcd877f8382ae382b38fcd104eca30f047a4424e5a79b5a15c0e20a07ca0d` |
| 0.200 | 401 / 1000 | 0.001667455636 | 0.09942243739 | `f40704733ea7873a218a61ae3d49733651117e5b49b0bd91ff36bae9a9da81d6` |

**New negative finding:** for *all six* declared meshes, the proven lower bound on the maximum fixed-barrier debt error exceeds `1e-6`. This refutes the earlier use of an *assumed* `1e-6` debt budget as physically verified at these configurations; it does not refute convergence of a different finer numerical method. The upper bounds are intentionally conservative and may be wider than the actual error. A `demand_external_debt_error_budget(..., '0.000001')` call correctly refuses. The six full unabridged JSON node records are maintained in the standalone local evidence bundle for reproducibility; only their canonical SHA digests and complete algorithm are committed here. These are **not** evidence of an all-grid quantum rounding theorem.

## Executed tests and source provenance

Local Python 3.13.5, SciPy 1.17.0, NumPy 2.3.5, mpmath, CPU, **9/9 focused unittest methods PASS**, no skips. An initial test used `float(rational_string)` instead of parsing it as `Fraction`; corrected before publication with unchanged scientific thresholds.

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_first_hit_time_interval \
  experiments.hcsn_hx_unified_v3.test_debt_pde_rational_interval_audit

python -m experiments.hcsn_hx_unified_v3.debt_pde_rational_interval_audit 0.2 101
```

Tests include five physical drift/discount cases against a separately coded normal-CDF reference; high precision independent `pi/exp/sqrt` checks; financial bond interval comparisons; actual all-node audits at two liquidity regimes; a deliberate corrupted numerical PDE node that increases the guaranteed discrepancy; invalid physical conditions; refusal of insufficient quadrature work; and rejection of an unearned `1e-6` real debt budget.

Exact upstream debt PDE implementation blob in the *local tested harness* matches #4520: `ad6262821e9a63e5a7f1a8dd8e39e3c020d7a815`. HX baseline functions were locally **reconstructed**, blob `8d719bec731da82184137069aeacce50d38c1b1a`, not the full upstream HX file blob `b6afc3c957297ed9b37b4f0177e0343ee6607f83`; **no full repository CI** or actual remote native/GPU run is claimed. All four *new* source/test Git blobs were verified against exact locally tested bytes.

## Remaining blockers: explicit NO_GO

This closes a **bounded experimental subquestion**: the finite set of actual PDE nodes now has external first-hit-derived upper and lower pricing error bounds. It does **NOT** close P0: missing continuum spatial interpolation error, full maturity-dependent error envelope (including incompatible corner), global financially endogenous coupled equilibrium, all-state obstacle active sets, independent financial FP32/BF16 gradient validation, and downstream exact-rational equity/STOP propagation using *all* real error budgets. P1 mechanism advantages remain negative/unproved; P2 OOD memory/host recovery, P3 genuine four-modal, P4 native GPU/Joules/4096, and P5 equal-budget backbone advantage remain open/blocked.

`complete_debt_error_budget=false`; `global_equilibrium_certified=false`; `all_scientific_blockers_closed=false`; `production_activation=false`. Keep this PR Draft/unmerged. All prior failures remain visible.

## Follow-up: bridge real debt bounds into existing conditional stop audit

Two additive files implement a strict diagnostic bridge using the exact same inherited parent #4520 numerical equity/conditional gate sources. Before evaluating, the bridge rejects incomplete/mismatched node sets and parameters, rounds each measured *actual* debt-error supremum **upward** to nine decimal places, and passes it as `debt_error`. It deliberately sets `upper_equity_error='0'` only as a **hypothetical perfect upper-equity boundary**, never claims physical full-bound verification. Receipt fields `equity_boundary_error_proved=false`, `continuum_stop_certified=false`, `scientific_gate_closed=false`, `production_activation=false` are invariant.

| sale_fraction | nodes / time steps | actual debt upper rounded up | guaranteed STOP | guaranteed CONTINUE | AMBIGUOUS |
|---|---|---|---:|---:|---:|
| .015 | 101/250 | 0.042719435 | 0 | 98 | 1 |
| .015 | 201/500 | 0.043101153 | 0 | 196 | 3 |
| .015 | 401/1000 | 0.043012387 | 0 | 392 | 7 |
| .2 | 101/250 | 0.096889570 | 0 | 93 | 6 |
| .2 | 201/500 | 0.099101852 | 0 | 186 | 13 |
| .2 | 401/1000 | 0.099422438 | 0 | 372 | 27 |

**No guaranteed STOP survives** the supplied *real* debt error budget on any of these panels, even with the idealized zero upper-equity error. This is deliberately a narrower conditional finite-quantized-grid statement, not a proof that the true financial optimal equity STOP policy has no stop states. Indeed, the previous fixed-barrier extra-STOP *numerical* observations remain unchanged and unresolved.

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_measured_debt_conditional_bridge
```

**2/2 additional focused local tests PASS**, zero skipped. The parent #4520 `hx_joint_pde_obstacle.py`, `hx_conditional_debt_interval_gate.py`, and `hx_actual_pde_conditional_audit.py` were matched by exact locally tested Git blobs `0aea5c12b2e42c6a17277071efc968a9c2981df2`, `aff677714e8307e16b4c0b6e29512b7bab70b649`, and `c21306bd2e00ed90b2688136bbd68712382bcae9`. The new bridge/test blobs `9f531ee84ae6c331342ee5320f975e77ea2e2092` / `d531045ac14cdec27b95c567aa655ebe2d8b9a0d` were read back exact. Total **11/11 new focused local tests PASS**, no full repo CI claim or P0 scientific closure.
