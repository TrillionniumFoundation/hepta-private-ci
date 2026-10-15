# Original E3 ScienceQA multimodal gate: real pretrained archive, no admitted Stem winner

**2026-10-15 / DRAFT / SHADOW_ONLY / DENY_ALL.** No selected Stem, FinalUse or `main` mutation.

Original successful pretrained execution: [Actions run 38672941350](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38672941350), source `b8b2f10fe38506972301e77e3836729a90200673`. GitHub original artifact #11945106672 SHA-256: `7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30`. The independent Python auditor checks the entire ZIP against this literal checksum, every internal `SHA256SUMS` member and the original prediction-seal digest. It validates 64 unique case hashes, all 8 probability arms, original source/label digest linkages and displayed model revision/forward-count claims. **This is archive-source consistency, not an independent publisher/hardware signature.**

| Observed retrospective 64 ScienceQA questions | Correct | Accuracy |
| --- | ---: | ---: |
| Text only / image masked | 17 | 26.56% |
| Frozen image+text unaligned mean | 10 | 15.63% |
| Rotated TRAIN-target fusion | 19 | 29.69% |
| Fitted Bridge + image only | 21 | 32.81% |
| Fitted Bridge + equal image/text | 16 | 25% |
| **Learned 769-parameter Cell gate** | **24** | **37.5%** |
| Calibration-selected fixed fusion | 17 | 26.56% |

Image and question text are actually processed through the pinned original pretrained Granite97 and DINOv2 source in that successful workflow, with **60 declared text and 24 declared visual forward batches**. It learned an Organ Bridge and 769-scalar Cell gate, but labels and model source were not independently attested outside the workflow.

**Critical statistical finding:** Train gate versus text-only: +7 net correctly answered, but unadjusted exact paired McNemar p=`0.18924713134765625`; with six exploratory arm comparisons, Holm-adjusted p=`0.9462356567382812`. The smallest other unadjusted p=`0.143463134765625` also has adjusted p=`0.86077880859375`. Neither crosses 0.05. This is an *underpowered negative/null on the present retrospective task*, not evidence of model equivalence or a reason to assert zero possible future gains.

**Critical calibration finding:** Original CAL-selected fixed visual coefficient is **0.0**, and both `calibrated_fusion` and `image_masked` match `text_only` exactly for all 64 heldout predictions. Training-gate predictions do differ (38/64 top-1 class choices changed, average L1 probability shift about `0.0354`), but changed predictions alone are not better decisions.

**Limits:** Neither heldout image-essential labels nor original per-case ground-truth answer labels are in the public ZIP; therefore this independent auditor recomputes *probability/source linkage, paired exact p from originally reported discordance, and multiplicity correction*, **not independently scored correctness from retained answer labels**. The ScienceQA source release is retrospective, not independent future1/2/3, and there is no cost/parameter-matched 421M, native EmbeddingGemma2, human-reviewed factual counterfactual, SRE/GPU/p99, WIP/FinalUse or production authority evidence.

**Decision:** Freeze any claim of demonstrated crossmodal advantage. Keep shared low-cost visual/classification Cell as control; next compare tasks where visual and language premises are jointly necessary with pre-registered test membership, true independent label source, image masking/swap controls, and equal total compute, before investing in more Bridge parameters or FBSDE System 2.
