# Full-cohort CREMA-D on a private Tesla T4

The frozen panel retained all 7,442 clips and the original 61/14/16 training, development and held-out actors. The 72 candidate label strings and four-atom financial table kept their original contents. A 4-bit summary reduced 12 video and acoustic frames to four time blocks, each with four image quadrants and four audio bands. The model receives quantized features and uses the archived actor identifier only for evaluating the split and confidence intervals.

| Endpoint | Model | Mean cold NLL | Mean cold top-1 | Steps by seed | Mean charged optimization, s |
|---|---|---:|---:|---|---:|
| updates78 | literal | 4.00030 | 6.53% | 78/78/78 | 2.468 |
| updates78 | smooth | 3.99726 | 7.14% | 78/78/78 | 2.210 |
| updates78 | lif | 4.13247 | 4.96% | 78/78/78 | 1.443 |
| updates78 | sdpa | 3.95239 | 7.22% | 78/78/78 | 1.124 |
| time12 | literal | 3.76122 | 9.03% | 380/421/416 | 12.009 |
| time12 | smooth | 3.79149 | 8.59% | 396/402/394 | 12.019 |
| time12 | lif | 3.77221 | 9.76% | 619/622/619 | 12.010 |
| time12 | sdpa | 3.56775 | 12.33% | 1093/1130/1180 | 12.003 |

The 32-coordinate ridge selected on development scored 3.96104 NLL and 9.61% top-1. Its train plus development search took 0.206 s. Every 78-update neural checkpoint processed all 4,984 training clips twice. The 12-second endpoint charges synchronized optimization. Setup, saving, dev evaluation and cold inference are recorded separately. The total panel time was 158.11 s.

| Endpoint | Actor-paired literal minus control NLL | Mean difference | 95% actor interval |
|---|---|---:|---:|
| updates78 | smooth | +0.00304 | [-0.00365, +0.00979] |
| updates78 | lif | -0.13217 | [-0.16648, -0.09369] |
| updates78 | sdpa | +0.04791 | [+0.03417, +0.05964] |
| updates78 | ridge | +0.03926 | [+0.00145, +0.07559] |
| time12 | smooth | -0.03027 | [-0.06095, +0.00016] |
| time12 | lif | -0.01099 | [-0.06011, +0.02781] |
| time12 | sdpa | +0.19347 | [+0.08925, +0.29297] |
| time12 | ridge | -0.19982 | [-0.26927, -0.13048] |

| Endpoint | Intervention on literal model | Mean NLL increase | Actor-cluster 95% interval |
|---|---|---:|---:|
| updates78 | perm_audio | +0.52885 | [+0.44462, +0.61622] |
| updates78 | perm_vision | +0.01008 | [-0.00384, +0.02362] |
| updates78 | no_wire | -0.00212 | [-0.00710, +0.00325] |
| time12 | perm_audio | +1.44256 | [+1.28629, +1.60356] |
| time12 | perm_vision | +0.06291 | [+0.01666, +0.10811] |
| time12 | no_wire | +0.01279 | [+0.00459, +0.02190] |

Higher NLL indicates worse log probability for the correct class. Actor intervals condition on the realized three seeds and test cohort. Permutations preserve the marginal distribution of each modality and reassign its clips across this held-out cohort. The no-wire intervention removes the second layer’s received boundary. Existing content/residual paths remain active. The fixed prompts define a supervised 72-way audiovisual retrieval task, with no free-form caption-generation endpoint.

The quantized signal retains about 34.1% of raw grey-level pixel variance and 20.5% of train-standardized acoustic variance on the held-out inputs under piecewise-constant reconstruction. In original grey levels, video RMSE is 21.57. Audio RMSE is .878 standardized units. These reconstruction metrics reflect lost fine structure. Task-relevant information loss may differ.

The registered study contains 24 SHA-identified neural states and a selected ridge solution. The artifact bundle preserves checkpoint bytes, every original clip identity, exact primary 72-way cold logits and all per-clip intervention scores. Colab’s returned file hashes and release receipt are separate from statistical qualification.

A separate physical CPU reloaded all 24 neural weights, rebuilt the ridge classifier and repeated the 81 cold conditions. Its 2,359,800 primary logits differed from T4 by at most 0.00001240. Per-clip NLLs differed by at most 0.00001203. The top-1 decision differed in 25 of 106,191 comparisons, including 7 primary comparisons. All occurred in the 78-update LIF checkpoints and reflected near-tied logits. These cross-device differences are preserved in `cpu_replay.json`.
