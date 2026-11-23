# Delayed renewal with signed release marks, independent reference

The recorded initial state is a positive distance x from a fixed absorbing boundary. Between releases it follows dX = μ dt + σ dW. Each hit holds its incoming two-vector unchanged for one deterministic interval d. At release the path restarts at a and its column-vector mark changes to Rm. The calculation always starts from the declared source and imports no HCSN product code.

For generation n ≥ 1, L = x+(n−1)a is the first-passage distance, h = T−nd is the time available after all n completed holds, and f_L is its drifted Brownian first-passage time density. The active positive point or bin contribution integrates f_L(s) times the positive absorbing transition from a at h−s over 0<s<h. A change s = h sin²(πu/2) resolves both time endpoints. The finite interval and tail probabilities integrate the positive Gaussian density times its absorption factor over the requested y range at every time node. The Gaussian space rule truncates outside 39 standard deviations; that total normal tail is smaller than half the smallest positive binary64 subnormal. The raw finite probability arrays are never normalized. Binary64 values below representable magnitude are outside the relative accuracy claim.

The remaining-time phase bin [l,r] in units of d uses τ_L ∈ [max(0,h+ld), h+rd] whenever the upper endpoint is positive. The cumulative and rate of hit n use T−(n−1)d, and both carry the (n−1)-release mark. Active component n carries Rⁿm₀. Since all these cases have x>0 and horizons strictly between delay multiples, the choice of boundary ownership for deterministic atoms is not measured here.

The lower and higher time/space Gauss orders are 128/20 and 256/32. The main reference integrates positive densities. Further checks use the analytic first-hit CDF for each generation's mass accounts and 62-decimal-digit de Hoog inversion of separate x and a first-passage transforms times the killed resolvent at six points. The inverse Laplace check includes y=a, both sides of the reset, four releases at T=.61, and the rare short-horizon branch. Derivatives are five-point centered differences at steps 2e-5 and 1e-5 for the declared scalar objective. That objective excludes point densities and involves only bins, emission totals and rates. FD checks do not probe a moving query at the y=a spatial kink.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python reference.py --output result-replayed.json --timing timing-replayed.json
```

The canonical result keeps the compute time in its separate receipt. To compare exact bytes on the recorded runtime, use `cmp result.json result-replayed.json`. The physical and mark parameter order, bins, horizons and objective weights are in protocol.json. Array dimensions and ordering are described below.

| Key | Axes |
| --- | --- |
| active_by_release | Number of completed releases beginning at 0, then six increasing active bins including the upper tail |
| density_by_release | Number of completed releases, then the configured physical y points |
| phase_by_hit | Hit number beginning with the first row for hit 1, then three increasing residual-time bins |
| event_probability_by_hit / event_rate_by_hit | Hit number beginning with hit 1 |
| marks | Number of preceding releases, then two signed components |
| P / C | Six active bins followed by three phase bins, with C carrying two additional signed components |
| density / density_content | Physical y points, plus two components for the latter |
| marked_cumulative_hits / marked_event_rate | Two signed components |
| objective_fd | Twelve named source, physical or mark parameters at the two declared differences |

The rare case uses four active bins including its tail, with the edges and two point queries in protocol.json. Per-generation marked active or phase quantities are reconstructed by multiplying each recorded generation's analytic probability or positive density by its corresponding recorded mark.
