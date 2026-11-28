# What a null-space edit changes in an audiovisual HCSN

Three already trained width-96 HCSN parents were edited to cyclically reassign the six emotion labels of one transcript. Every fit used the 366 training clips from that transcript. The held panel contains 96 edited-task clips and 1,215 retained-task clips, with all 72 gallery prompts available. All eighteen candidate matrices were sealed before scoring. The experiment implements the explicit AlphaEdit-style null-space constraint at a known 256×96 shared projection. It tests a synthetic localized relabeling on a weak parent. LLM fact localization and target-value estimation are outside this experiment. See [protocol](PROTOCOL.md).

| Matrix edit | Edited-task NLL ↓ | Edited top-1 | Retained-task NLL ↓ | Retained top-1 |
|---|---:|---:|---:|---:|
| Unchanged parent | 4.47666 | 0.69% | 4.13464 | 3.54% |
| Unconstrained ridge | 4.13863 | 10.76% | 4.32578 | 0.66% |
| Null-space, 72 protected text keys | 3.55184 | 20.49% | 4.44015 | 0.08% |
| Null-space, text plus 8 audiovisual anchors | 3.92420 | 11.46% | 4.28897 | 1.40% |
| Null-space, text plus 32 audiovisual anchors | 4.47666 | 0.69% | 4.13464 | 3.54% |
| AdamW, 16 steps with eight audiovisual anchors | 3.64872 | 10.76% | 4.34266 | 0.33% |

With only text keys protected, the input null-space dimension is 24. The raw changes on the protected text keys remain below 7×10⁻⁸, yet the audiovisual queries move. Against the unchanged parent, edited loss improved by 0.92482 nats (paired actor 95% interval 0.86232–0.98672), while retained loss increased by 0.30551 (0.27593–0.33796). Eight additional protected audiovisual keys leave 16 dimensions. The corresponding differences are −0.55246 and +0.15433. With 32 additional keys only one numerical dimension remained in these fits. Held top-1 decisions matched the original and mean loss changes were below 2×10⁻⁹. Exact preservation of the selected gallery vectors and preservation of unseen query behavior are different measurable conditions. This experiment is evidence for targeted post-training adaptation and its capacity cost. See [fit identities and rank diagnostics](fits.json) and [per-seed held measurements](terminal.json).
