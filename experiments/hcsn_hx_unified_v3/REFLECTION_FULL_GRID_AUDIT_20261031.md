# P0: rational Brownian reflection all-node financial debt-PDE comparison (2026-10-31)

**Research-only / DENY_ALL / NO_GO.** Stacked on #4535 exact HEAD `9681bda7fa3359854cb8ed7a232dfe0848bf1e23`, descendant of #4530. No changes to the original He–Xiong financial formula, original debt-PDE, historical evidence, native production owner or CI configuration.

## Additional analytic rational reference (separate from time-density Darboux)

For `Y_t = y + mu*t + sigma*W_t`, `y>0`, and downward first-hit time `tau_0`, finite first-hit probability is evaluated using the Brownian reflection identity

```
F_mu(T) = Phi(-(y+mu*T)/(sigma*sqrt(T)))
        + exp(-2*mu*y/sigma^2)*Phi(-(y-mu*T)/(sigma*sqrt(T)))
theta   = sqrt(mu^2 + 2*q*sigma^2)
G_mu,q(T) = exp((theta-mu)*y/sigma^2) * F_theta(T)
```

These are first-hit identities, not imported HX Eq.(8) bond software. The normal CDF is bounded via **exact-rational alternating Gaussian series with certified decreasing next term**, a separately bounded rational pi/sqrt/exp implementation from the independent first-hit library, and a rigorous Mills inequality for `z>=5.5`. Signed multipliers and square-root endpoint perturbations are enclosed; output is outward quantized to the 1e-35 rational grid. The routine does **not** import SciPy's normal CDF, HX Eq.(8)/(12)/(A7) or the financial Green resolvent.

This is an **auxiliary analytic reference**: the mathematical reflection identity overlaps the original financial bond's first-passage decomposition. It is *not* a fully independent finite-difference or time-density quadrature derivation, and cannot on its own close full coupled HX or prove optimality. A separate physically integrated Darboux oracle is retained and has independently overlapped on **20** drift/distance combinations (drift -0.5, -0.01125, 0, 0.2, 0.7 × distances 0.036, 0.3, 1, 3.6; fixed sigma 0.25, T=2, q=0.25). All 20 F/G interval intersections passed. The earlier #4535 time-density oracle already independently certified strict **full 101-node** inequalities for the two declared HX regimes; it did not finish full 201/401-node time-density integrations.

## Six full-node analytic-rational error comparisons

For each exact binary64 input and every **finite grid node**, `B_true(i)` is enclosed in an exact-rational interval. Both PDE outputs are converted from float64 to exact rationals. Error bounds are computed without taking a shortcut through original HX bond code. Only strict `max_i Rannacher_error_upper(i) < max_i BE_error_lower(i)` is accepted.

| HX sale_fraction | Nodes / steps | BE max error lower | Rannacher max error upper | BE witness i / Rannacher upper i | All-node strict? | Canonical panel SHA256 |
| --- | --- | --- | --- | --- | --- | --- |
| 0.015 | 101 / 250 | 0.006229480155480175 | 0.003249828889069045 | 7 / 19 | YES | `dd80647fa5cf5dcbcb3a1193188a6e99dbd3aedebb9b28a5838ff3e96d624738` |
| 0.015 | 201 / 500 | 0.003024117534953333 | 0.0008133002708582381 | 14 / 37 | YES | `7266c5677148e78699f42f4eb3afa74bcb1de1d867e0857742163bca09c6943a` |
| 0.015 | 401 / 1000 | 0.0014919329037722565 | 0.00020340919712352916 | 29 / 75 | YES | `cf9f10c5258a0cf0ea2ba6ecea0ee4051080b49d890fb40e7a0306ef5e0fcbf7` |
| 0.2 | 101 / 250 | 0.01214171246082057 | 0.004310487438992286 | 12 / 9 | YES | `fee1a42514eb2f23857520ea8d51b5dd992c8860f4f212a8fe259897ce512363` |
| 0.2 | 201 / 500 | 0.005109272327672841 | 0.0010791848486976744 | 25 / 17 | YES | `0655589169b7a253dc49c4ad36661da5d1458689ad2f507a917b493b934b604b` |
| 0.2 | 401 / 1000 | 0.0023262002490985127 | 0.0002699167692140844 | 54 / 35 | YES | `8d1dbc83a8e203941ea6289099c9aee323c8083e2d04f53aa0624ebec0a0abb8` |

All six exact finite-grid panel routines were executed locally, with all nodes (101/201/401, not selected points). Their row-complete canonical JSON digests are frozen above for replay. This does not prove Rannacher is uniformly more accurate at every individual node, every parameter, between grid nodes or for a globally optimal coupled financial stop: **only the maximum of node errors** is strictly bounded under each declared mesh.

## Failure-preserving safety and tests

Five small targeted tests passed (5/5 methods, no skips) after correction of a negative-control test that initially expected a zero strict margin when identical solvers should actually produce **nonpositive** margin because of interval width. The tests cover: (a) twenty physical-time Darboux oracle overlaps, (b) rational Gaussian/Mills ordering, (c) invalid physical input rejection, (d) intentional equal-solver tie (no false strict win), and (e) invalid/incomplete grid refusal. A sixth test method contains all six frozen full-grid SHA256 assertions; all six corresponding panel routines ran separately, while one long combined six-panel unittest invocation was **not** claimed as completed.

Reproduce the quick controls:

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_rannacher_reflection_full_grid.ReflectionIntervalTests \
  experiments.hcsn_hx_unified_v3.test_rannacher_reflection_full_grid.RannacherFullGridTests.test_equal_solvers_do_not_pass_strict_comparison \
  experiments.hcsn_hx_unified_v3.test_rannacher_reflection_full_grid.RannacherFullGridTests.test_incomplete_or_invalid_grid_refused
```

Reproduce every frozen panel (long CPU test):

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_rannacher_reflection_full_grid.RannacherFullGridTests.test_six_frozen_all_node_certificate_digests
```

Source/test blobs committed and read back exactly as locally tested: `first_hit_reflection_interval.py` `1bc46da894941c0872072f0393cbcb600f76c54c`, `rannacher_reflection_full_grid.py` `eb1e7551b0dc9603e589704ac57472b62252eb93`, tests `7d06831e3f0c930dd74006e6482ab9ebe1435c0a`. The original independent time-density and both PDE solver sources match the pinned ancestor Git blob identities. Local HX parameters/boundary used a reconstructed research subset, **not a full repository checkout or CI green verdict**.

## Explicit scientific blockers remain

- **P0 OPEN:** Coupled original He–Xiong self-consistent equilibrium, global financial obstacle, rigorous *full equity* PDE and boundary error budget, all admissible parameter/extreme/discontinuous regimes, financial FP32/BF16 and true active-set gradients. The known `sale_fraction=0.2` negative-equity witness is **not** repaired by the debt-PDE.
- **P1 OPEN/NO_GO:** Existing 192-run negative/partial matched-mechanism observations remain, plus rank-one normalized Call/Put/Margin identifiability obstruction. No reliable independent causal gain.
- **P2 OPEN:** Real trained content memory, Copy/MQAR/overwrite/irregular time, durable host recovery/OOD advantages.
- **P3 OPEN:** Four independently pretrained genuine modality encoders, paired OOD temporal alignment.
- **P4 OPEN:** Native Rust/GPU, 64/256/1024/4096 Cells, full queue/transfer/recovery costs, p95/p99, measured Joules.
- **P5 BLOCKED:** Equal data/tokens/FLOPs and total-cost backbone scaling gain before expanding parameters.

No production activation; no global scientific blocker is marked closed.
