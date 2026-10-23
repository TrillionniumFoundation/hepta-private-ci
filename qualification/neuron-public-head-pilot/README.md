# Harrier native-pooling public-text Head and calibration pilot

This is a locally pre-frozen, bounded historical-data diagnostic, not scientific qualification, a replacement for the five-model Cell bakeoff, or a production acceptance result.

## Main findings

- A trained logistic head did not outperform the centroid baseline: 277/320 versus 280/320 correct. The paired difference was −0.94 percentage points, with a descriptive 95% paired-bootstrap interval [−2.50, +0.31].
- A scalar temperature fit only on the separate temperature split improved held-out logistic NLL from 0.488564 to 0.374698. The paired NLL improvement interval was [0.062066, 0.158187]; top-1 predictions were unchanged.
- The primary logistic + temperature + LAC refusal route failed the locally pre-frozen utility condition. Its test-set coverage was 275/320 (85.94%); it accepted 307 singleton predictions, of which 38 were wrong (12.38%; Wilson 95% interval 9.15–16.53%).
- Secondary APS accepted fewer singleton predictions: 223/320, of which 14 were wrong (6.28%; interval 3.78–10.26%). Its set coverage was 282/320 (88.13%). These results do not authorize switching the primary route after seeing the test.

The plan and selection were frozen locally before extraction; analysis source was frozen before extraction completed and before fitting or held-out metric inspection. There is no independent registry or external timestamp establishing preregistration. Historical JSON key names containing “preregistered” refer only to these local predeclared conditions.

## Frozen design and evidence

- Original author AG News archive SHA256: 4e2fc37d369e6e317a8b62d0d2f11d379f8c3dde60c07c35a46b069a246498ad, independently matched to TensorFlow Datasets official checksum.
- Full-text normalization: NFKC, collapse whitespace, casefold only for duplicate-group identity. All 10 normalized exact-duplicate groups shared by the official train/test splits were excluded from both candidate pools. Training data also contained 151 duplicate rows and 22 label-conflict groups; conflicting groups were excluded. This does not detect semantic or story/source duplicates.
- Selection was a fixed salted SHA256 ranking over unique eligible groups, without label stratification. Splits: 320 head-training, 160 temperature-fitting, 160 conformal-calibration, 320 official-test rows. All 960 selected group identities are disjoint.
- Plan SHA256: 48ff3c003067370449254daefcf465c4960fbc01a39dae5b83d98123d3aec55c. Row manifest SHA256: 48c6ce55a95e1e6652a36fdeedc5b0a4f57ac23230b7b706bf5456d395726244. Both frozen before embeddings/fitting; analysis source frozen before feature extraction ended and before held-out metric inspection.
- Encoder: microsoft/harrier-oss-v1-270m revision 31de22b673913c7d658c0f03f792d77c2dcf8ebd, original standard model implementation, no remote custom code. CPU float32, 2 threads, batch 8, 256-token cap, explicit empty document prompt, native last-nonpadding-token pooling and L2 normalization. This is document-mode encoding, not an optimal classification-prompt claim.
- All arms reuse exactly the same 960×640 feature matrix. Total input tokens: 51,179; zero sampled documents were truncated. A first-batch manual pooling check had maximum absolute difference zero. Original snapshot and disposable runtime copy matched all files at load, each split, and final guarded checkpoints. Checkpoint hashing does not prove absence of transient rewrite-and-restore.
- Feature archive SHA256: efd68909845d2810167a9a2048d1e07e0eed5012b446e6e9713511bcb1e9a9dc. Encoder extraction took 133.0 seconds including copy/hash/load; peak process RSS 1,993,840 KiB. This is not a production throughput benchmark.

## Head and calibration recipes

- Centroid: normalize each class mean of normalized training embeddings; score by cosine.
- Logistic: zero-initialized 640→4 weight/bias head, float64, 200 full-batch Adam steps, learning rate 0.1, mean cross-entropy plus 0.001/2 times squared weight norm; unpenalized bias. The final objective gradient norm was 6.82e−5. A fixed-step optimizer is not a proof of optimality.
- Ridge, secondary: centered one-hot squared-loss readout with lambda 1.0 and unpenalized intercept. This is not claimed identical to sklearn RidgeClassifier label coding.
- Temperature: one positive scalar per head, T=exp(t), fit by 100 iterations of golden-section validation-NLL search over t in [−5,5], including raw T=1 and endpoints as candidates. No fitted temperature hit the boundary. No encoder or publisher calibration setting was edited.
- LAC: score 1−p_y. APS: stable descending class probability, class-index tie breaking, cumulative probability through candidate minus U times candidate probability. Separate fixed calibration/test PCG64 streams; one uniform per row shared across candidate labels, common across arms. Empty sets are allowed.
- Alpha=0.10, calibration size 160, exact order statistic k=ceil(161×0.9)=145. Prediction sets use score≤threshold. Accept a single label only for singleton sets; otherwise abstain.

## All locally pre-frozen arms

| Head | Variant | Accuracy | NLL | Brier | ECE10 | LAC coverage | LAC accepted/errors | APS coverage | APS accepted/errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| centroid | raw | 0.8750 | 1.336807 | 0.724841 | 0.611428 | 0.8688 | 268/21 | 0.8531 | 313/40 |
| centroid | TS | 0.8750 | 0.368260 | 0.191994 | 0.023576 | 0.8562 | 310/36 | 0.8469 | 229/17 |
| logistic | raw | 0.8656 | 0.488564 | 0.237252 | 0.162319 | 0.8594 | 301/32 | 0.8438 | 215/18 |
| logistic | TS | 0.8656 | 0.374698 | 0.192478 | 0.033285 | 0.8594 | 307/38 | 0.8812 | 223/14 |
| ridge | raw | 0.8625 | 1.017057 | 0.542000 | 0.486169 | 0.8906 | 284/25 | 0.8469 | 269/33 |
| ridge | TS | 0.8625 | 0.382404 | 0.190295 | 0.033180 | 0.8812 | 308/35 | 0.8719 | 227/16 |

The accepted/errors columns mean number of accepted singleton predictions / number wrong, not an accuracy fraction. Complete thresholds, temperatures, set sizes, empty rates, per-class counts, confidence intervals and fixed-bin statistics are retained in results.json. Raw cosine and ridge scores have arbitrary scale, so their temperature improvements should not be interpreted as equivalent evidence to calibrating a probability-trained head.

## Interpretation and limits

Split conformal concerns marginal prediction-set coverage under exchangeability, with all fitted components independent of the conformal split. It does not promise 90% correct accepted singleton decisions, class-conditional coverage, every realized split, or OOD safety. Official training versus test distributions and this fixed historical sample do not establish exchangeability; observed coverage below 90% is the result on this finite sample, not a refutation of the general theorem. Its Wilson interval conditions on the realized threshold and does not include uncertainty from the 160-row calibration sample; neither finite calibration/test uncertainty nor distribution shift is established as the sole explanation.

The primary LAC per-class coverage varied substantially: World 76/82, Sports 75/76, Business 59/75, Sci/Tech 65/87. The protocol was not altered to fix these outcomes. No new test-driven thresholds, seeds, head hyperparameters or prompts were selected.

This is one small historical AG News subset, with unknown encoder-training contamination and residual semantic/source leakage. Descriptive bootstrap/Wilson intervals do not account for these issues or future distribution shift. They are unadjusted for multiple comparisons and are not simultaneous cross-arm 95% guarantees. It cannot close original five-model resource parity, independent future-family evaluation, OOD/rejection qualification, or production artifact lifecycle blockers.

The original AG News README restricts use to academic research and non-commercial purposes. Raw news text and original archive are retained locally only and are not included in the deliverable; row IDs/hashes allow reconstruction from the cited public source. No broader commercial or redistribution license is inferred.

## Primary sources

- Microsoft original model card and implementation configuration: https://huggingface.co/microsoft/harrier-oss-v1-270m/tree/31de22b673913c7d658c0f03f792d77c2dcf8ebd
- AG News author repository and dataset paper: https://github.com/zhangxiangxiao/Crepe ; https://arxiv.org/abs/1509.01626
- TensorFlow Datasets provenance/checksum: https://www.tensorflow.org/datasets/catalog/ag_news_subset ; https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/datasets/ag_news_subset/checksums.tsv
- Temperature-scaling objective: https://proceedings.mlr.press/v70/guo17a.html ; https://github.com/gpleiss/temperature_scaling/blob/master/temperature_scaling.py
- APS paper and author implementation: https://arxiv.org/abs/2006.02544 ; https://github.com/msesia/arc/blob/master/arc/classification.py
- Split-conformal overview: https://arxiv.org/abs/2107.07511

## Reproduction status

Exact observed preparation, extraction and analysis source, hash manifests, package versions, outputs and unit-test logs are retained. The observed extraction source points at the existing local model and published artifact-guard checkout; path configuration must be supplied for another machine and any modified driver must get a new identity. No fresh model download is necessary on this host. The original result files are not overwritten by replay. Independent review status is recorded separately.

## Portable source and observed-source distinction

The top-level scripts are an opt-in portable diagnostic, not imported by the existing five-model runner and not a production acceptance gate. They accept a separate output directory. The exact originally executed scripts remain in observed/source; their hashes bind the original receipts. The portable extraction driver additionally checks the complete original snapshot inventory and package versions against the observed receipt before inference. Its identity is different from the observed extraction driver, so the existing extraction receipt is not represented as a run of the portable driver.

To reproduce: obtain the original archive from the source URL in plan.json, verify its exact SHA256, and safely extract only train.csv and test.csv into a fresh output directory. Run prepare.py --output-dir OUTPUT. The resulting plan.json and rows.json must match the published SHA256 values. Then run extract.py --output-dir OUTPUT --snapshot EXISTING_PINNED_SNAPSHOT, with a CPU runtime matching observed/extraction.json. The published sibling neuron-model-bakeoff/artifact_guard.py is used by default; --bakeoff-dir can locate its exact reviewed bytes elsewhere. Limit OS affinity and OMP/MKL/OpenBLAS threads to two as in the observed run. No remote model/code downloads are performed by the extractor. Finally run analyze.py --output-dir OUTPUT. Output existence checks prevent overwriting frozen features or prior results. Run the focused mathematical tests with python -m unittest -v test_analyze.py in this directory.

These instructions require the existing scientific Python packages, archive and original model supplied separately; they do not install packages, accept model licenses or request credentials. The AG News archive/license restriction remains in force. Published row identities/hashes are not raw news text. Features and trained arrays are retained in the local scientific evidence package, not committed as repository tensors.

## Relation to prior repository work

Earlier research already compared learned readouts and cheap centroid/prior baselines on historical AG News, including [#2671](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2671) and [#2625](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2625). This is not the first AG News Head experiment or a matched comparison to those results: it uses a different pinned native-pooling Harrier model, new fixed row selection and disjoint temperature/conformal partitions, and explicitly tests LAC/APS refusal. Search found no existing Harrier/conformal PR duplicating this exact route.

All readouts share features, not equal optimization budgets: centroid has 2,560 stored coefficients and no gradient updates; logistic and ridge each have 2,564 coefficients including bias, with respectively 200 Adam steps and a linear solve. This deliberate cheap-baseline comparison cannot close the original five-model equal-budget/performance requirements.

## Post-run custody hardening

See [CUSTODY_NOTE.md](CUSTODY_NOTE.md). The original observed evidence and scores are unchanged. Preparation now rejects adjacent CSV bytes that do not match the original archive members. Analysis now pins the original reviewed extraction anchor and independently checks the actual float32 tensor bytes for every split, rather than accepting a mutually consistent editable feature file and receipt. This is an exact historical-feature replay profile: a fresh extraction producing different tensor bytes is rejected and requires a separately reviewed feature freeze/profile, even if the difference is numerical only. Repacking identical tensors is allowed after the file receipt is updated. This does not establish independent signing, blind custody, source-code immutability or scientific qualification.
