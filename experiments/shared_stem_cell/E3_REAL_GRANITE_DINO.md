# E3 actual Granite 97M text Stem → DINOv2-small Vision → learned Organ Bridge + 769-scalar Cell gate

**Research / SHADOW_ONLY / DENY_ALL — never a production selection or a native Neuron model installation.**

This small additive child of the current #1885 multi-modal shared Stem research
has four original executable stages rather than a simulated claim of vision:

1. **Pin public original source.** `e3_scienceqa_stage.py` requires the literal
   `lmms-lab/ScienceQA-IMG@b9984af01798586705cee1fbdfa80a6dcbef04f1`
   dataset revision, original train/validation/test parquet inventory, bounded
   publisher file size/LFS digests and original embedded image bytes. It
   predeclares 96 TRAIN / 32 VALIDATION / 64 TEST cases. Source membership is
   selected from public `image/question/hint/choices` only, by fixed content
   hash ordering, with pixel and question leakage checks across partitions.
   Original answers are accessed **only after** the whole input cohort has been
   sealed. Answer-bearing solution, lecture, labels, grade and other target
   metadata are never accepted as model inputs. Sources retain their original
   split identity. The publisher TEST split is **NOT** a new future-time window
   or externally sealed semantic-necessity judgment.
2. **Load actual weight files or fail.** `e3_granite_dino_real.py` requires exact
   immutable public original-weight commits, from publisher inventories:
   `ibm-granite/granite-embedding-97m-multilingual-r2@835ad14087e140460703cf0fae09f97d469d65c2`
   and `facebook/dinov2-small@ed25f3a31f01632728cabb09d1542f84ab7b0056`.
   Only safetensors/json/tokenizer assets are staged, with every downloaded
   file's bytes rehashed and original available LFS digest matched. The existing
   strict `execution.LocalEncoder` owner executes Granite with **CLS+L2** pooling.
   Stock `Dinov2Model` executes images using its exact saved-weight equality
   verification, original processor and **CLS+L2** pooling. No pickle,
   `trust_remote_code`, model fallbacks, Meta tensors, proxy model, or
   substitute synthetic vectors are accepted in the physical job. Count actual
   physical forward **batches** and total load/acquisition/training wall time.
3. **Train only on TRAIN.** Fit one shared, 384-to-384 FP64 ridge Organ Bridge
   (147,840 parameters including intercept), an independently rotated TRAIN
   target-label negative control, and one zero-initialized 768-to-1 sigmoid
   **Cell gate of exactly 769 trainable parameters** with actual 80 AdamW steps.
   CALIBRATION may only choose a weight from a fixed set `{0, .25, .5, .75, 1}`.
   One frozen text encoder and one frozen vision encoder encode source rows;
   per-Cell training updates only the private gate, not pretrained weights.
   Predictor's CLI accepts TRAIN+CAL labels, never TEST labels or held-target
   arguments. Predictions are sealed to an exact SHA **before** TEST labels are
   opened by a separate scoring process.
4. **Independent implementation scores original task outcomes.**
   `e3_scienceqa_review.py` does not import the producer/optimizer. It reopens
   exact source/question/image hash identity, verifies 64/64 original TEST
   labels and all eight complete probability arms, recomputes four-class
   accuracy/Brier/NLL, paired lost/rescued cases and unadjusted exact McNemar.
   The original-source held-out label producer and model runner are within
   one workflow/owner, therefore this separation is **procedural**, not an
   independent cryptographic external observer. Image swaps are **not** scored
   as ground-truth truth flips without a separately adjudicated correct answer.

## Predeclared matched arms

| Arm | Frozen text | Frozen DINO | Organ Ridge | Trainable gate |
| --- | --- | --- | --- | --- |
| `text_only` | Yes | no contribution (physical extraction still charged) | No | No |
| `unaligned_equal_fusion` | Yes | Yes | No | No |
| `rotated_equal_fusion` | Yes | Yes | rotated TRAIN target | No |
| `bridge_image_only` | option strings | Yes | TRAIN label bridge | No |
| `bridge_equal_fusion` | Yes | Yes | TRAIN label bridge | No |
| `train_gate` | Yes | Yes | TRAIN label bridge | 769 scalars |
| `calibrated_fusion` | Yes | Yes | TRAIN label bridge | fixed CAL-selected scalar |
| `image_masked` | Yes | physically zero contribution | No | No |

The `image_masked` arm must reproduce `text_only` bit-for-bit. All arms reuse
exact original source and feature tensors. The full acquisition/inference cost
of each physically loaded model is reported separately: shared weight residence
is not confused with saved model-forward FLOPs.

## Run and results boundary

The dedicated `.github/workflows/hepta-e3-granite-dino-scienceqa.yml` invokes
actual pinned source/model acquisition on push to the new isolated E3 research
branch, then the existing original strict Granite loader, full DINO tensor
materialization audit, fitting and SHA-sealed prediction. A separate scoring
process opens original TEST labels **after** sealing. Artifacts are sanitized:
source identities, original per-case probabilities and aggregate scores may
be retained; raw images, dataset parquet, checkpoint weights and tokenizer
material are **not** uploaded. A failed source acquisition or pretrained model
load is a failed workflow, never a successful fake-model result.

Local dependency-light tests (with actual CPU Torch SGD and f64 ridge on
**explicitly synthetic feature vectors**) run as:

```bash
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p test_e3_scienceqa_real.py -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_e3_scienceqa_real.py -v
```

For an operator-staged offline source with the exact pinned model material,
see the four CLI `--help` interfaces. The physical CI is the canonical end-to-end
entry. **No local unit test is a genuine pretrained-image result.**

## What this experiment does NOT prove

- It does NOT compare independent 421M model replicas or EmbeddingGemma 2 native
  vision at equal total hardware work. It is a Granite/DINO image-to-text
  bridge feasibility test, not global Stem selection.
- It uses a ScienceQA historical source release, not independent prospective
  future-1/future-2/future-3 source groups or an adjudicated image-essential
  counterfactual. Some questions are solvable by text alone. A model preferring
  the image need not have better semantic or relational understanding.
- A ridge Organ Bridge has more than 9.7k parameters but is shared across all
  logical Cells; the **separate** Cell gate uses 769. Comparing against a full
  421M model must include all shared towers and bridge acquisition, training,
  inference, memory, and possible decoding/verifier costs.
- Current exact-source CI, independent publisher/host signatures, target-host
  64/256/1024/4096 native Worker throughput/RSS/p99/recovery, NDU prospective
  utility, capability authorization, and complete-task semantic provenance remain
  separate blocking gates. Original Neuron Q24 journal, Worker, NDU, CNS,
  Artifact CAS, FinalUse, model selector, production releases and `main` stay
  **unchanged**.

Decision: `stem_winner=null; production_accepted=false; authority=DENY_ALL`.
