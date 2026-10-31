# P0 financial HX finite-domain obstacle increment — 2026-10-31

**Research-only / DENY_ALL / NO_GO.** Stacked on exact draft PR #4495 HEAD `989abc7557a4323f54a5f89c8c29a9ee9b3f952d`. All previous analytical HX, regenerative QVI, model, negative evidence, native owner and production controls remain unchanged.

## What is independently implemented

- `hx_obstacle_grid_independent.py` reconstructs HX representative-bond cash flow from independent time-first-hit **density quadrature** (Brownian log asset, variable `t=(log(A/b)/(sigma*u))^2`). It does **not** import or call the repository's published bond Eq.(8), financial smooth-fit Eq.(12), equity Eq.(A7), or financial Green resolvent.
- Given a *fixed candidate* financial default barrier `b`, a monotone finite-difference/Howard policy iteration solves the discounted **financial equity obstacle** `max{(L-r)V + payout*A + B(A;b,T) - C, -V}=0` in log-asset coordinates, with `C=(1-tax)*coupon+principal/T`, zero value on the lower boundary and an explicitly assumed no-default far-field Dirichlet value.
- The solver returns a discrete residual, any extra immediate-STOP region above the supplied candidate barrier, numerical quadrature error estimates (NOT interval enclosures), and its tail assumption. It refuses unsupported `payout=0`, unrepresentable/invalid finite grids, invalid probabilities, failed pivots or unresolved policy iterations.
- This is an **independent obstacle counterexample detector for a fixed financial boundary**, NOT the endogenous coupled He–Xiong financial equilibrium, universal obstacle solution, convergence certificate or a neuronal Call/Risk/Margin effect.

## Locally executed test evidence

Reproduce on the repository branch using real `hx.py`:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_obstacle_grid_independent
```

In the local Python 3.13.5 / SciPy reference environment, **5/5 tests PASS**, zero skipped, using a **locally reconstructed subset** of the preexisting HX parameter, boundary and bond functions and the corresponding independent killed-resolvent equity (not an exact upstream file checkout). Thus the new files were locally executed, but the full repository integration test and CI are **not** claimed as completed.

- 20 independent bond-quadrature comparisons (4 parameter configurations × 5 asset ratios) against the reconstructed HX Eq.(8) have maximum absolute discrepancy `7.105427357601002e-15`. SciPy `quad` error estimates are not rigorous rounding bounds.
- Standard HX `sale_fraction=0.015`: candidate financial barrier `64.6251766753`. With 101/201/401 log-grid nodes at `log_upper=3.6`, no extra STOP region was detected; finite-grid Bellman residuals were below `5e-13`. **No extra STOP detected is inconclusive, not a global certificate.**
- Retained adverse HX regime `sale_fraction=0.2`: candidate algebraic boundary `101.324028609`, independent financial equity near `1.01*b` is negative `-0.00048928557`. The obstacle grid detects extra exercise through `112.879805625` for 101/201 nodes, and `111.868445323` for 401 nodes. This is an **explicit bounded refutation** of treating the algebraic smooth-pasting candidate as a globally valid financial stop.
- Maximum finite-grid residual in displayed cases `9.095e-13`; a separate `log_upper=4.2` check retains an extra STOP region. This is *not* a certified continuum truncation or full all-domain sensitivity proof.
- Invalid domains, unsupported payout-zero limit and grid/iteration caps fail closed.

Exact locally tested and remotely read-back Git blob identities:
- Solver: `782795200d55c23c58502f86715b9952b45b9b17`.
- Tests: `49b2d16fcaccce2d838f04c15e5f25feb295df3f`.

## Remaining P0-P5 scientific admission gates

| Stage | Status | Missing evidence |
| --- | --- | --- |
| P0 complete HX | **OPEN** | Self-consistent financial free-boundary fixed point; entire admissible-domain obstacle and finite-domain convergence/interval enclosure; discontinuous/degenerate regimes; actual FP32/BF16 implementation and implicit-gradient error bounds |
| P1 attribution | **OPEN** | Eight-channel matched information + signed slope + active parameters + **total** training/inference compute ablation; heldout positive gain, multiplicity correction, OOD negative-transfer control |
| P2 continuous memory | **OPEN** | Learned content state and causal Selective Copy, MQAR, overwrite, long retrieval, irregular time, repeated-event checkpoint and crash replay |
| P3 four-modal | **OPEN** | Real distinct text/image/audio/video encoders; paired heldout retrieval/alignment and robustness |
| P4 native | **OPEN** | Real Rust/GPU kernel, CPU/GPU/RSS/p95/p99/Joules, 64/256/1024/4096 Cell scaling and recovery |
| P5 hybrid | **BLOCKED** | Prespecified equal data/tokens/FLOPs/training/inference budget net quality-and-cost advantage over tuned gate/Transformer/SSM baselines |

Historical negative training and hardware results are **not erased, selected away, or promoted to success**. `production_activation=false`; `all_scientific_blockers_closed=false`. Keep this research PR draft, unmerged, and independent of production permission.
