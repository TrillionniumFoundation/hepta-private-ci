# HCSN P0 Rannacher debt PDE — independent rational selected-node audit (2026-10-31)

**Scope:** RESEARCH_ONLY / DENY_ALL / NO_GO. This additive increment starts from exact draft #4528 HEAD `b365e539a0734ddbc337300f3994183059ef9214`; no earlier finance formula, negative observations, uncertainty threshold, learned weights, native Rust code, production permission or CI workflow was modified.

## Implementation and why

The original fixed-barrier finite-maturity debt solver (#4499) uses first-order backward Euler for all time steps, with an incompatible principal-at-maturity / recovery-at-default corner. `hx_bond_pde_rannacher.py` adds two backward-Euler **half steps** at the initial corner, followed by positivity-guarded Crank–Nicolson with the same 10 physical HX input parameters, maturity-T survival-principal far boundary, fixed candidate barrier, spatial mesh and time-step count. It explicitly REFUSES nonpositive generator rates, unsupported work and CN nonnegative-RHS-weight (CFL) violations. The reported machine algebra residual is *not* a continuum/roundoff certificate.

The new `rannacher_debt_point_certificate.py` consumes the separately authored exact-rational physical-time first-hit interval oracle inherited from #4524. At each selected actual PDE node it treats floating output as its exact binary64 rational; each solver's true error has a rigorous lower and upper interval **conditional on the upstream first-hit enclosure**. Strict improvement is claimed only when `Rannacher_error_upper < backward_Euler_error_lower`; a forced-identical-solver negative control must reject a strict-improvement claim. Physical identity binds all 10 float.hex inputs, barrier and grid. No analytic HX Eq.(8) is called by the solver or rational proof.

## Executed evidence (local CPU; **development-selected**, not preregistered)

The following are empirical **maximum errors across finite grid nodes** against separate Eq.(8), not all-node interval certificates. Identical log upper L=3.6, maturity-T horizon and time-step counts. The rigorously enclosed row is **one selected interior point** per panel, selected after inspecting initial error results.

| sale_fraction | nodes / time steps | BE max abs | Rannacher max abs | reduction | probe i | certified BE error lower | certified Rannacher error upper |
|---|---|---:|---:|---:|---:|---:|---:|
| .015 | 101 / 250 | .00622948016 | .00324982889 | 1.9169x | 19 | .00388578223 | .00326221644 |
| .015 | 201 / 500 | .00302411753 | .000813300271 | 3.7183x | 37 | .00101884216 | .000825877199 |
| .015 | 401 / 1000 | .00149193290 | .000203409197 | 7.3346x | 75 | .000328778793 | .000215971837 |
| .2 | 101 / 250 | .0121417125 | .00431048744 | 2.8168x | 9 | .0115844284 | .00434430160 |
| .2 | 201 / 500 | .00510927233 | .00107918485 | 4.7344x | 17 | .00458397726 | .00111305272 |
| .2 | 401 / 1000 | .00232620025 | .000269916769 | 8.6182x | 35 | .00203552536 | .000303779205 |

All **six selected-node inequalities** hold under the exact-rational first-hit oracle (323/336/329/843/893/869 refined time cells). Minimum strict separation: `0.00011280695630718484`. The first-hit width target is `2e-6` for F and G individually, and node/bond interval is wider depending on payoff coefficients. This does **not** prove all-node strict improvement, all-node error less than a threshold, financial free-boundary optimality, nor the missing 1e-6 external debt budget. In fact, even the observed improved 401-node max errors `2.03e-4` / `2.70e-4` greatly exceed 1e-6.

In this isolated Python 3.13.5 CPU process the single-sample solver CPU was BE ~0.0085/0.0332/0.1485 s and Rannacher ~0.0117/0.0466/0.2034 s for nominal 101/201/401, with comparable high-liquidity timings. These noisy observations suggest more CPU work; **not** a controlled full-platform latency, GPU or energy benchmark.

## Reproducibility and scope

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_hx_bond_pde_rannacher \
  experiments.hcsn_hx_unified_v3.test_rannacher_debt_point_certificate
python -m experiments.hcsn_hx_unified_v3.run_rannacher_debt_panel \
  --output /tmp/RANNACHER_DEBT_PANEL_20261031.json
```

**10/10 focused methods PASS**, zero skipped; six physical-time 60-digit independent mpmath checks, 6 meshes with Eq.(8) used for *empirical testing only*, rational cross-method probes, coarse/nonmonotone/CFL refusal, maturity/default corner, same-output negative control, physical-identity change. The local HX financial model was a previously reconstructed equivalent 98-line subset, not a byte-identical complete repository checkout. The inherited original debt PDE and physical-time mpmath reference were exact remote Git blobs. Full repository CI, actual target hardware, FP32/BF16 financial gradients, and global integration are **not** claimed.

The locally generated canonical six-case panel has SHA256 `ec07710f59586941f35a31359c4ed68fce10f081dac9be89bfff7d2cfe6e759f` (canonical body excluding its digest field) and pretty JSON SHA256 `1414777137c3bb7d407c23adf9767f371fc224874b9cd0f33915ddc9cbc4ac64`. The deterministic runner regenerates all six cases and checks the same scientific booleans (timing fields are hardware-dependent, so the canonical digest including single-run timing is not expected to match across machines).

Executed source/test/runner Git blob identities, each checked locally and remotely on upload:
- Solver `8afd308bbcc74ae4392b4be1dc593d97ff1b3333`
- Solver tests `b2a9ea19c5f0bf0d3b73b9654e57844eb75918d8`
- Rational point certificate `26b18c2a77300e87473252e8dcac8321fac3ee7e`
- Rational certificate tests `266c32939f8cc9b0a606565053a46a2bd82d2c2b`
- Panel runner `4b3375209c6ad97d23ab7c80d5b0fa0b945870f6`

## Remaining hard blockers (not silently upgraded)

**P0 OPEN:** requires full coupled financial fixed point and globally admissible obstacle, certified *all-node* continuum/time/space/tail/roundoff equity error, near-boundary active-set and true FP32/BF16 financial implicit gradients. **P1 OPEN:** 12-seed matched training fails multiplicity correction and structural rank-one mechanism identifiability remains. **P2 OPEN:** repeated-event OOD memory and actual durable host recovery. **P3 OPEN:** four real distinct encoder modalities and paired OOD alignment. **P4 OPEN:** Rust/GPU native kernels, 64/256/1024/4096 real cell CPU/RSS/p95/p99/Joules/recovery. **P5 BLOCKED:** do not scale without matched strong-backbone utility/cost superiority.

`production_activation=false`, `all_scientific_blockers_closed=false`, `global_continuum_certified=false`; leave this Draft/unmerged. Do not discard the #4524 actual-debt 1e-6 refusal or #4528 identity failure witness.
