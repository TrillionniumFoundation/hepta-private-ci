# HCSN P0: independent finite-maturity debt PDE and equity obstacle (2026-10-31)

**Research-only / DENY_ALL / NO_GO.** Additive increment stacked on PR #4498, exact parent 7a9dd0a918feaf986c70101fd7006af44afb6afc. Original HX Eq.(8)/(12)/(A7), historical negative evidence, P1-P5 models and production/CI files are unchanged.

## Independent mathematics

- hx_bond_pde_independent.py solves the time-to-maturity parabolic financial bond PDE with backward Euler, a positive-jump-rate generator and an M-matrix tridiagonal solve. It retains finite-maturity surviving principal at the upper boundary, and explicitly preserves the incompatible default/maturity corner. It never calls HX bond Eq.(8), reflected first-hit probability, SciPy density quadrature or the mpmath time integral.
- hx_joint_pde_obstacle.py takes the independently computed PDE debt values and solves the stationary equity obstacle using a separate SciPy banded policy iteration, with no call to closed-form HX equity, smooth-fit Eq.(12), or the earlier Thomas/Howard obstacle solver.
- hx_financial_mesh_gate.py compares independent *PDE bond + equity obstacle* versus *Brownian density bond + equity obstacle* for 101, 201 and 401 nodes, refusing any STOP/CONTINUE discrepancy. Agreement on tested meshes never means globally certified optimality.
- Three new test files cover maturity corner, positive-rate upwind drift, numerical refinement, invalid inputs and resource caps, high-liquidity extra-STOP disagreement and strict NO_GO gate.

## Executed local tests

Run these two new suites from repository root:

~~~sh
python -m unittest -v \
 experiments.hcsn_hx_unified_v3.test_hx_bond_pde_and_joint_obstacle \
 experiments.hcsn_hx_unified_v3.test_hx_financial_mesh_gate
~~~

**15/15 new methods PASS** (zero skipped); **33/33 total targeted methods PASS** including the prior 18 inherited P0 methods, on Python 3.13.5 / NumPy / SciPy / PyTorch CPU. This is a local reconstructed HX reference subset with the tested v2 far-field correction, **not** a full byte-identical upstream checkout, complete repository CI, or GPU run. The five new GitHub source/test blobs were read back byte-identical to the tested local files.

## Numerical observations (fixed-b diagnostics only)

The fixed financial default candidate b is taken from the separately implemented algebraic HX smooth-fit Eq.(12) and supplied externally; the PDE does not compute or certify that candidate.

| Sale fraction | Candidate b | PDE bond max absolute error 101x250 | 201x500 | 401x1000 |
|---|---:|---:|---:|---:|
| 0.015 | 64.6251766753 | 0.002632219 | 0.000818546 | 0.000311632 |
| 0.2 | 101.324028609 | 0.019926564 | 0.007847557 | 0.003191572 |

Errors compare the independent bond PDE to separate financial bond Eq.(8) at asset/b ratios 1.001, 1.05, 1.5, 3, 10, with log_upper=5. Under the coupled mesh/time refinement listed, each error series decreases. Discrete PDE time residual below 1e-10 in these cases is not a continuum or roundoff certificate.

| Sale fraction | Mesh | Debt PDE + financial obstacle | Density-quadrature debt + obstacle | Outcome |
|---|---:|---:|---:|---|
| 0.015 | 101 / 201 / 401 | No extra STOP | No extra STOP | Tested mesh agreement only |
| 0.2 | 101 | No extra STOP | Extra STOP to 105.03814665 | **Disagreement -> NO_GO** |
| 0.2 | 201 | Extra STOP to 103.16437455 | Same | Bounded mesh agreement |
| 0.2 | 401 | Extra STOP to 104.09704464 | Same | Bounded mesh agreement |

A coarse financial PDE grid demonstrably misses the high-liquidity exercise strip despite a small discrete Bellman residual. This failure is retained, and no P0 grid stability gate is closed. Higher-resolution agreement is insufficient for a uniform continuum or full endogenous-financial-equilibrium theorem.

At the explicitly inconsistent default/maturity corner the convention is default precedence: B(barrier,0)=recovery*barrier/maturity, while the right-side terminal payoff for strictly positive distance is principal/maturity. This is genuine model boundary incompatibility, not something to silently smooth away.

## Verified published source identities

- Independent bond PDE: ad6262821e9a63e5a7f1a8dd8e39e3c020d7a815
- PDE-driven equity obstacle: 0aea5c12b2e42c6a17277071efc968a9c2981df2
- Cross-method mesh gate: 1d51e2159e485d15be00cab1fe4bfd47868b041f
- PDE and obstacle tests: d3538630faeae3b505c350016affe0a4558a1852
- Mesh gate tests: 5322baf80263e78ab65f6e3f3f4449be7f2b993f

## Exact remaining admission status

P0: **OPEN**, missing self-consistent financial free-boundary, global obstacle domain and discontinuous-case proof, interval/roundoff enclosure, real HX FP32/BF16 numerical/gradient proof. P1: **OPEN**, matched information/slope/active-parameter/total-cost and heldout Call/Risk/Margin causal gain. P2: **OPEN**, learned event memory, Selective Copy/MQAR/overwrite/long-range/irregular time and authoritative crash restore. P3: **OPEN**, true distinct paired four-modal encoders and robust heldout alignment. P4: **OPEN**, Rust/GPU, 64/256/1024/4096 Cell throughput, p95/p99 and real Joules. P5: **BLOCKED**, no same-budget net quality-and-cost advantage has been proven.

production_activation=false; all_scientific_blockers_closed=false. Keep draft, unmerged and without deployment.

## Follow-up: local cell endpoint tolerance correction

The initial gate used the far-field log-grid asset width as an exercise-endpoint tolerance; this could be vastly too permissive near the candidate barrier. A corrective commit now tests endpoint agreement against the **actual local physical-asset cell spacing** based on max(left_stop,right_stop)*expm1(log_upper/(nodes-1)), never the far-field width. One additional regression explicitly rejects a 103-versus-200 stop boundary while accepting 103-versus-104 on the stated mesh. Re-run of all seven focused local modules: **28/28 PASS, zero skipped**. The old source and tests remain inspectable in Git history; all claims remain research-only.

## Independent exact-rational discrete Bellman certificate

The additional source hx_discrete_bellman_certificate.py uses **Fraction.from_float** (the exact rational value of every supplied IEEE-754 binary64 coefficient, debt cashflow and boundary value) to recompute the *finite-dimensional* fixed-endpoint Bellman residual. For positive financial discount r, the normalized M-matrix Bellman map is a sup-norm contraction with gamma=(ql+qr)/(r+ql+qr)<1. Thus the exact discrete map's value distance from the approximate grid is bounded by max-residual/(1-gamma). A STOP or CONTINUE sign is guaranteed for this exact *quantized finite-state operator* only when the local advantage exceeds gamma times the value bound; otherwise it is marked AMBIGUOUS.

At 401 nodes and 1000 maturity steps, the nominal financial regime has 399 guaranteed finite-grid CONTINUE nodes, zero STOP, with sup-error bound about 8.69e-9. For sale_fraction=0.2, it has 2 guaranteed finite-grid STOP nodes (indices 2 and 3), 397 CONTINUE, with sup-error bound about 1.80e-6. Crucially, at 101 nodes the same adverse regime certifies 99 CONTINUE nodes within its **different and coarser finite grid** while the independent first-hit-price obstacle finds an extra STOP. Therefore **even mathematically certified discrete decisions do not certify physical-financial continuum correctness.** This discrepancy remains NO_GO.

Five extra targeted tests include a deliberately corrupted grid whose inflated residual results in ambiguous action classification; the *full local eight-module targeted replay* is now **33/33 PASS, zero skipped**. This is exact rational error accounting **conditional on rounded binary64 problem data**, NOT interval bounds on cashflow construction, PDE time discretization, log-domain truncation, underlying financial process, FP32/BF16 or hardware. The research gate and production activation remain false.

Exact additional Git blobs, read back matching tested local source: source 6d178d708534eb4fa0a16de06008cf48a933f4ca, tests a769789ea35a0883d90484449a7ab21228656a74.
