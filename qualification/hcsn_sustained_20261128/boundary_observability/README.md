# Sharp recovery limits for continuous boundary signals

A receiver can predict a specified next-step firing mass from a finite set of continuous first-passage queries. The absolute error depends on the geometry of the queries, the size and direction of the next boundary displacement, and sensor precision. On 64 live atoms with a −0.175 log-margin shock and componentwise sensor error at most 0.001, the best possible worst-case error falls from 0.50000 for a fixed boundary alone to 0.07089 for the four existing HCSN horizons. Eight horizons give 0.05734. Four horizons plus four probes with shifted boundaries give 0.05067. These conclusions are for arbitrary live initial populations on the declared grid. Reachable populations for a particular trained network or dataset can have smaller errors.

## Minimax results

The numbers are probabilities. The radius is the largest remaining unavoidable ambiguity for the best possible decoder, up to the stated numerical tolerances. Each four-column tuple below gives perturbations −0.175, −0.075, +0.075 and +0.175 in that order. Negative shifts bring live mass closer to the absorbing boundary.

| State information transmitted | Noiseless observations | Componentwise error up to 0.001 |
|---|---|---|
| Fixed common boundary only | 0.50000, 0.50000, 0.20465, 0.04358 | 0.50000, 0.50000, 0.20465, 0.04358 |
| One first-passage horizon | 0.42705, 0.22327, 0.02612, 0.01141 | 0.42818, 0.22440, 0.02658, 0.01151 |
| Existing four horizons | 0.05108, 0.02587, 0.00193, 0.00115 | 0.07089, 0.03293, 0.00245, 0.00148 |
| Eight horizons | 0.02344, 0.02179, 0.00035, 0.00029 | 0.05734, 0.03089, 0.00100, 0.00058 |
| Four horizons and four shock probes | 0.02921, 0.01391, 0.0000154, 0.00000186 | 0.05067, 0.03199, 0.00118, 0.00090 |

For the four existing horizons, the decoder for the first, noisy example has intercept −0.05127 and coefficients (6.20368, −9.31705, 3.89525, 0.39794). The two extremal populations produce allowable observation boxes meeting at their midpoint. Their firing probabilities differ by 0.1417853. Because either state can produce the same readout, even a nonlinear receiving network incurs error at least half that difference for one state. The displayed affine decoder attains the upper bound. Computing the weights is a direct convex solution for this specific first-passage readout. It has no global language-model training objective.

All 180 grid, port, shock and precision combinations include the affine decoder and both extremal probability populations. A second physical host independently evaluated the entire set using scalar Python `math.erfc` and Torch CPU contractions. The largest difference between recovered witness bounds or independent evaluations was 4.52e−7; the largest constraint excess was 6.79e−10. The receiver was tested on 8,192 fixed random population vectors per cell. No sampled error exceeded the analytic upper bound. The populations repeat across conditions on each grid, so this is 24,576 distinct random states. The independent replay took 0.45 s on the specified host, excluding Python startup and original LP solves.

The older sustained CREMA-D experiment was read separately from its native process and immutable progress checkpoints. At 09:04:38 ET on 2026-11-28 all twelve cells had crossed 1,000 active optimization seconds; cumulative persisted training was 12,360.32 s and 338,559 updates. Mean development NLLs were 2.52692 (smooth), 2.66652 (literal), 2.88696 (LIF), 3.70948 (causal attention). The original source computes gate-specific aggregate cold scores and stores per-clip scores for each best checkpoint. The stricter #7264 collector was absent from the running code and archive path. A subsequent gate replay can be authenticated against final weights and the recorded aggregate, while only first-observation bytes can establish original per-clip custody. This observation predates the final cold seal.

## Reproduction and hardware

Run the pure SciPy solver and the independent numerical check:

```bash
python observability.py --device scipy --out witnesses.json.xz
python independent_replay.py witnesses.json.xz independent.json --device cpu
```

The archived uncompressed JSON SHA-256 is `dd2460497e8312a6a484aa4fb305dd3109740cc67e159af0e14ac715f7d63988`. Exact optima can admit multiple extremal populations, and solver versions can return different valid witnesses with the same bound. The supplied independent replay checks both constraints and sharpness directly.

The HeptaRuntime survey found one Colab account and one Kaggle account ready out of six account/platform combinations. The single selected Colab request first returned an assignment read timeout. Later inspection of the original request confirmed an owned runtime, and the same run bound a kernel and submitted the program once. The adapter then reported an unconfirmed remote outcome and FileNotFoundError during status reads. Source, original request and kernel-job identity are retained. The completed checks in this chapter are the CPU solve and independent native CPU replay; no confirmed CUDA result or resource-release receipt has been recovered. See [the retained provider observation](cloud_observation.json), [native training status](original_run_observation.json), [numerical replay receipt](independent.json), [all optimizer witnesses](witnesses.json.xz), and [the derivation and fixed conditions](PROTOCOL.md).
