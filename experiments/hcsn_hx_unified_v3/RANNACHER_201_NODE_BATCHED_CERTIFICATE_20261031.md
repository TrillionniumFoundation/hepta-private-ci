# HCSN P0: 201-node exact-rational Rannacher all-node certificates — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** This increment is stacked on exact #4535 HEAD `9681bda7fa3359854cb8ed7a232dfe0848bf1e23`. It adds no change to the original HX financial formulas, the PDE solvers, historical negative evidence, CI, production routing or native owner.

## Result

The previously incomplete **201-node / 500-time-step** fixed-barrier debt-PDE all-node comparison has now been completed for both registered financial regimes. Each panel has exactly 201 independently enclosed true debt prices, one per spatial grid node. The computed BE and Rannacher binary64 outputs are compared as exact rational values against the same exact-rational first-hit price interval.

| sale_fraction | nodes / time steps | BE maximum-error LOWER | Rannacher maximum-error UPPER | strict all-node margin | refined nodes | runtime |
|---:|---:|---:|---:|---:|---:|---:|
| 0.015 | 201 / 500 | 0.0027705151829239575 | 0.002041176661915313 | **0.0007293385210086448** | 80/201 | 23.10 s |
| 0.2 | 201 / 500 | 0.004309330439710794 | 0.0035614361778736354 | **0.000747894261837158** | 80/201 | 23.28 s |

Both satisfy the complete finite-panel inequality:

`max_i upper_error_Rannacher(i) < max_i lower_error_BE(i)`.

All 201 nodes are present in each canonical record, with no favorable-node selection. The 80 refined nodes per panel were selected by a batched deterministic work-priority rule: refine the current maximum BE lower-error witness and the four largest unresolved Rannacher upper-error candidates per round, for 16 rounds. The remaining 121 nodes retain their valid, coarser `.005` exact-rational intervals. Refinement order affects tightness/work only, not the validity of any node enclosure or the all-node inequality. Every interval remains bound to the same physical parameters, candidate boundary, grid and time mesh.

## Canonical and raw evidence identity

| sale_fraction | canonical science SHA256 | raw JSON SHA256 |
|---:|---|---|
| 0.015 | `fbf95d10447a6ffae02b4a158b74597a19a20021a7862e2fcf94206dcefdaff4` | `b968a9fb9254cf8ecd520327b4c089e96c0563444c8931a6bc89744464f97271` |
| 0.2 | `cdb2a90ceffb17436c01d1a5bb30b2100f69066f31c7c2750fa465e5044626bd` | `4fd5b3b3e161b486f3e1ccae33033e6eb6da133534402fa02844fb1675cbc788` |

Canonical SHA256 is computed using the exact `AllNodeResult.canonical()` contract in #4535, over the 201 exact rational rows and scientific status fields. Raw JSON additionally records the parallel work schedule, worker count, refinement indices, runtime and exact source identities. All 201 indices are unique and contiguous; an independent readback recomputed both maximum error bounds from the stored rational strings and verified the strict inequality.

Exact numerical source Git blobs used by the local run were independently verified:
- all-node certificate `41a84473702c28ce3262e81d6c75ccab0ed5b3a7`
- first-hit interval oracle `31cf96c1381e5340321339dc071799ce4ced7eba`
- BE debt PDE `ad6262821e9a63e5a7f1a8dd8e39e3c020d7a815`
- Rannacher debt PDE `8afd308bbcc74ae4392b4be1dc593d97ff1b3333`

## Reproduction

The two raw canonical records are provided as separately downloadable conversation artifacts; their raw SHA256 values are above. The numerical run used five local CPU worker processes. The proof oracle remains the exact-rational first-hit interval implementation; parallel scheduling changes only execution order.

## Strict scope and remaining blockers

This closes **one bounded P0 numerical subgate only**: for the two stated fixed financial barriers and exact binary64 physical inputs, the Rannacher finite-maturity debt PDE has a strictly smaller maximum absolute error than BE across every one of the 201 sampled spatial nodes at 500 time steps.

It does **not** establish:
- the self-consistent coupled He–Xiong debt/equity/default-boundary equilibrium;
- a continuum-in-space or continuum-in-time error certificate, all-parameter admissibility, or global equity obstacle optimality;
- the maturity/default corner and every far-field uncertainty term over all admissible regimes;
- certified FP32/BF16 financial kernels, active-set derivative enclosures, or GPU execution;
- P1 Call/Risk/Margin causal superiority; P2 trained memory/OOD/crash recovery; P3 genuine four-modal alignment; P4 native GPU/energy/4096-Cell production performance; or P5 equal-budget hybrid net benefit.

The 101-node strict proofs in #4535 remain unchanged. The previously timed-out serial 201-node attempt is superseded by this completed, independently reproducible batched run; no tolerance was relaxed below the registered coarse interval tolerance, no row was omitted, and no failure was relabeled. Both result records explicitly keep `complete_continuum_hx_certification=false`, `all_scientific_blockers_closed=false`, and `production_activation=false`.

**Admission remains RESEARCH_ONLY / DENY_ALL / NO_GO.** Keep this PR draft and unmerged.
