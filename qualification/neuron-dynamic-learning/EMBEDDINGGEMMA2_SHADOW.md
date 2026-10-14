# EmbeddingGemma 2 Stem / multimodal Cell shadow candidate

**Status: EXPERIMENT ONLY.** This work is an additive child of #1503's
research branch, which itself stacks on native shared-feature #1498. It does
not select/replace the existing Laya baseline, issue FinalUse, install native
models, change organ topology or claim new intelligence. No model weights,
media datasets, training outcomes or real host benchmarks are committed here.

## Stage 1 — frozen baseline and candidate identity

- Preserve Laya 421M/322M and mmBERT/ModernBERT comparison from the existing
  research lanes. `embeddinggemma2_shadow.py` adds only
  `google/embeddinggemma-2` as a *separately qualified* candidate. The official
  model card: https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2
- Before inference the local manifest MUST include a 40-hex Hugging Face commit,
  every local file with SHA256 (including weight shards), exact runtime package
  versions, Apache-2.0 license, precision, dimension and modality profile.
  Source revision is a claim until independently compared against remote source
  metadata. No automatic download, `trust_remote_code` or floating refs.
- The profile sizes are **nominal**: text 270M, text+vision 440M, text+audio
  570M, all 740M. Actual loaded tensor count/residency must be measured.
- The model must execute float32 or *supported CUDA* bfloat16, **never fp16**.
  Official multimodal docs:
  https://ai.google.dev/gemma/docs/embeddinggemma/multimodal-embeddinggemma-with-sentence-transformers

## Stage 2 — scoped shared Encoder / Cell Head

- Exact Scope, Principal, Purpose, Generation, Authority Epoch, source SHA256,
  role and modality gate feature reuse. The **complete** joint question/options/
  state should be serialized with `offline_stem.joint_text` before admission if
  this stem is used for decisions. A vector of state alone is not equivalent.
- Per-Cell independent dynamic heads/SGD, 2K/8K/16K ablations and immutable
  Q24 artifact export belong to pre-existing `cell_learning.py`. No new owner,
  cache, trainer or authority is created by this candidate.
- EmbeddingGemma 2 has 768d native features. `truncate_dim=256` and
  `normalize_embeddings=True` implement the official Matryoshka path. Only 128d
  or 256d may currently export a neuron-pilot Q24 feature; 512d and 768d
  require a separately registered, versioned runtime profile, not silent truncation.
- Encoder API-call counts are **not** physical forward counts. A real local
  model invocation is not an independently signed model receipt.

## Stage 3 — optional vision, audio, video qualification

- `embeddinggemma2_shadow.py` verifies local image/audio/video bytes, sizes,
  extensions and media SHA256; network URLs and symlinked paths are forbidden.
  It uses official `SentenceTransformer.encode` modality dictionaries and
  supports only four whitelisted selective-load profiles.
- `embeddinggemma2_pairs.py` runs true encoded text/media pair retrieval on
  independent test/future groups with chronological ordering and anti-leakage
  checks. At least two independent case groups per ranking cohort are required.
  It reports actual recall@1 per direction, never synthetic model accuracy.
- This 256d paired retrieval gate does **not** establish GUI localization,
  audio transcription, temporal causal reasoning, visual grounding or
  generative Reader capability. Separate task evaluations are required.

## Stages 4–5 — Organ learning / differentiation / Stem consolidation

- Reuse the existing `organ_transfer.py` with equal-capacity frozen controls and
  real future data. Retain old-task preservation and negative-transfer slices.
- `differentiation_gate.py` screens reuse, Head, Organ adapter, Cell LoRA,
  split/merge/retire and shared Stem consolidation proposals. At least three
  independent future windows, positive gain **lower confidence bound**, no
  group leakage, retention/OOD/calibration and no higher matched total cost are
  required for `READY_FOR_INDEPENDENT_REVIEW` (not promotion).
- A self-reported `independent_outcome` flag or nonzero digest does **not**
  authenticate evidence; `learning.eval`, artifact, training-purpose/consumer,
  revocation and existing selection/FinalUse owners must verify it themselves.
  Every output from these files explicitly retains `production_promotion=DENY_ALL`.

## Run without downloads or production authority

Install a **separately pinned** local runtime matching your reviewed manifest,
including SentenceTransformers/Torch/Transformers. For text-only profiles the
required runtime keys are `torch`, `transformers`, `tokenizers`, `safetensors`,
`sentence-transformers`; multimedia profiles also require `pillow`, `soundfile`,
`torchcodec`. Keep the snapshot and media root outside the repository.

```bash
python3 -m unittest discover -v -s qualification/neuron-dynamic-learning -p 'test_*.py'
python3 qualification/neuron-dynamic-learning/embeddinggemma2_shadow.py \
  --manifest /approved/stem/manifest.json \
  --requests /approved/stem/approved_requests.json --device cpu
python3 qualification/neuron-dynamic-learning/embeddinggemma2_pairs.py \
  --manifest /approved/stem/manifest.json --pairs /approved/stem/paired.json \
  --media-root /approved/media
python3 qualification/neuron-dynamic-learning/differentiation_gate.py \
  --candidate /approved/evaluation/advisory_candidate.json
```

No revision, GPU/CPU runtime, pair dataset, historical source validation,
predecessor receipts or signed reviewer attestations are included; therefore
**no physical EmbeddingGemma 2 experiment or model-improvement claim follows
from passing the offline contract tests.** This branch is a new experiment
surface to evaluate, not a replacement for the native owner stack.
