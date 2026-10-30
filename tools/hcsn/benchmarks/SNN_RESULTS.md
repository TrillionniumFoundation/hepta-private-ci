# Conventional hard-spiking LIF reference

Completed **20 additional training runs**: five seeds on each of the three original v1 synthetic tasks, and five seeds on the unchanged frozen MiniLM/SST features. All runs, validation histories and 20 checkpoints are retained. This closes the conventional SNN comparison gap: a GRU is not an SNN.

The design was recorded in `snn_protocol.json` and communicated before the first SNN training run. There was one architecture, one set of hyperparameters and no test-driven retry. This is a post-declared reference on holdouts already examined by the HCSN experiments, so it is an **exploratory comparison**, not a new independent confirmation dataset or a tuned estimate of the best attainable SNN performance.

## Fixed neuron and training rule

The reference is a single recurrent layer of leaky integrate-and-fire neurons. It follows the general surrogate-gradient training approach described by [Neftci, Mostafa and Zenke (2019), *Surrogate Gradient Learning in Spiking Neural Networks*](https://arxiv.org/abs/1901.09948). The parameters below are our fixed experimental choices, not a claim to reproduce that paper's benchmark system.

Let \(u_t\) be the supplied current input, including the same \(\log(1+\Delta t)\) feature given to the other models. For each neuron,

\[
I_t=W_xu_t+W_rs_{t-1}+b,\qquad
\alpha_t=e^{-\Delta t/\tau_m},
\]

\[
\tilde v_t=\alpha_tv_{t-1}+(1-\alpha_t)I_t,\qquad
s_t=\mathbf1[\tilde v_t\ge1],\qquad
v_t=\tilde v_t-\operatorname{stopgrad}(s_t).
\]

The threshold is one, reset is subtractive, and there is no refractory period. The forward spikes are exactly 0 or 1. One event at most is emitted per neuron per supplied time bin; threshold-crossing time inside a bin is not resolved. The exponential leak integrates the linear leak with current frozen over the bin, not a full event-exact simulation.

Only the backward rule substitutes

\[
\frac{\partial s_t}{\partial \tilde v_t}
\rightsquigarrow
\frac{1}{(1+5|\tilde v_t-1|)^2}.
\]

The reset branch is detached, while the recurrent-spike and readout paths use this surrogate. It is an approximate optimization rule; it is not the true derivative of the discontinuous forward function. Consequently, we do not claim finite-difference agreement between the hard threshold and the surrogate.

The classifier sees only a low-pass filtered spike state:

\[
r_t=e^{-\Delta t/\tau_r}r_{t-1}
+(1-e^{-\Delta t/\tau_r})s_t,
\qquad \mathrm{logits}=W_or_T+b_o.
\]

There is no direct input or membrane-potential readout bypass. Membrane time constants are learned in \((2,20)\), initially four; readout time constants in \((4,64)\), initially sixteen. Trainable bias starts at 1.25, and the recurrent weight initialization has gain 0.1. Initial states are zero.

Width is chosen only by parameter count: **68 neurons, 6260 trainable parameters and 204 persistent state scalars** for synthetic tasks; **50 neurons, 6002 parameters and 150 state scalars** for frozen features. The three state arrays are membrane, previous binary spike, and filtered spike. They are float arrays in this dense JAX reference; no bit-packed or neuromorphic storage advantage is measured.

Every run uses the same 300 Adam updates, batch 32, learning rate 0.003 and global gradient clip norm one as the existing references. The minimum validation cross entropy at 50-update intervals selects the saved checkpoint. The synthetic input width, seed schedules, train/validation/test splits, examples and minibatch indices match v1. Every synthetic split fingerprint was checked against the original receipt before training. The frozen feature SHA is unchanged before and after training: `970c2c56442dc7deaa0e1db98f78b12ab0254a5fae2d45923852055252286a8a`.

## Synthetic results

Accuracy in percent, mean ± sample standard deviation over five seeds. Training uses 32 positions; the long split uses 64. Chance is 25%.

| Task | Train | Validation | Test, 32 steps | Test, 64 steps | Increased noise/missingness |
|---|---:|---:|---:|---:|---:|
| Memory | 25.77 ± 1.18 | 25.86 ± 1.43 | 24.57 ± 1.46 | 26.45 ± 2.43 | — |
| Key/value retrieval | 46.49 ± 1.96 | 43.63 ± 1.43 | 45.74 ± 2.45 | 39.26 ± 3.80 | — |
| Irregular input | 66.38 ± 0.87 | 65.55 ± 1.92 | 66.09 ± 3.28 | 64.26 ± 2.35 | 58.71 ± 0.55 |

The same-data comparison with the original v1 models is:

| Task, 32 steps | LIF SNN | HCSN v1 | Same-structure sigmoid v1 | GRU | Transformer |
|---|---:|---:|---:|---:|---:|
| Memory | 24.57 | 99.84 | 100.00 | 26.56 | 100.00 |
| Key/value retrieval | 45.74 | 29.61 | 29.34 | 48.98 | 100.00 |
| Irregular input | 66.09 | 81.80 | 81.68 | 76.95 | 79.18 |

Under this fixed small budget, HCSN v1 exceeds this LIF reference on training-length memory and irregular-input classification, but the LIF reference exceeds HCSN v1 on key/value retrieval. HCSN v1 does not retain its memory advantage at doubled length: its mean is 14.49%, compared with the LIF reference's 26.45%, and both are inadequate. The ordinary sigmoid counterpart is nearly indistinguishable from HCSN on the tasks where HCSN does well, so these results do not establish an advantage specific to the financial put activation.

Paired HCSN-v1-minus-SNN differences on the 32-step test are +75.27 pp for memory, -16.13 pp for retrieval and +15.70 pp for irregular input. The corresponding nominal 95% t intervals over five seed differences are [73.09, 77.46], [-20.76, -11.51] and [10.51, 20.89] pp. These post-declared intervals are exploratory and unadjusted for multiple comparisons; they do not generalize to every SNN architecture, optimization regime or data distribution.

## Frozen encoder results

The encoder, training-only PCA, data splits and feature rows are identical to the earlier head experiments. Five SNN checkpoints yield **76.20 ± 0.46%** test accuracy and **75.75 ± 0.44%** perturbed-feature accuracy. Mean training and validation accuracy are 83.35% and 79.70%, respectively.

| Head | Test accuracy, mean ± seed SD | Perturbed features, mean ± seed SD |
|---|---:|---:|
| LIF SNN | 76.20 ± 0.46% | 75.75 ± 0.44% |
| HCSN v1 | 74.70 ± 1.13% | 74.45 ± 1.24% |
| Sigmoid v1 | 74.23 ± 1.71% | 74.55 ± 1.35% |
| GRU | 75.18 ± 1.39% | 75.13 ± 1.39% |
| Transformer | 74.53 ± 1.24% | 74.43 ± 0.76% |
| HCSN v2 | 76.05 ± 1.42% | 75.73 ± 1.12% |
| Sigmoid v2 | 76.58 ± 0.56% | 75.93 ± 0.52% |

The SNN's point estimate exceeds HCSN v1 and is close to HCSN v2. The paired HCSN-v1-minus-SNN difference is -1.50 pp, with nominal 95% t interval [-3.09, +0.09] pp. For HCSN v2 it is -0.15 pp, interval [-1.73, +1.43] pp. These intervals summarize training-seed variation on the same 800 examples; they are not complete data-sampling uncertainty estimates. No HCSN advantage over conventional spiking is established here.

The perturbation is 20% **local frozen-feature-block dropout** plus Gaussian feature noise with standard deviation 0.15. The final global-mean block, containing full-sentence information, is always kept. It does not test raw missing tokens before the encoder and cannot establish robustness to missing original inputs. Reusing this already-examined SST holdout makes all these additional architecture comparisons exploratory.

## Validation, timings and limits

`snn_validation.json` verifies the hard 0/1 forward values, the exact declared surrogate derivative at and around threshold, finite nonzero gradients through input/recurrent/time-constant parameters, the intended initial time constants, and strong float32 initialization. Its initial diagnostic batch has 12.89% active spike entries. Every trained checkpoint also has explicitly verified binary spikes; these firing fractions describe the simulation and are not energy estimates.

The separate checkpoint audit reloaded all 20 saved checkpoints, verified source/checkpoint/data hashes, and reproduced each recorded test accuracy, loss and Brier score exactly. All maximum replay errors were zero. This verifies the retained implementation and results, not statistical generalization to new data.

The measured synthetic loop took 25.513 seconds and the frozen-head loop 5.251 seconds, excluding process startup and the initial validation pass. Mean training-call wall times, including validation and any compilation in that call, were 1.442 seconds for memory, 1.424 for retrieval, 1.180 for irregular input and 0.705 for frozen text. They are reproducibility diagnostics on a shared CPU, not benchmark evidence of speed superiority.

The common legacy trainer also retains a field named `warm_training_seconds`. It excludes only the first update. Earlier HCSN/GRU/Transformer receipts can include a second JIT compilation caused by weakly typed initialization on a new signature; later seeds can reuse caches. New SNN parameters are strongly typed, but all train-time fields remain diagnostic because compilation/cache order and shared CPU load are not controlled for a speed comparison. No old JSON or source was changed to conceal this limitation.

No GPU, neuromorphic hardware, event-driven sparse kernel, energy, or joule measurement was made. Equal parameters, updates and presented examples are not equal FLOPs. The SNN has one predetermined setting and no family-wide hyperparameter search. The results therefore support comparisons among these concrete implementations under this budget, not a claim that either HCSN or traditional SNNs are generally superior.

**The full-backbone gate remains closed.** The new conventional SNN comparison does not repair HCSN's length-generalization and associative-retrieval failures, and does not supply a put-specific gain or a frozen-text advantage. No language-model or multimodal pretraining result is implied.

## Reproduction and retained evidence

Run `python run_snn_reference.py --features PATH_TO_FROZEN_FEATURES`, then `python audit_snn.py --features PATH_TO_FROZEN_FEATURES`. The JAX dependencies and CPU limits described in README.md apply. `validate_snn.py` runs the stand-alone implementation checks.

- `snn_protocol.json`: design frozen before training.
- `snn_models.py`, `run_snn_reference.py`: independent model and execution entry point.
- `snn_reference_results.json`: all 15 synthetic runs, source/data hashes and validation histories.
- `snn_frozen_results.json`: all five frozen-head runs with unchanged feature SHA.
- `snn_validation.json`: binary-forward and surrogate-backward checks.
- `snn_reference_checkpoints/`: all 20 selected checkpoints and hashes in the receipts.
- `snn_checkpoint_audit.json`: checkpoint replay and provenance verification.

The original v1/v2 source and raw JSON files remain unchanged. The earlier reports were amended only to state the JIT-timing and holdout/feature-perturbation limitations explicitly.
