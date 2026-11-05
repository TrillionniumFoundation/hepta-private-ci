# V5 formal training and artifact inspection

Forty actual fits completed under frozen source `21da14adf9910fa5218696f6451f517fa0ef46a7`. This report covers training, public selection, costs, and artifact readout mechanisms. The independent held corpus has not been opened by this training or inspection owner. No unit tests were rerun.

## Execution and identities

- Training command exited 0; stderr was empty.
- FREEZE SHA-256 before and after training/inspection: `9e10b723c13a0243aa8d652a192809f73b8c4dc8e7ae41959625383e4ec80afa`.
- Training-run summary SHA-256: `29f6167a287b8a8c13f8144ad127aea4d622000e6dd3ca311292b459bcdb0106`.
- Artifact inspection SHA-256: `fb438069f3f2540cfabc9cde8cf030564f8a69b50e4b26e5328be95fdc0144dd`.
- All frozen source and formal training-run bytes remained unchanged during inspection.

## Selection, before independent held evaluation

All five seeds select `mixed-svm-c2` from the same eight predeclared candidates. The normalized-score minimum margin is 0.3, minimum confidence is 0, and reject-all is false. Each selected model correctly accepts 17/96 known selection requests (17.7083%), accepts no wrong known label, and falsely accepts 4/96 selection OOD requests (4.1667%). Thus all five selected models already fail the 80% correct-coverage gate on public selection. These are not independent held results.

| Seed | Selected stored bytes | Loaded numerical array bytes | Manifest SHA-256 |
|---|---:|---:|---|
| 1019 | 270,685 | 657,912 | `b2bf96bcb71e39f011ab11ca9a0b4f3dac754bd15e1c6895513b85a376d74cce` |
| 1021 | 270,431 | 657,912 | `104ea251e42ca58302651a05638b18b0af986e91c937906a665d0ca4b2647616` |
| 1031 | 270,177 | 657,912 | `70696ae5691eaa389c28bfae05c6afb34e3b8d074d52edfb672ee834eb95e0ad` |
| 1033 | 270,387 | 657,912 | `e9a9046eb8b3a134d0ee5c002258534b2bc1e717bc6a4a84adb9f0a5d99fbf6b` |
| 1039 | 270,607 | 657,912 | `a51250ac10738e184881cfcf92c4e0f3445d2ed2f7e65c5444552f9e3177d395` |

The same authored language is shared by all five optimization seeds. Five seeds do not create five independent language datasets. The SVM normalized scores are not calibrated probabilities.

## Actual cost ledger

| Measured item | Amount |
|---|---:|
| Complete training process, outer wall | 68.124512 s |
| Complete training child CPU, including process startup | 68.095237 s |
| Training function wall | 65.823697 s |
| Training function process CPU | 65.793138 s |
| Actual 40 model-fit CPU sum | 54.962782 s |
| Actual 40 calibration CPU sum | 5.830962 s |
| All 40 candidate artifacts, actual retained bytes | 7,049,096 |
| Five additional selected copies | 1,352,287 B |
| Five PRIMARY metadata files | 29,280 B |
| Shared CSR caches, actual serialized storage | 4,196,915 B |
| Shared CSR caches, loaded numeric arrays | 12,887,076 B |
| Stored public corpora, compressed | 67,044 B |
| Complete formal training directory | 339 files / 23,901,273 B |
| Pretrained encoder calls / bytes | 0 / 0 |

Candidate-level totals below cover five actual fits per row. Shared TF-IDF fitting and caching are charged once in the separate cache ledger. All fits completed without solver warnings. Solver iteration arrays are retained with their algorithm-specific meaning; they are not converted into fabricated exact update counts or FLOPs.

| Candidate | Fits | Fit CPU | Retained artifact bytes | Numeric arrays per model |
|---|---:|---:|---:|---:|
| `char4096-lr-c4` | 5 | 32.977199 s | 673,169 | 262,200 B |
| `mixed-svm-c0.5` | 5 | 0.854184 s | 1,378,558 | 657,912 B |
| `mixed-svm-c2` | 5 | 1.868969 s | 1,352,287 | 657,912 B |
| `mixed-svm-c2-negative-families` | 5 | 2.257802 s | 1,875,899 | 986,872 B |
| `unigram2048-lr-c4` | 5 | 2.392310 s | 115,284 | 21,624 B |
| `word-lr-c1` | 5 | 2.822580 s | 482,028 | 196,344 B |
| `word-lr-c4` | 5 | 4.022835 s | 482,062 | 196,344 B |
| `word-lr-c4-negative-families` | 5 | 7.766905 s | 689,809 | 294,520 B |

Storage and runtime arrays are different quantities. Model storage includes all actual compressed parameter parts, vocabulary/IDF metadata and manifest. Loaded numeric bytes include coefficients, intercepts and IDF; they exclude Python objects and runtime binaries and do not claim total RSS. All retained candidate alternatives and duplicate selected copies are counted.

## Actual artifact mechanisms

- Reloaded all 40 saved model artifacts using their externally bound manifest SHA-256; checked every part inventory, actual serialized byte total, loaded numeric byte total, source commit, seed, config digest and training-source inventory digest.
- Reproduced **5,760/5,760** saved public development decisions from those loaded artifacts, with every decision field exactly equal and parameter digests unchanged.
- Loaded each of the five selected models in a separate fresh process and reproduced **720/720** saved public decisions, again with exact all-field equality and unchanged parameter digests.
- Recomputed every shared sparse-cache shape, nonzero count, numeric-array size and archive size from the actual stored CSR payload.
- Recomputed the eight-candidate primary selection for every seed and verified byte-identical selected copies.
- These repeated public-query readouts are implementation mechanisms, not 6,480 independent language observations or new semantic qualification evidence.

Inspection overhead is additional to training: 11.547713 seconds wall measured inside the inspection function, including its five fresh subprocesses. The parent inspection CPU was 0.956319 seconds; the fresh readers reported 0.133985 seconds inside their inference functions. The latter excludes their Python/import startup and is not claimed as complete child CPU. Initial inspector imports also precede its function timer. Complete formal-training process CPU is separately measured above.

## Handoff

The selected models are ready for root-controlled SELECTED_MODELS sealing and remote publication before opening independent held evaluation. No model, threshold, support definition or candidate was changed after these fits. Original V5a/V5b failures remain preserved. This training report does not claim that the semantic blocker or production admission has passed.
