# HDCF V12: original DINO + Granite text-cue membership stress test

**RESEARCH_ONLY · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MODEL WINNER · NO CELL SPLIT · NO FINALUSE · NO MAIN MERGE**

## Exact source and lineage

This is an additive child of V11 PR #2645 at **`8d86a8921fa3db341f8264adf8d6a5a81b9b40b3`**. The original 36 TRAIN / 24 historical TEST Beans visual features and three frozen TRAIN Granite text class prototypes were produced during original E2 [Actions 38680856403](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680856403). SHA-pinned original source ZIP `49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad`, model feature ZIP `92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e` and *separately withheld* label ZIP `946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d`. The original producer reported 60 DINO forwards and 18 Granite forwards across three original text classes. **No new pretrained forward in V12.** Image originals are real leaf JPEGs; text queries are the *three constant disease class prompts*, NOT novel language questions, arbitrary captions, human-moderated image/text necessities, or independent source families.

## Research task and negative controls

For each original image, make three candidate pair queries: "is this photographed leaf an example of the text class [angular_leaf_spot / bean_rust / healthy]?" The learner sees **36 TRAIN images × 3 already-encoded genuine Granite class-text queries = 108 membership pair decisions** with one positive per image. The source partition seals the original **24 historical TEST images × 3 = 72** candidate decisions **without any original TEST targets**. This is an image-conditioned class-name membership grammar, not a generic text-image model or a true new future window. Analyze *24 image clusters*, not 72 independent question sources.

One rank-8 bilinear Organ has **6,144 independently trained FP64 parameters** (384×8 on each side), 160 full-batch CPU SGD steps, fixed seed `1197`, fixed `LR=0.3`, softmax scale `24`, and L2 `0.0001`. A second **real independently executed 160-step SGD** Organ receives a fixed signed orthogonal permutation of the Granite class embeddings; its input projection is permuted compatibly so both models begin with exactly identical scores. This null retains the exact class-prototype Gram matrix. The training objective is invariant under this transformation; the small numerical prediction difference is an expected finite-precision effect, **not an indication of learned class-name semantics**. Negative comparison is the same source DINO-only TRAIN Ridge classifier (regularization `0.1`), original archived frozen DINO nearest prototype, zero-fit original DINO-to-Granite cosine, and a deliberately wrong text-cue permutation. The vision Ridge and DINO-prototype both know the query **class identity** when deciding membership; it would be misleading to compare only against a blind always-no model.

The original source/feature ZIP outer hashes, all 60 JPEG original SHA256s, 36 train-only labels, all DINO receipt/weights/preprocessor revisions, original Granite target source IDs/32-bit feature representations, three repeated proto identities, 24 feature-only held cases, and frozen visual-prototype predictions are checked before any training. Original held targets are absent from the training process. A separate reviewer later downloads original held label ZIP plus publisher TRAIN/TEST Parquets, requires exact original immutable file hashes and reruns original V9 source/label re-selection, and then independently scores the model's already sealed per-image 3-option predictions. Both jobs upload **sanitized aggregates only**; raw JPEG/text, labels, per-case scores, model weights and optimizer tensors stay in ephemeral run-local files.

## Genuine local CPU evidence, not external-host qualification

With exact authenticated-by-expected-SHA research ZIP bytes and NumPy float64 2.3.5, both rank-8 Organs actually ran for all 160 SGD steps. Genuine historical TEST outcome is **20/24 image decisions and 64/72 derived pair members** for the trained real-proto Organ; signed-isometry null **20/24 and 64/72**; DINO-only Ridge **20/24 and 64/72**; original frozen DINO **20/24 and 64/72**; untrained direct cosine **8/24 and 40/72**; wrong-cue permutation **1/24 and 26/72**. Organ vs original DINO: 1 gained image, 1 lost image, case-level exact nominal p=1. Organ vs DINO-only Ridge: zero discordant image correctness, case-level exact nominal p=1. The signed isometry control max absolute score difference was approximately `1.13e-12` (under `1e-8` contract). This **falsifies interpreting this class-prototype data as independent evidence for cross-modal semantic grounding or Organ superiority**. Do not interpret p-values as validity certificates: all 24 historical TEST samples come from the same original publisher and are not prospective future observations.

The input source and class labels are all retrospective public information. Output was never independently future-prospectively held by a distinct real-world evaluator. Only the original pretrained-model producer's backend self-reported CPU cost is inherited; V12 CPU times/SGD touches are local self-reported, and no end-to-end GPU/RSS/p95/p99/energy/pretraining TCO/rollback or independent model publisher attestation is supplied. Matched rank-8 Organ parameter counts do not imply equal Transformer FLOPs or complete lifecycle cost. The original sparse runtime and HNMF, CAS/CNS, NDU, FinalUse, native action, and production Stem remain unmodified.

## Reproduce

Local, when given the **exact original ZIPs** (no synthetic substitute), set `HDCF_V12_SOURCE_ZIP`, `HDCF_V12_FEATURE_ZIP`, `HDCF_V12_TARGET_ZIP`, then run:

```sh
cd qualification/hdcf-research
OPENBLAS_NUM_THREADS=1 python3 -m unittest -v test_organ_query_binding_v12
OPENBLAS_NUM_THREADS=1 python3 -O -m unittest -v test_organ_query_binding_v12
```

The dedicated push-only workflow `hepta-hdcf-original-query-binding-v12.yml` fetches original pinned ZIPs, trains the original two Organs **before fetching TEST labels**, records the exact sealed prediction SHA, then obtains publisher original Parquets and runs the external held-label scorer in a distinct step. It refuses to write `production_authorized=true`, refuses to claim independent source families, and retains negative comparison results. Dedicated CI plus non-relaxed existing `blocking-ci` must actually pass before an engineering completion statement; even green experiment CI cannot authorize model/Cell promotion.

## Required next science evidence

At minimum: genuinely independent source issuers, new future time windows, genuinely text-dependent and image-essential natural tasks with fresh text cues (not three label-class prototypes), paired image intervention and text ablations, frozen/vision-only/param-matched Organ/Cell controls, actual CUDA/CPU service metrics, and old-task retention/rollback evidence. Until then: **`HOLD_NO_GO_DENY_ALL`**.
