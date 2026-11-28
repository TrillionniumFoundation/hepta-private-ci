# Finite observation windows and measured spike counts

The history and reset of an absorbing process allow an exact finite-window count operator. For initial and reset distance 1, fixed refractory duration d and horizon T, its mean count is the sum of first-passage probabilities from distances j at horizons T−(j−1)d over positive horizons. Here each specimen's physical drift was fitted to its observed input current, using the original within-cell training and withheld-current splits. We independently fitted a stationary approximation in the same bounded parameter domain. Both the fixed-noise and the fitted-noise finite variants are reported. Training fits for all 108 specimens were frozen before this analysis read any held-out count. Other analyses have previously used these cohorts.

| Mean cell absolute error, spikes per original sweep | 72 summary specimens, 174 held levels | 36 NWB specimens, 219 held levels |
|---|---:|---:|
| Stationary renewal, this protocol | 5.0581 | 1.8123 |
| Finite-window renewal, fixed noise | 4.9958 | 1.8288 |
| Finite-window renewal, fitted noise | 4.8830 | 1.8706 |
| Original LIF comparator | 4.4443 | 1.8021 |
| Original softplus fit | 4.1645 | 1.4936 |
| Original adjacent-current interpolation | 3.7175 | 1.3313 |
| Original QVI response | 8.2408 | 9.0176 |

Fitted-noise finite minus matched stationary gave −0.1751 counts per sweep on the 72-cell cohort, with a paired-specimen 95% interval [−0.3298, −0.0318]. On the independent 36-cell cohort it was +0.0582 [+0.0048, +0.1273]. Fitted-noise finite minus interpolation was +1.1655 [+0.2213, +2.2405] and +0.5393 [+0.0774, +1.1612]. The finite-time correction does not improve both cohorts. The original project also fitted a more permissively parameterized asymptotic curve with more starting points and reported errors of 4.3591 and 1.5563. The stationary fit in this comparison follows the common bounds in its own protocol. Neither biological-count experiment uses the monetary price channels, which requires separate evidence about cellular mechanism.

All four analytical derivatives of finite count were checked against centered differences (largest absolute error 1.16e−9). For noise and drift there is a voltage scale ambiguity; fixing the initial/reset distance identifies that scale convention. Fit convergence, parameters, training errors, all withheld currents and counts, paired predictions and rates are preserved. Interpolation uses the same cell's nearby known current levels and does not measure transfer to a new specimen.

Retrieve the two input archives at commit d20c92c160c731b320b1426d76481222cbef43a0, under qualification/hcsn_research_20261127/feedback/ephys, into a local data subdirectory, then run `OPENBLAS_NUM_THREADS=1 python finite.py`. The summary records the hashes of each ZIP. [Original cohort comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fff9a90720deaf848ad30991158f2b6180e61f4f/qualification/hcsn_frontier_20261127/continuum/ALLEN_RESULTS.md)
