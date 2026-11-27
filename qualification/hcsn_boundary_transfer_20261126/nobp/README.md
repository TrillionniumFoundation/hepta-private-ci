# Training a spoken-digit decoder from random encoder weights

Hammami and Bedda's UCI Spoken Arabic Digit dataset supplies MFCC time series, digit labels via file order, and an author-defined speaker-disjoint split. This experiment examines a centered, boundary-only HCSN with 32 physical populations, the original uniformized mixed-precision forward and 80 receiver features at each time point. Its six concatenated receiver latents feed a supervised linear readout. A frozen encoder arm starts with the original random input/recurrent weights and physical default values and executes zero encoder-gradient steps. A paired BP arm starts with the identical full state, optimizes with a temporary classifier, and then receives the identical direct ridge readout. A GRU pair and flattened MFCC ridge provide independent task baselines.

The 660×6×13 fit tensor uses a prespecified positional subsample of the 6,600 official training recordings. All 2,200 official confirmation utterances are retained. The six selected frames are interpolated time coordinates across an already recorded utterance. This design neither offers live causal digit recognition before the final frame nor measures raw-waveform or multimodal pretraining. The counts range across 66 training-source and 22 separate test-source speakers as documented by the authors. The features contain no per-speaker identifier, so speaker-resampled confidence intervals cannot be computed faithfully. The audio corpus documentation is available from [the authors](https://archive.ics.uci.edu/ml/machine-learning-databases/00195/documentation.html) and [UCI](https://doi.org/10.24432/C52C9Q).

## Reproduce

Use the pinned original repository commit listed in SOURCE.json on PYTHONPATH. NumPy and a single-threaded CPU PyTorch runtime are required. The archive includes double-precision ridge weights and both the initialized and selected encoder states for all arms. The application data mirror provides exact author-format source files. The ROG compute host used a pinned mirror after an official-endpoint timeout. An independent desktop retrieved the 14,646,679-byte official UCI ZIP, SHA-256 3c8c83404289c49631605421830872be337d92d887e61798385aacbe9423010d. Both official text files match the frozen mirror SHA-256 digests byte for byte. The separate official origin receipt records the check.

```sh
python get_data.py data
python launch.py train data run --workers 3
python launch.py test data run --workers 3
python verify.py run --data data --save fresh_summary.json
```

Each pair uses the same seed, input tensors and ridge target. The basis can carry useful information even without encoder updates. A frozen-feature accuracy comparison identifies only what this representation and supervised readout can do on this fixed task. It does not demonstrate learning an encoder's internal weights without gradients. Physical defaults and handcrafted MFCC features are also part of the tested system. Full pretraining compute, GPU energy, training from raw audio and large-model scaling are outside the evidence.

## Held-out results

| Random seed | HCSN frozen | HCSN after BP | GRU frozen | GRU after BP | Flat ridge |
|---:|---:|---:|---:|---:|---:|
| 107 | 85.00% | 84.59% | 90.00% | 90.32% | 89.73% |
| 211 | 82.32% | 81.18% | 90.73% | 91.45% | 89.73% |
| 431 | 85.64% | 84.86% | 91.18% | 91.50% | 89.73% |

Always predicting digit zero achieves exactly 10%. Each frozen HCSN exceeds the .70 floor and falls within the two-point margin relative to same-initialization HCSN BP. Its paired gains are +.41, +1.14 and +.77 percentage points. Each also trails the strongest ordinary comparator by 5.32, 9.14 and 5.86 percentage points respectively. Flat ridge outperforms all HCSN arms. The overall prospective gate fails. Direct regression alone makes usable digit predictions from random HCSN features in this bounded setup. Their relative accuracy against BP depends on its fixed 64 updates, the temporary-head objective, the final ridge and the six-frame input; longer or tuned BP was not tested.

| Arm | Median cold fit through checkpoint | Median official test process | Median same-seed sum |
|---|---:|---:|---:|
| Frozen HCSN | 2.992 s | 5.322 s | 8.314 s |
| HCSN BP | 15.426 s | 5.324 s | 20.751 s |
| Frozen GRU | 1.503 s | 1.232 s | 2.735 s |
| GRU BP | 2.590 s | 1.232 s | 3.822 s |
| Flat ridge | 1.435 s | 1.209 s | 2.628 s |

These are three paired seeds on one shared ROG CPU capped at three concurrent single-threaded processes. Each fit rechecks and parses the training file, initializes an encoder where applicable, performs all feature extraction, BP if specified, final ridge and serialization. Confirmation includes a fresh process, test data preparation, inference and individually scored output. The first training wave had a large startup outlier, including 35.8 s for frozen HCSN and 34.4 s for frozen GRU. The per-process receipts are required for interpreting these medians. Download and experiment authoring are outside these clocks. The cheaper flat and GRU models also reached higher accuracy than the frozen HCSN.

The full files have zero matching utterance line-payload hashes across the official split. The training file contains 82 repeated utterance payloads beyond their first copies, the selected training subset has zero, and the test file contains 25. All official test rows retain their prescribed weights. Numbered utterances are not independent people. Predictions from repeated seeds on the same recordings are paired. No person-level uncertainty or population equivalence inference is justified from anonymous record order.

Each ZIP under evidence/ contains a single arm and seed, including fresh initial and selected weights, test scores and actions, and process logs. `python verify.py evidence --data data` verifies hashes, reconstructs the archives, independently scores every official row, verifies matched initializations and reproduces each registered gate and timing median. The complete numerical output, including paired digit and sex-stratum summaries, is in summary.json.
