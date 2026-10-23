# T9 retained-cost decomposition

T9 actually exited 2, selection_ready=false and test_opened=false. This audit uses only retained selection/build receipts; no model or dataset was loaded and no measurement was rerun. It does not replace the negative outcome.

## Exact mean decomposition

| Contribution to NC minus N complete CPU-net utility | Value |
|---|---:|
| NC full-view content minus N full-view content | -0.003729004304 |
| Continuation minus full on the same NC weights | +0.001311078897 |
| Service CPU-price contribution | +0.000531911743 |
| Complete build CPU amortization contribution | -0.000207816414 |
| Preparation CPU amortization contribution | -0.000000422057 |
| Reconstructed total | -0.002094252134 |
| Recorded readiness contrast | -0.002094252134 |

The identity closes within 4e-16. The raw NC-versus-N gap is −0.002417925406; complete CPU pricing improves it by +0.000323673272, leaving the failed −0.002094252134 contrast. Routing helps on NC weights, but does not offset their full-view content gap. All three frozen random probabilities equal 1, so the cheaper one-pass random comparator is always-full and agrees with NC-full raw utility up to floating-point rounding.

| Seed | Content gap | Routing gain | Complete CPU contribution | Complete net | N/NC updates | Decision price | Continue fraction |
|---|---:|---:|---:|---:|---|---:|---:|
| 11 | -0.000783300 | +0.000982583 | +0.002183056 | +0.002382339 | 386/367 | 0.000000000000 | 0.657986 |
| 23 | -0.003747436 | +0.000066547 | +0.000994238 | -0.002686651 | 386/367 | 0.000000000000 | 0.690972 |
| 47 | -0.006656277 | +0.002884107 | -0.002206274 | -0.005978444 | 386/367 | 0.000589021155 | 0.643229 |

N/NC mean complete service CPU is 87,683.189236/85,113.992766 ns per request. Their declared service work is 19,236/20,745.59375 units per request: the measured CPU saving is not an operator-work saving. NC build CPU is 6.158979821s versus N 5.857846482s; the complete cost difference is fully amortized at the unchanged H=100,000 and price=0.02. Per-seed preparation/build/service costs and all three raw paired calibration deltas are retained in cost-decomposition-audit.json; negative medians and their zero-clamped prices remain visible.

## Budget constraint

| System | Actual CPU / 10s | Operator units / 12B | Selected updates (each seed) | Unused units |
|---|---:|---:|---:|---:|
| additive | 5.911573597 | 11960164047 | 387 | 39835953 |
| anchor | 5.337372386 | 11960455809 | 396 | 39544191 |
| ndu | 5.857846482 | 11963868465 | 386 | 36131535 |
| ndu_control | 6.158979821 | 11912037540 | 367 | 87962460 |
| supervised | 5.652317297 | 11960455809 | 396 | 39544191 |

All 45 candidate update counts exactly equal floor(their frozen candidate unit cap / actual step quote). N has only 1,101,327 candidate units left against a 2,307,106-unit next update; NC has 491,897. For all N/NC candidates, even conservative guards based on the saved maximum step leave at least 0.091596/0.275244s CPU headroom. Their 386/367 update difference is therefore an operator-allocation constraint, not an actual CPU-cap failure. It is consistent with a training-content tradeoff but does not by itself prove what another update allocation would achieve.

No system executed a residual refinement round. N needed 168,865,158 units for one full three-seed round plus required changed-model validation and tail, but had 109,911,951 (deficit 58,953,207). NC needed 529,117,611 but had 504,427,077 (deficit 24,690,534). Conservative first-round CPU forecasts from saved maximum steps were 6.238341/6.683920s, both below 10. Unused final units reflect indivisible updates and required future work; reserved work was not charged as executed padding.

## Actual numerical runtime

The same-process environment receipt records one actual OpenBLAS thread and one observed process task, OpenBLAS 0.3.30 pthreads/SkylakeX, NumPy 2.3.5, Python 3.12.14 and affinity [0,1,2,3,4]. Python/NumPy paths and the BLAS path/version/SHA match P1; BLAS SHA256 is ee2039cf13a45e1e89f04d0cea9585657d93ffaa425594e1935161013fdf4e12. Trace/profile are inactive; errors are empty. These are boundary observations, not proof that no transient thread ever existed.

Runtime sampling took 0.037795484s CPU. Frozen run.py starts the complete CPU clock before sampling and later replaces common.cpu_seconds with that full elapsed cost; this sampling was charged in full to every system through shared common preparation. The environment and common numerical-runtime receipts match exactly.

The current blocker is the negative complete CPU-net validation mean. The positive content/routing validation means, zero budget violations, greedy-retention and decoder-corruption checks do not constitute heldout acceptance; formal test remains unopened. Further operator-saving implementation work must retain the base’s exact dense500 training, actual costs and unchanged gates. No further runtime probe is implied by this audit.
