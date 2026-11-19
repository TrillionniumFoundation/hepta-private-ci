# HDCF V9 — real DINOv2 Beans features into the shared CellBank (retrospective)

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / NO MODEL SELECTION / NO FINALUSE / NO MAIN MERGE**

## Scope and provenance

This is a strict additive child of #2570 (`e9c700eb50961f9553015cb558d34a745aa9c5c2`). It changes **only three new research paths**, without touching the V8 converter, parent five-arm Head algorithms, Runtime, NDU, FinalUse, control-plane permission owners or `main`. The new bridge is specifically a **genuine original image-Encoder feature replay**, not a freshly trained multimodal unified Transformer.

Original successful E2 source run: [GitHub Actions 38680856403](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680856403), original head `927bf53b184c3947db17a129834046c5f03add04` (#2189). Its original archive IDs / exact outer ZIP SHA-256 are pinned in `original_beans_v9.py`:

| Archive | Original artifact ID | SHA-256 |
|---|---:|---|
| Source train/held real JPEG and train-only class identity | `11948574238` | `49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad` |
| Physical DINOv2 and Granite Bridge observations | `11949168280` | `92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e` |
| Withheld original TEST class labels | `11948269689` | `946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d` |

The original visual model is `facebook/dinov2-small@150c8e7bb7cef2d30ec31b13a517af14840ee3f7`, weights SHA `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1`. The original pinned dataset is `AI-Lab-Makerere/beans@27aa014ce09b193e1a6f58112d4a66e0eddb69c5`, with train/test source Parquet SHA-256 pinned and independently re-opened by the evaluator. Image preprocessor file SHA, original whole-source manifest, all source image digests and the DINO feature receipts must agree exactly. 36 TRAIN original DINO forwards and 24 TEST original DINO forwards were physically executed **in the earlier Actions run**; V9 performs **zero new DINO forwards**. Original producer-reported counts are not a host-signed GPU accounting receipt.

### Critical scientific distinction

The **original source problem is three-class bean leaf diagnosis** (angular leaf spot, bean rust, healthy), retrospectively stratified into original 36 TRAIN and 24 public TEST images. This V9 Head replay pre-registers a *derived* **binary task** `healthy_vs_diseased_binary_reanalysis` to match the existing HDCF binary V1 Head interface. Its binary Head accuracy is NOT the original study's 3-class accuracy. The original stronger frozen DINO visual prototype **20/24 three-class** result is independently replayed against true TEST classes and then **re-scored separately for the new binary task**. Do not directly compare binary candidate counts to original 3-class `20/24`.

Two logical Cell types are assigned using a registered, label-blind SHA-256 of each public case ID. This is intentionally *not* a biology- or disease-semantic split, and no strong task-specialization hypothesis is established just by classifying this small dataset. Every 384D DINO CLS feature is converted to one immutable image Token and its little-endian FP32 digest, then Q24-rounded by V8. A real Trainer with common sample order uses the **original inherited frozen / shared_dense / shared_one_touch / split / swapped** physical CPU SGD (256 updates per trained arm). Matched parameter counts must be exact; the original independent scalar Head replay re-executes the arithmetic, all 120 sealed held predictions and weight digests.

## Actual operational boundary

1. Download original **source and feature archives only** using GitHub Actions `actions:read` and verify exact ZIP SHA256; strip GH authorization when requesting the signed CDN URL. No source source assets are uploaded anew.
2. Audit all original JPEG/source digests, DINO feature bytes, model identity/preprocessor revision and their exact 36/24 sample set. Construct an immutable V8 bank and export V1 training bank; do not read the withheld archive or original TEST Parquet in this stage.
3. Run **existing** `physical_cli.py train` as an OS process; seal real CPU SGD outcome to a private file, with no TEST targets available.
4. **Only after the training file exists**, download held-target archive and independently re-fetch original publisher TRAIN + TEST Parquet at exact immutable source revision in the reviewer phase. Require whole-byte SHA256 and reconstruct the exact per-class sample selection and all 60 source IDs, original image hashes and actual labels.
5. In another process, run independent complete V1 replay/score and the original four-arm three-class predecessor score audit. Compare the new binary split against equal-touch shared Head and the original frozen visual prototype **as binary re-scored**, not as incompatible 3-class outcomes.
6. Upload only a small sanitized aggregate `HOLD_NO_GO_DENY_ALL` JSON receipt. Original model weights, image payloads, source texts, private labels, per-case predictions, V8 raw feature vectors, individual Head tensors and tokens remain unpublished.

Job security is bounded: separate commands and delayed label downloads do not create a cryptographically independent evaluator or OS sandbox. Public TEST labels have been published historically; retrospective archive replay is vulnerable to developer/model-selection leakage. Source and model origin signatures are absent. Full costs, GPU memory, p95/p99 and energy are not independently attested; the first E2 physical DINO wall time is inherited from the same original worker and the new CPU fit time is self-reported. The pretraining cost and previous E2 Granite/Bridge work cannot be ignored when comparing architecture TCO, even though V9 does not rerun them.

## Running original independently

On this branch in the exact HDCF parent checkout, `python3 -m unittest -v test_original_beans_v9.V9ContractTests` and `python3 -O -m unittest -v test_original_beans_v9.V9ContractTests` run hermetic source/adversarial tests. The original suite requires the three exact original ZIPs as `HDCF_BEANS_ORIGINAL_SOURCE_ZIP`, `HDCF_BEANS_ORIGINAL_FEATURE_ZIP`, and `HDCF_BEANS_ORIGINAL_TARGET_ZIP`; never call skipped original tests a pass. The pinned workflow `hepta-hdcf-original-beans-v9.yml` downloads these, runs every original test with **zero skips**, seals the physical five-arm CPU fit before downloading TEST labels, then revalidates two original Parquet sources and independently scores the complete original outputs. Missing or corrupted model/features/dataset/artifacts **fail closed** rather than using random/synthetic replacements.

Suggested independent comparisons after this candidate: equal-FLOP non-split Head capacity, external future source families, genuine image-required task adjudication, image-lesion / input substitution, matched visual-prototype controls, audio temporal pilot and physical CPU/GPU 64/256/1024/4096 Cell fanout cost. The first image original-data replay cannot prove this architecture wins or generalizes.

**Exact outcome remains `HOLD_NO_GO / DENY_ALL` regardless of retrospective binary score; no Cell Split or model promotion.** Global `blocking-ci` failures on unrelated Rust/security targets remain blocking and are not bypassed by this dedicated experiment.
