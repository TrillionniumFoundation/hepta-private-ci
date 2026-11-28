# Three-stream MOSI recovery and new cold evaluation

The original historical seal identifies 103 weight files across 63 fits and 189 accepted validation prefixes. The public aligned input and all three historical standardized split archives were recovered byte for byte. The newly scored confirmation partition contains 686 utterances from 31 source videos. Its SHA-256 is `e84b18ceca68138a1db83a812a9c67fe837046df12537018f6f14ddc01368c8a`.

## Historical weights

Nine exact frozen weights were recovered, covering three seeds for each pooled ridge model. Their intact confirmation video-macro MAEs were 1.07080 for all streams, 1.03894 for text, and 1.43200 for audio plus vision. Seeds yield identical predictions within each deterministic ridge configuration. All streams minus text alone was +0.03186 with a paired 95% interval of [−0.01375, +0.07988]. Replacing both audio and vision by their training mean in the all-stream model changed MAE by −0.03310 [−0.07228, +0.00661].

The full ridge/forward reconstruction enumerated all three original penalties for all 33 nonlinear finite-solver fits. None of 117 exact serializations matched the 39 frozen nonlinear objects. All 15 new width-64 development winners reproduced across independent processes, including an exact deserialize/reserialize check. Changing CPU dispatch on the same host changed 172,439 of 901,071 numeric state elements in those 15 models at fixed penalty. All three ridge controls remained bitwise identical. The lost originals expose only an archive SHA-256, so the specific discrepancies with those originals cannot be attributed to a historical CPU kernel or a particular serialization format.

For the 55 historical gradient-trained objects, both original learning rates and the fixed 0, 1, 4 and 12-update evaluation points generated 440 exact serialization tests. A further 59 tests compared 22 newly selected width-64 BP checkpoints with their 23 historical filenames. These tests produced no additional byte matches. The historical grid also allowed later 24-update multiples, with admission depending on the particular training process's CPU time. The original timing histories were unavailable.

## Separately sealed new study

The new panel has 36 fits, 49 selected weight files and 108 eligible prefixes. The seal SHA-256 is `fc024bfe4a11bcf1f95390efe0a32d2200cb532f11aa7c7c57fa15c601194858`. It precedes the new confirmation scoring. The study uses a public, previously examined cohort and upstream pre-extracted BERT, acoustic and vision coordinates. The results describe training the new MOSI models on these supplied features. The acquisition and upstream feature extractor costs are outside the clocks.

| Method | Video MAE at 180 CPU s | Nonzero-label sign accuracy | End-to-end upper wall time at 180 CPU s |
|---|---:|---:|---:|
| Forward HCSN, all streams | 1.02560 | 76.93% | 19.56 s |
| Same architecture, BP | 1.02908 | 76.83% | 195.73 s |
| Transformer, all streams | 1.00490 | 76.17% | 194.13 s |
| Forward HCSN, text | 0.98488 | 77.24% | 19.26 s |
| Forward HCSN, audio and vision | 1.46997 | 51.88% | 19.39 s |
| Pooled ridge, all streams | 1.07080 | 76.22% | 15.46 s |
| Pooled ridge, text | 1.03894 | 76.83% | 15.38 s |
| ReLU forward projection | 1.05218 | 75.86% | 16.05 s |
| Forward HCSN, shuffled hidden target | 1.38308 | 56.76% | 19.30 s |
| Fixed random HCSN features and ridge | 1.34391 | 61.84% | 15.79 s |

At the common 180-CPU-second budget, the all-stream forward HCSN minus same-architecture BP difference in equal-video MAE was −0.00347. The paired seed/video 95% interval was [−0.05290, +0.04876], which clears the prespecified +0.05 noninferiority margin by 0.00124. Against the all-stream Transformer the difference was +0.02071 [−0.04496, +0.08148]. Against text ridge it was −0.01333 [−0.08156, +0.05863]. These two upper bounds exceed +0.05. The raw all-stream ridge comparison favored the forward HCSN by −0.04519 [−0.08819, −0.00139].

At the predeclared 1.20 MAE quality target, every seed first qualified at the 15-CPU-second rung for forward HCSN, same-architecture BP and Transformer. Their corresponding mean end-to-end wall-time upper bounds were 19.56, 31.56 and 29.47 seconds. This gives 1.61× relative to same-HCSN BP and 1.51× relative to the Transformer. Text and all-stream ridge reached the same level at 15.38 and 15.46 seconds. The Transformer already passed 1.05 across all three seeds at the 15-second rung. The forward HCSN and its same-architecture BP comparator remained censored at 1.05 through the last rung. Their censored crossings leave the relative time to 1.05 unidentified.

## Modality evidence

Separately trained forward HCSN using text alone had 0.98488 MAE and using audio plus vision had 1.46997. Relative to the text-only model, full fusion changed the average by +0.04072 [−0.01645, +0.09985]. Text was important to full-model predictions. Cross-video text swaps increased MAE by +0.56312, audio swaps by +0.02435 and vision swaps by +0.03018. The familywise-adjusted intervals were [+.44916, +.68007], [−.01158, +.05818] and [−.03244, +.09769], respectively. Replacing the full audiovisual input by its training mean improved full-model MAE by 0.06447, with paired interval on the signed change [−0.13264, −0.00178]. Whether the three streams provide a joint benefit remains unresolved in this experiment.

There are 684 intact or perturbed prediction vectors and 469,224 scalar predictions. The independent metric replay recovered the same two summary files from all models, split IDs, three cross-video derangements and raw confirmation scores. The primary summary SHA-256 is `b4de92a5706d9b2d89373fa1cb7e965262bd0d3c38db54d25d4189689bdc65b7`. The terminal inventory SHA-256 is `d89654fa913fa27fb9bd9ac1d130746b5f9293811011ae093051427118d749c3`. Exact figures for all 12 arms and all observed quality thresholds are in `fresh_interpretation.json`; `interpret_fresh.py` regenerates that compact view from `fresh_summary.json`.
