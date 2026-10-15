# Independent archived ScienceQA E3 readout — genuine pretrained path, no Stem selection

**DRAFT · SHADOW_ONLY · DENY_ALL.** This child stacks solely on frozen #2173
at source HEAD 2dc43da7d9bf343acc871219ddce44d0e14d8911.
It adds an independent standard-library archive reviewer and a GitHub Actions
workflow. No model weights, Head training, original scorer, Neuron/Worker,
FinalUse, NDU, CNS, Q24, CAS, production selector or main branch is modified.

## Origin and what actually executed

Original PR #2173 run 38678847948 concluded **SUCCESS** after its original
ScienceQA data stage, actual Granite97 and DINOv2-small model forwards,
shared 147,840-parameter Ridge Organ Bridge fitting, private 769-parameter
Cell gate with 80 SGD/optimizer updates and independent heldout 64-row score.
The 20 new and 27 inherited local-contract methods ran on the Actions host
in ordinary and Python -O modes. This statement is grounded in that original
run's complete per-step log, not a source-only canary.

Original archived artifact ID: 11947722496.
Exact ZIP SHA-256:
f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30.

Original GitHub PR HEAD: 2dc43da7d9bf343acc871219ddce44d0e14d8911.
Base: b8b2f10fe38506972301e77e3836729a90200673.
GitHub PR test merge checkout:
095769f27c6b2861460b385e297540081a26af05.
The latter is a **synthetic merge commit** with the exact original
HEAD/base as its parents. Do not falsely label it the source branch HEAD.

The audit verifies these identities from live GitHub read-only metadata,
the complete ZIP digest and original archive SHA256SUMS, actual frozen
model revision names, source/prediction/held-label seals, required
Head/Bridge budgets and every reported paired count and exact McNemar p.
It does NOT import or trust the original producer code for arithmetic.

## Original descriptive 64-example TEST outcomes

| Arm | Correct / 64 | Accuracy | Relative to text |
| --- | ---: | ---: | ---: |
| Text only | 17 | 26.5625% | baseline |
| Unaligned equal fusion | 10 | 15.6250% | -7 |
| Rotated TRAIN bridge | 19 | 29.6875% | +2 |
| Trained Bridge: image only | 21 | 32.8125% | +4 |
| Trained Bridge: equal fusion | 16 | 25.0000% | -1 |
| Private learned gate | 24 | 37.5000% | +7 |
| Calibration-selected fixed fusion | 17 | 26.5625% | 0 |
| Image masked | 17 | 26.5625% | identical |

Relative to text, learned gate rescued **14** cases and harmed **7**.
The independently recalculated unadjusted exact two-sided paired McNemar
probability is **0.18924713134765625**. Six-arm Bonferroni correction
is **1.0**. This is an exploratory positive signal, **not statistically
established benefit** and not an allowed model-selection result.

The CAL-selected fixed visual weight was **0.0**, exactly pure text.
Source-reported original model forward batches: **60 text / 24 vision**.
Source-reported acquisition-plus-fit wall **48.154727451 s**; measured
inner compute phase **38.128502106 s**. These are ONE research host's
observations, not end-to-end baseline-matched FLOPs, power, GPU/CPU
p99, energy, or production peak RSS. Peak RSS and energy are absent.

## Exact evidence boundaries

- Original TEST labels are withheld from the uploaded model prediction archive;
  this separate readout therefore verifies numerical **reported** correctness
  and paired-count consistency, not original human labels independently.
- ScienceQA is a historical public test split. True prospective source
  families/windows 1–3 and independent visual-necessity ground truth are absent.
- It cannot prove genuine visual causality, natural image-required improvement,
  negative-transfer safety, Cell Split/NDU gains or target-host 4,096-Cell readiness.
- CI read-only token can fetch original run/artifact metadata but does not
  authenticate publisher signatures or provide external label ownership.
- **No Stem winner. DENY_ALL.** Failure, skipped job, green source-only
  contract, or pending archive audit never permits promotion.

## Next experiment

Use exactly the same source/label provenance and preregister a
label-blind five-arm comparison: text-only; OCR→text; unaligned visual
feature; learned Granite97/DINO Organ Bridge with per-Cell gate; native
EmbeddingGemma 2 with a capacity-matched train-only task Head. Report
matched inference+load+training costs, grouped paired outcomes, image-
evidence interventions with separate reviewed labels and future windows.
Do not equate a multimodal embedding with an image-generating VLM.
