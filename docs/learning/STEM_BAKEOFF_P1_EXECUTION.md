# Hepta shared Stem P1: executable native candidate and evidence preflight

This additive slice extends research-only shared Stem bake-off PR #2970,
stacked on shared Encoder/Cell Head PR #2695. It is
**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO** and changes no production
Worker, NDU, selected Stem, effect issuer, credential manager or durable
memory writer.

## Executable artifacts

- qa/stem-bakeoff/native_latent.py defines frozen bidirectional PyTorch
  slot Transformer architectures with **148,845,312 parameters** for the
  150M arm and **302,309,376 parameters** for the 300M arm. Default meta
  instantiation counts shapes without allocating model weights. No trained
  checkpoint or multimodal teacher knowledge is included.
- LightCellHead owns only a Gate, zero-delta low-rank Adapter,
  Task/Action/Value/uncertainty Heads. Cell state comes from the caller;
  external Memory is represented by an exact digest, not by replicated
  model weights, optimizer state, or privately written facts.
- SharedStemServer performs exactly one **Python owner-level Encoder call**
  for many independent Cell Heads. It rejects stale generation, duplicate
  Cell ids, missing Memory binding, nonfinite slots and invalid local states
  before running the shared Encoder.
- evidence_gate.py is a separate fail-closed *admission preflight*.
  The original validate_result() in #2970 checks **JSON shape only**.
  It cannot prove inference execution, and its success is not admission.
  The preflight requires source/model/checkpoint digests, source-disjoint
  train/calibration/two future/OOD splits, bounded finite metrics, all six
  measured Cell scales, actual model-forward instrumentation claims, and
  terminal blocking CI on the exact HEAD. Its strongest possible result is
  REVIEW_REQUIRED, never production authorization. Independent auditors
  must inspect original artifacts and GitHub statuses themselves.

## What has and has not been proven

The local tests run a **small random/untrained PyTorch Encoder** on CPU,
count the two full-size model architectures on the meta device, demonstrate
zero-delta head parity, and fan out one Python Encoder invocation to 64
Cell Heads. This does NOT prove one physical backend forward, trained 150M
or 300M inference, target-host latency/energy, 4096-Cell scale, multimodal
quality, memory recall, System 2 emergence, or learning superiority.

The negative evidence tests reject bogus SHA256 digests, arbitrary all-true
gate booleans, nonfinite resource metrics, reused OOD source hashes, absent
model forward hooks, stale/cancelled/pending CI, and per-Cell backbone bytes.

## Keep teacher/control arms separate

EmbeddingGemma 2 remains the short-term shared perception/Memory candidate;
the frozen existing 421M remains a cognition CONTROL, not a replicated
Cell model. T5Gemma 2 Encoder remains the long-context alternative: the
270M/270M encoder-decoder family has around 370M total parameters excluding
vision owing to shared embeddings/attention, and official model weights
require acceptance of the Gemma terms.

EmbeddingGemma 2 unifies text, image, audio and video embeddings. Selective
text-only, text+image, text+audio and full model loads are approximately
270M, 440M, 570M and 740M. Every 512/256/128-dimensional Matryoshka
truncation from 768 dimensions requires a fresh L2 normalization before
cosine similarity; different dimensions must never be compared directly.
Its pooled embeddings cannot substitute for token/slot reasoning states.

## Remaining blockers

1. Exact original-model checkpoints and accepted licenses; actually execute
   the pinned EmbeddingGemma 2 and T5Gemma 2 teacher comparisons with
   independent resource and model-forward instrumentation.
2. Train and freeze native 150M/300M students on aligned multimodal and
   long-context teacher targets. Prevent held-label leaks; preregister
   untouched future/OOD cohorts and Cell replay/calibration tests.
3. Measure one shared Encoder execution on actual target hardware, at
   1, 8, 64, 256, 1024 and 4096 active Cells, including p95/p99, memory,
   energy and Head/slot/projection/cache costs. Python owner call count is
   not sufficient.
4. Repair real repository-wide security, Bazel/cross-platform and test
   failures; require terminal exact-head blocking-ci, Architecture and
   V8 results. Queued/cancelled/skipped do not count as success.
5. Keep NO_MODEL_SELECTION / NO_FINALUSE / NO_PHYSICAL_CELL_SPLIT and
   SHADOW_ONLY / DENY_ALL until independent authority/owner review.

Local smoke: python3 -m unittest discover -s qa/stem-bakeoff -p test_*.py -v

## P2 multimodal slot differentiation + offline distillation

- `qa/stem-bakeoff/multimodal_bridge.py` adds a **shared**, trainable per-modality
  projector and cross-attention latent slotizer with an explicit missing mask,
  bounded token budgets, time tags for audio/video/UI events, generation and
  SHA256-shaped source references. It accepts precomputed features only and
  never fetches teacher weights or allocates per-Cell modality towers.
- An EmbeddingGemma 2 pooled output is **one** source token, not proof of image
  regions or temporal reasoning. T5Gemma 2 hidden states and specialist tower
  tokens need real, pinned and independently audited producer receipts.
- `shadow_distill_step` supports a small, *offline* trainable student using
  MSE/cosine alignment against detached teacher features. Neither synthetic
  toy-step improvements nor caller-provided SHA strings prove pretrained
  knowledge, modality utility, provenance, future/OOD gains or production use.
- Tests check real tiny CPU forward/backprop, Gate/Head separation, temporal
  ordering, missing-mask provenance, invalid inputs, and detached teacher
  targets. The shipped 150M/300M variants remain **untrained blueprints**.
