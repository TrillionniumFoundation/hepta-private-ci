# HCSN P0: all-node exact-rational Rannacher debt error audit — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO; no production activation.** Additive follow-up stacked on exact #4530 HEAD `81b944aa019801e51abf1211b6aa02108479776a`. Original He–Xiong financial formulas, original debt-PDE, independent first-hit oracle, historical negative trials, and production/CI files are not changed.

## What the new result proves (strict, finite-grid only)

The existing #4530 work established strict physical error improvement for **six posthoc-selected nodes**, not the entire grid. The new `rannacher_all_node_certificate.py` independently evaluates the true fixed-barrier representative-bond price via exact-rational Brownian first-hit time-density enclosures at **all** grid nodes. It computes two error intervals, for the original Backward Euler (BE) and Rannacher–Crank–Nicolson (RCN) fixed-barrier debt PDE respectively. All binary64 PDE results are treated as exact rationals when compared to the true interval. The oracle imports neither HX bond Eq.(8), endogenous boundary Eq.(12), equity Eq.(A7) nor their financial Green resolvent.

At every node `i`, the independent true value obeys `L_i<=B_true(y_i)<=U_i`. Therefore for a computed PDE value `z_i`, its true error is between `max(0,L_i-z_i,z_i-U_i)` and `max(|z_i-L_i|,|z_i-U_i|)`. A finite **all-node strict win** is certified only when

```
max_i upper_error_RCN(i) < max_i lower_error_BE(i)
```

The algorithm never samples only favorable nodes: it first encloses all nodes at tolerance `0.002`, then adaptively refines the widest/witness candidate intervals at tolerance `0.00005`. Refinement uses estimated midpoints **only to select work**, never for the proof itself. If any oracle call fails, node count is incomplete, physical input fails, a resource cap is hit or the strict inequality cannot be established, the algorithm refuses or returns `INCONCLUSIVE_NOT_CERTIFIED`.

## Actually executed two 101-node/250-step regimes

Source context: local Python 3.13.5, SciPy 1.17.0, reconstructed `HX` dataclass/boundary subset from an older exact numerical reference; the three relevant numerical sources `first_hit_time_interval.py`, `hx_bond_pde_independent.py`, and `hx_bond_pde_rannacher.py` match exact ancestor remote Git blobs `31cf96c1381e5340321339dc071799ce4ced7eba`, `ad6262821e9a63e5a7f1a8dd8e39e3c020d7a815`, and `8afd308bbcc74ae4392b4be1dc593d97ff1b3333`. Thus **no full main-branch checkout or whole-repo CI** is claimed.

| Financial regime | Nodes / time steps | Certified BE max error LOWER | Certified RCN max error UPPER | Strict margin (BE lower minus RCN upper) | Refinements | Canonical panel SHA256 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| HX sale_fraction=0.015 | 101 / 250 | 0.005975877803450799 | 0.003560565569059512 | 0.002415312234391287 | 38 | `7279b14252698334da9a1d98d679a6b18e10bb9acb1dfcbe6d401124f9e72171` |
| HX sale_fraction=0.2 | 101 / 250 | 0.011306436296890474 | 0.010752872762559866 | 0.0005535635343306075 | 36 | `456a83edbada7bc98559b934bc6266b5e4c43188bf750bec20a53098064612b1` |

These strict margins are **guaranteed only for the exact binary64 physical inputs and all 101 *sampled* spatial nodes** at the specified maturity and finite PDE meshes, conditional on the existing independently proved first-hit interval routines. This does not imply an all-spatial-positions inequality or global financial default policy. The high-liquidity original HX negative-equity obstacle witness remains valid, and **is not fixed by debt-PDE error improvement**.

## Prior six coarser interval panels are not a valid full-grid superiority proof

Before tightening intervals, re-evaluating the six retained #4524 all-node rational bound panels against actual RCN output gives (RCN maximum error upper, BE maximum error lower):

- sale=.015, 101: (0.04141645, 0.00002282), 201: (0.04279428, 0.00001141), 401: (0.04293574, 0.00000571).
- sale=.2, 101: (0.09606351, 0.00666449), 201: (0.09935274, 0.00333403), 401: (0.09948511, 0.00166746).

**None of those coarser certificates proves full-node superiority.** Hence the new fully regenerated, refined, strict 101-node proofs are substantive and cannot be inferred from the six selected probes. All prior evidence stays intact. An attempted fully regenerated 201-node panel exceeded a single 180-second local execution limit: **recorded as incomplete, not a passed scientific test**. 201/401 RCN all-node strict error comparisons are still open.

## Exact local test and reproduction

```sh
# Local runtime with NumPy/SciPy and original research ancestors:
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_rannacher_all_node_certificate

# Reproduce directly as two independent full 101-node calls:
python - <<'PY'
from fractions import Fraction as F
from experiments.hcsn_hx_unified_v3.hx import HX,boundary
from experiments.hcsn_hx_unified_v3.rannacher_all_node_certificate import audit_rannacher_all_nodes
for sf in (.015,.2):
    p=HX(sale_fraction=sf)
    result=audit_rannacher_all_nodes(p,boundary(p),nodes=101,time_steps=250,
        first_tolerance='.002',refine_tolerance='.00005',max_refinements=80)
    print(sf,result.status,result.canonical()['canonical_sha256'],
          float(F(result.be_max_error_lower)),
          float(F(result.rannacher_max_error_upper)))
PY
```

The **two actual 101-node solver runs** were executed independently (roughly 30 seconds each in the local CPU environment). The five lighter test methods passed (5/5, no skips) in 1.887 CPU environment wall seconds: coarse-result NO_GO, identical solver negative control, full ten-parameter SHA256 identity sensitivity, forced oracle failure and invalid parameter/cap refusal. The combined six-method test command is supplied for independent replay; **not** reported as a new full-repository CI pass.

Tested new Git blobs were read back exactly:
- full-node solver: `41a84473702c28ce3262e81d6c75ccab0ed5b3a7`;
- test suite: `aedf749a14d0f7079f06e967523a37d31dd65514`.

## Remaining P0–P5 blockers (no closure upgraded)

**P0 OPEN:** endogenous **self-consistent** original HX financial obstacle, full physical equity/debt error budget, continuum and all-admissible-parameter estimates, discontinuous/default corner and active-set gradients, complete real FP32/BF16 financial hardware certification. This audit is only a fixed-barrier debt-PDE finite-grid comparison.

**P1 OPEN (negative/unproved):** registered matched Call/Risk/Margin causal positive gain remains absent; #4517 preserves 192 negative/partial runs, #4527/#4531 identify a rank/identifiability limitation. Do not substitute additional correlated features for independent information.

**P2 OPEN:** learned Selective Copy, MQAR, overwrite, irregular physical time, genuine durable FIRE recovery with OOD positive gains and full costs.

**P3 OPEN:** four genuine text/image/audio/video paired encoder training and noise/temporal OOD.

**P4 OPEN:** native Rust/GPU kernel, 64/256/1024/4096 Cell real throughput, CPU/GPU/RSS, p95/p99, Joules, faults and authentic host recovery.

**P5 BLOCKED:** equal-token/data/FLOPs/hardware quality-and-total-cost net advantage over tuned ordinary gate, Transformer and SSM.

Do not mark `global_hx_equilibrium_certified`, `all_scientific_blockers_closed`, or `production_activation` true.
