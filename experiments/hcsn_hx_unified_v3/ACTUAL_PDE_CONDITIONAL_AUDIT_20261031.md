# P0 actual HX debt-PDE conditional decision audit — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Strictly stacked on PR #4508 HEAD `be5299fb4c5ae5feaa421d7f49f1ac2402c4fbbd`; its #4499 debt-PDE/equity VI and the #4508 exact-rational perturbation oracle remain byte-identical. No existing mathematics, negative evidence, CI, host, or production permission is changed.

## The missing integration filled

Previously #4508's conditional perturbation theorem had been exercised only on synthetic finite grids. This increment actually runs its **unchanged** exact-rational checker on numerical debt-PDE + equity-obstacle output from #4499, for both nominal and high-liquidity HX. The endogenous candidate barrier comes from the existing HX algebraic expression, while the **debt cashflow** comes from the independent time-dependent PDE, not the published bond Eq.(8).

A SciPy banded solve returns a tiny nonzero `V[0]` despite the exact default Dirichlet condition `V[0]=0`. The unchanged exact checker appropriately refuses. The new integration accepts an explicit zero projection only when the measured error is at most **64 ULP of the grid's maximum absolute value**, and then **recomputes the full rational interior Bellman residual against that projected value**, including the adjacent node. Artificially injected 1e-6 boundary drift is rejected. This ULP threshold is an empirical numerical admission rule, **not** a certified LAPACK roundoff theorem.

For every grid it reruns three *hypothetical* external absolute debt + upper-equity uncertainty budgets: 0, 1e-6, 1e-3. These budgets are **not** justified by the actual finance PDE / continuum; zero is only an exact quantized-grid thought experiment. They cannot be promoted to a genuine uncertainty certificate. All rows, including no-detection, remain in a canonical lossless evidence record.

## Actually executed 18-case panel

Both financial `sale_fraction` values use `log_upper=3.6`. Node/temporal meshes are 101/250, 201/500 and 401/1000. Count columns below refer to **interior** cells only.

| Sale fraction | Grid | Nominal extra STOP | Exact-grid e=u=0: STOP / CONTINUE / AMBIGUOUS | Hypothetical e=u=1e-6 | Hypothetical e=u=1e-3 |
|---|---|---|---|---|---|
| .015 | 101 | No | 0 / 99 / 0 | 0 / 99 / 0 | 0 / 98 / 1 |
| .015 | 201 | No | 0 / 199 / 0 | 0 / 199 / 0 | 0 / 194 / 5 |
| .015 | 401 | No | 0 / 399 / 0 | 0 / 399 / 0 | 0 / 375 / 24 |
| .2 | 101 | **No (known mesh miss)** | 0 / 99 / 0 | 0 / 99 / 0 | 0 / 95 / 4 |
| .2 | 201 | Yes, to asset 103.1643745 | 1 / 198 / 0 | **0 / 197 / 2** | 0 / 186 / 13 |
| .2 | 401 | Yes, to asset 104.0970446 | 2 / 397 / 0 | **0 / 394 / 5** | 0 / 356 / 43 |

**Key finding:** The exact rational proof can classify the quantized finite-grid solve under hypothetical zero debt and boundary uncertainty. It **cannot** repair an under-resolved 101-node mesh, and even hypothetical 1e-6 external uncertainty makes the 201/401-grid high-liquidity STOP classifications ambiguous. This quantitatively identifies which independent *financial* error budget must be supplied next. It is **not** an all-domain negative or positive continuum obstacle certificate.

## Evidence and rerun

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_actual_pde_conditional_audit
python -m experiments.hcsn_hx_unified_v3.hx_actual_pde_conditional_audit
```

Local Python 3.13.5 / NumPy / SciPy CPU: **6/6 targeted tests PASS, 0 skipped**. First local run failed 4/5 because the strict upstream exact-default boundary check correctly rejected floating-point solver drift; second run failed one test due to an over-strict 8-ULP engineering threshold. The final 64-ULP bound and 1e-6 injected-defect refusal passed all 6 tests. Those initial errors are disclosed rather than hidden.

The tested package used **exact byte-identical published** upstream code for three scientific implementations:

- Bond PDE `ad6262821e9a63e5a7f1a8dd8e39e3c020d7a815`.
- Equity obstacle PDE `0aea5c12b2e42c6a17277071efc968a9c2981df2`.
- Conditional rational checker `aff677714e8307e16b4c0b6e29512b7bab70b649`.

**Important upstream limitation:** Local `HX`/candidate-boundary functions were reconstructed equivalents (local blob `8d719bec731da82184137069aeacce50d38c1b1a`), not the full upstream `hx.py` blob `b6afc3c957297ed9b37b4f0177e0343ee6607f83`. This is a partial locally reconstructed test harness, **not** a successful clean full-repository CI. The new two Python source/test blobs are byte-identical between locally executed and published GitHub files.

- Original complete pretty-printed JSON: SHA-256 `79569c7e852fc0d9d8cb8ba3d772253a4482f643366213fdeec7c6a879e0a791`, 14,993 bytes.
- Gzip with mtime=0: SHA-256 `db091636a09fbfe6c44200bd0418326f8bbeef0046f35f1aaa8679888b95714c`, 1,954 bytes; retained losslessly as `ACTUAL_PDE_CONDITIONAL_PANEL_20261031.json.gz.b64`, decode via `base64 -d | gzip -d`.
- Canonical `rows` payload SHA-256 (stable JSON sorting and separators): `c90886ecea9e70c1c094e8ca33828e4db9b513c5fc114f74e8835c4864f838fe`.

## Scientific gates

P0 remains **OPEN**: proof of genuine debt-PDE spatial/time/tail/rounding uncertainty, far-field equity uncertainty, self-consistent coupled financial default barrier, continuous and low-precision active-set certification all missing. The assumptions `e=u=0` must **not** be used in real finance admission. P1 matched causal mechanism superiority **OPEN**, P2 OOD memory/host durable recovery **OPEN**, P3 real four-modal paired generalization **OPEN**, P4 Rust/GPU 64–4096 Cell and Joules **OPEN**, P5 matched-benefit scaling **BLOCKED**.

`production_activation=false`, `all_scientific_blockers_closed=false`, `complete_debt_error_budget=false`, `continuum_certified=false`. Keep all historic failures, do not merge/deploy as production.
