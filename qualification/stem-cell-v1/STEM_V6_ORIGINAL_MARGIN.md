# V6 — Original multimodal margins and numerical stability

DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. Original pretrained Granite97 + DINOv2-small ScienceQA E3 GitHub run 38678847948; immutable artifact 11947722496, outer ZIP SHA256 f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30. No model training or new forward in V6, no label ownership, no model selection, no production authorization.

## Actual source-bound execution

Independently reopened the original exact 14-member E3 archive and 64 original model prediction rows. The V6 audit requires original prediction SHA256 e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7, exact source SHA, eight arms, no-privilege status and text-only == image-masked control. All source and model identities remain frozen.

For each visual arm, check both original text and visual model top1-top2 probability gaps. A visual class disagreement is **certified stable under L-infinity perturbations of each probability by epsilon** only when both output gaps exceed 2*epsilon. This is a mathematical argmax certificate, NOT actual physical image perturbation, causal visual necessity, or proven correctness.

| Original visual arm | Changed argmax / 64 | Stable at epsilon=0.001 | Stable at epsilon=0.005 |
| --- | ---: | ---: | ---: |
| Trained visual Gate | 38 | 24 | 3 |
| Trained image-only Bridge | 50 | 33 | 5 |
| Trained equal Bridge fusion | 26 | 14 | 0 |
| Rotated Bridge negative control | 28 | 11 | 1 |
| Text-only / masked / calibrated-to-text | 0 | 0 | 0 |

Mean raw top1-top2 margins: trained Gate 0.010357, image-only Bridge 0.009435 and bridge equal fusion 0.007122. Many class changes are near decision ties. Inference drift, trained image utility and human visual necessity must not be inferred from these numbers alone.

## Reproduction and explicit limits

Source: scienceqa_margin_stability_v6.py. Negative tests: test_scienceqa_margin_stability_v6.py. Original digest-bound eight-arm result: STEM_V6_ORIGINAL_MARGIN_20261016.json. All three files byte-match the tested local Git blob identity. Actual original archive analysis passed; local 4/4 ordinary and 4/4 Python -O tests passed. The read-only exact-HEAD hepta-stem-v6-original-margin.yml workflow must separately finish its original-archive stage before the GitHub-hosted result can be called passed.

No individual original inputs, labels, model weights or private source media are published. The JSON is aggregated-only. This is a fixed historical panel, without independent issuer signatures, prospective task windows, equal lifecycle cost, task semantic adjudication, 4096-Cell learning, multimodal generation, NDU or System2 efficacy.

The next **physical** causal experiment must rerun frozen original pretrained model/vision and unchanged trained Head for identical source IDs with correct-image, deliberately different-source-image and masked-image interventions. The original archived probabilities cannot simulate this. No promotion, Cell Split, FinalUse or main merge.
