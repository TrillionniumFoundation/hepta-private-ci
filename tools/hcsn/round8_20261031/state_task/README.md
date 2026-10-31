# History compression and future event risk

This is a new **synthetic, known-model functional experiment**, not a claim
that the old finite OU cell has become a continuous diffusion or that a new
spiking architecture is necessary. All predictors receive the same causal
sensor increments, durations, sensor noise and future-query parameters.

## Task and information contract

A latent drift takes values `{-0.8, 0, 0.8}` with public prior `{.3, .4, .3}`.
An observed increment satisfies `dy = drift*dt + sensor_sd*sqrt(dt)*noise`.
After the observation history, a **new independent Brownian path conditional
on that drift** starts at a specified distance from a future affine boundary.
The target is its conditional first-hit probability over a specified horizon.
The sensor history is not an absorbed path, so no unmodeled survival evidence
is discarded.

Two accumulated statistics suffice:

\[
A=\sum_i dy_i/s_i^2,\quad B=\sum_i dt_i/s_i^2,\quad
\pi_j(A,B)\propto\pi_j(0)\exp(\mu_j A-\mu_j^2B/2).
\]

The analytic predictor computes `sum_j posterior_j * F_j` with the Brownian
first-hit formula. A five-parameter trainable calibration adjusts the two
statistic scales and three prior logits. The ordinary exact control uses the
same public model and two accumulators without a spiking cell or fitted
calibration. It does not receive a hidden drift label, an already computed
posterior, or stored teacher components.

The ordinary learned controls are a sufficient-statistic MLP, a 24-state GRU,
and a memoryless MLP. Their heads have two 48-unit tanh layers. The memoryless
model is an ablation; the exact ordinary filter is the crucial strong
same-information control. All trained arms use 800 Adam steps, batches of 256,
the registered learning rate, three seeds and development-only selection.
The teacher supplies exact known-model probabilities equally to all trained
arms. This is not an unknown-dynamics or model-free learning experiment.

## Freeze and the recorded protocol deviation

Training used 3,072 examples and development used 768. Twelve checkpoints were
trained, serialized and hashed in `FREEZE.json`, with 31.871 CPU seconds of
recorded fitting/selection/export time. All models remain unchanged.

A numerical unit test generated the original low-noise and moving-boundary
confirmation seeds before freeze, comparing only the teacher against the
stable independent kernel. This violated the literal generation-order rule.
`CONFIRMATION_AMENDMENT.json` preserves this deviation and registers new seeds
for **all four** confirmation regimes. Amendment, evaluation source and the
checkpoint hash manifest were published at commit
`6eaebb947bb6e2731423254601b5825fdc69ddcb` before replacement generation.
The final 8,192 confirmation examples use seeds `191001..191004`.
No original confirmation predictions were used for fitting or model selection.

## Frozen confirmation results

Entries are mean probability MSE / mean expected protective-action regret
over the three separately executed frozen fits. No unpriced prediction
ensemble is deployed. Protection costs are public; protection pays its cost,
while inaction incurs a unit loss if the queried event occurs.

| Predictor | IID | Longer history | Low noise | Moving boundary |
|---|---:|---:|---:|---:|
| Analytic filter | 2.24e-15 / 0 | 3.50e-15 / 0 | 7.12e-15 / 0 | 5.29e-16 / 0 |
| Ordinary sufficient MLP | .000732 / .000388 | .002212 / .001154 | .008967 / .006017 | .002545 / .001336 |
| Ordinary GRU | .001339 / .000797 | .003123 / .001847 | .010491 / .007657 | .002459 / .001228 |
| Memoryless MLP | .028206 / .019804 | .046422 / .031727 | .043316 / .027212 | .008916 / .003850 |
| Ordinary exact filter | 2.20e-15 / 0 | 3.49e-15 / 0 | 6.86e-15 / 0 | 5.70e-16 / 0 |

History and the correctly specified risk operator have a real task function
in this fixture. The near-zero analytic error is expected from knowing the
generative model; it is not evidence of discovery of an unknown physical law.
The ordinary two-statistic filter duplicates that function. Consequently this
experiment does **not** establish task necessity or architectural novelty of
spikes. The learned controls' errors do not prove a lower bound for all GRUs,
MLPs, training budgets, or distributions.

## Costs and the computed comparison gates

`cost_analysis.py` accepts only deployable inputs and includes conversion of
the complete history, inference, decision and JSON output. Each batch contains
2,048 queries; scalar measurements use 64 separately executed queries, with
balanced randomized model order. Times are descriptive CPU measurements in
this environment, not hardware energy or an entire Hepta application.

| Predictor | Batch CPU / episode | Scalar CPU / episode | Mean standalone training/setup CPU |
|---|---:|---:|---:|
| Analytic filter | 1.119 us | 210.154 us | 1.332 s |
| Sufficient MLP | 1.266 us | 156.060 us | 1.198 s |
| GRU | 10.639 us | 385.078 us | 6.966 s |
| Memoryless MLP | 1.146 us | 157.849 us | 1.380 s |
| Ordinary exact filter | 1.148 us | 193.973 us | .000035 s |

The exact ordinary control passes both registered quality margins on all four
regimes and is cheaper in the scalar workload. Its measured batch CPU is
slightly higher; that batch cost gate is explicitly **false**, and timing
noise is not converted into a universal ordering. At the registered compute
price, its zero fitting cost also matters for finite deployment horizons.
`evidence/cost_and_gates.json` records every cost, gate and amortization row.
These quality gates compare recorded seed means with the registered margins;
they are not confidence-interval noninferiority tests. The Boolean execution
cost gate excludes training. Including the stated fitting/setup amortization,
all 32 comparisons against the exact ordinary filter favor that control at
the four registered deployment horizons, in both workloads and all regimes.
This is a statement about the registered CPU-price model, not an absolute
economic or hardware-energy cost claim.

The original evaluator's benchmark included conversion of an unused target
tensor. It remains in `confirmation.json` with its true scope; the new
query-only measurement is separate. This did not expose target information to
model inference. Native journaling, durable recovery, engineering labor and
energy are outside this functional experiment; the native-owner track measures
its own complete execution fixture.

Episode bootstrap intervals condition on these three frozen fits. They are
descriptive, not a confidence guarantee over arbitrary training randomness.

## Reproduction

Restore the lossless evidence first from the repository root:

```sh
python -m tools.hcsn.round8_20261031.bundles restore state_task
python -m unittest tools.hcsn.round8_20261031.state_task.test_task -v
```

Historical sources, seeds and checkpoints are retained. `train.py`,
`confirm_data.py` and `evaluate.py` refuse to overwrite their relevant frozen
outputs. For a fresh reproduction use a separate checkout/output copy; keep
the registered records intact. The recorded numerical/data environment used
NumPy 2.3.5 and SciPy 1.17.0; fitting and predictor timing used CPU PyTorch
2.9.1 with NumPy 1.26.4 and one Torch thread.
