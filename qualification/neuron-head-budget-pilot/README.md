# Harrier head-budget diagnostic: conditional endpoint gain, budget hypothesis inconclusive

This is a new **historical same-source** AG News experiment, not source-family independence, future-data qualification, a replacement decision, or production readiness. It preserves the original negative head/calibration findings in #3588/#3593.

## Actual result

All heads use the same pinned Harrier 270m document embeddings, last-token pooling and L2 normalization. Only training budget changes. Four nested training prefixes and one new 1600-component test were fixed before feature extraction.

| Training rows | Logistic accuracy | Centroid accuracy | Difference |
|---:|---:|---:|---:|
| 320 | 88.3125% | 87.7500% | +0.5625 pp |
| 640 | 90.0000% | 88.5625% | +1.4375 pp |
| 1280 | 90.3750% | 88.6875% | +1.6875 pp |
| 2560 | 90.0000% | 88.7500% | +1.2500 pp |

Two locally pre-frozen primary contrasts, with 10000 paired row bootstraps and Bonferroni-adjusted two-sided 97.5% percentile intervals:
- Endpoint (2560) logistic-minus-centroid: +1.2500 pp, interval [+0.3750, +2.1250].
- Change in that relative advantage from 320 to 2560: +0.6875 pp, interval [-0.5000, +1.8750].

**The pre-frozen joint budget-improvement claim is not demonstrated.** The endpoint shows conditional superiority on this cohort, but the increase in relative advantage remains uncertain. The intermediate 1280 score is not a retrospectively selected winner. Intervals are descriptive, conditional on one nested training draw; no claim of exact finite-sample simultaneous coverage. Fixed 200-step Adam is not proof of the optimum (final gradient norms 2.7e-5, 1.0e-5, 2.9e-6, 2.9e-5).

## Independence and title-graph audit

The protocol was locally frozen at 2026-10-24T04:37:46Z before cohort selection, not externally preregistered. It excludes every connected component linked to the previous 960 selected rows. Edges are equal NFKC/whitespace/casefold normalized titles OR full text. It removes cross-official-split or label-conflicting components before deterministic hash ranking.

An independent BFS, separately implemented from the preparation union-find, reproduces 120461 components from 127600 source rows and all selected component keys. The full corpus contains 744 cross-official-split components (1937 rows), 727 label-conflict components (1705 rows), and 960 old-exposure components (1164 rows). Exclusion counts overlap. New selected component overlap and old-exposure overlap are zero.

Crucially, the old pilot test has **zero** title/full-text components shared with its training, temperature or conformal subsets. The full-corpus 744 count is not evidence that the old pilot leaked. Equal titles are only potential contamination proxies, not same-event truth: zero empty titles, 206 repeated-title groups with at most 20 characters, maximum component size 43. Conservative title exclusion can overmerge generic headlines and changes the sampled population. Semantic-story overlap and model pretraining contamination remain unknown.

Preparation reads source labels for conflict exclusion; the **fitter** does not read test labels until all eight head objects (two head types at four budgets) and the fit receipt are saved. This is not a claim of full-process test-label blindness.

## Actual execution and verification

- 4160 new embeddings, 222480 tokens, no truncation (max train209/test198).
- Pinned snapshot revision 31de22b673913c7d658c0f03f792d77c2dcf8ebd; all ten original reviewed file hashes matched after official restoration and after inference.
- Native/manual last-token+L2 first-batch maximum error 0.
- Encoder 512.89 seconds; peak RSS 2375352 KiB (~2.27 GiB); two CPU threads, batch8, CPU float32. Fitting and analysis 2.36 seconds, RSS307216 KiB.
- Frozen protocol, row and raw-data hashes, independently partitioned labels, exact drivers, runtime versions and tensor/head digests retained.
- Independent reviewer recomputed eight accuracies and both bootstrap intervals exactly from retained features/heads/labels, without retraining. A clean preparation rerun matched six artifact hashes and its receipt.

CI runs only arithmetic replay of the recorded per-row correctness and the frozen intervals; it does **not** reload weights, rerun inference, fetch news, or confer qualification. It has no missing-model skip path.

## Files and reproduction

protocol.json and rows.json are the fixed protocol and text-free selected sample identities. observed/ contains results, receipts, evidence correctness bits, and the original executed source. replay_observed.py needs numpy2.2.6 only. Run `python replay_observed.py` from this directory. No raw news, labels, model weights or secrets are published. Large frozen feature/head arrays remain local with hashes in extraction.json and fit-receipt.json; CI cannot independently recompute model predictions without them and the source labels.

Full replication requires the original AG News source archive and prior pilot exclusions, plus the pinned official Microsoft snapshot and exact core runtime. Archive source drivers in observed/source reproduce the original workspace layout documented by their relative paths; they are evidence, not a path-portable one-command installer. Do not overwrite original receipts or reuse the now-exposed 1600 test for another acceptance test. A fresh independent source-family/future cohort remains needed.

AG News README/TFDS describe research and non-commercial use; no commercial or redistribution rights inferred. Harrier model card is MIT. This package contains no news text.

Sources: https://huggingface.co/microsoft/harrier-oss-v1-270m ; https://www.tensorflow.org/datasets/catalog/ag_news_subset ; https://arxiv.org/abs/1509.01626 ; https://arxiv.org/abs/2103.10948
