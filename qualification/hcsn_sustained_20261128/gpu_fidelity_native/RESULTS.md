# Qualification on full-resolution CREMA-D features

The private Tesla T4 checked two locally installed FFmpeg versions. The 9.0.2 candidate failed the six frozen pixel-and-acoustic pilot checks. The Ubuntu 6.1.1 binary (`ed16af623947494a72e284b6eb8ff225f2da22b38b5d5069c2fd4b4ba3384e41`) passed all six. The provider reported actual hard and soft per-file ceilings of 33,554,432 bytes. The 48- and 168-clip tiers reproduced both original tensor arrays and ordered identifiers exactly. Of the 672 attempted, 671 decoded successfully. A separate comparison with the entire original archive reproduced every image and audio SHA for those 671, totaling 1,342 physical checks, comprising 384 training, 95 development and 192 cold clips. The 672 tier therefore did not qualify.

The failed source `1076_MTI_NEU_XX`, original row 6186, is a 35,166-byte, three-frame, 836-sample development clip. All 7,442 original media records were checked. The original first-pass guard affected exactly zero training clips, one development clip and zero cold clips. The project's archived #8559 repair used the three images at twelve temporal centers (four copies each) and selected the eight raw acoustic windows at indices 0,1,1,2,3,3,4,5,5,6,7,7. Re-decoding this public FLV using the original pinned FFmpeg reproduced both stored tensors. The subsequent disjoint-volume worker incorporates the archived method with the same per-clip SHA requirement.

| Six-layer width-96 model | Parameters | 12 synchronized train steps, s | Cold NLL | Cold top-1 |
|---|---:|---:|---:|---:|
| Literal | 731,168 | 2.836 | 4.57076 | 2/48 |
| Smooth | 731,168 | 2.290 | 4.61950 | 3/48 |
| LIF | 731,168 | 1.346 | 4.49193 | 0/48 |
| Causal SDPA | 673,056 | 0.657 | 4.24726 | 5/48 |

Each arm used the same seed, 96 distinct available training clips, 288 batch presentations, 24 development clips and 48 held clips. The study does not determine generalization at convergence. All four development and held logit matrices and exact labels were independently rescored, with a maximum summary discrepancy of 8.89×10⁻¹⁶. The 13,824 held logits come from four arms, 48 samples and 72 fixed text prompts. The cloud program took 175.47 seconds including 161.42 seconds to acquire and verify inputs. Its four artifacts were collected and its runtime released.
