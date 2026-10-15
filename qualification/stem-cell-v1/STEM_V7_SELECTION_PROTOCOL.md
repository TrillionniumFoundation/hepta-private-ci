# V7 shared Stem selection, multimodal differentiation and fleet cost gate

**Research only — DRAFT / SHADOW_ONLY / DENY_ALL. No model selection or production activation.**

This is an additive qualification layer stacked on the completed V6 bridge study in
`research/cross-fact-bridge-v6-20261015` (PR #2338). It does not modify the
frozen V5/V6 training runtime, existing pretrained assets, Rust serving owner,
NDU, signed FinalUse/CNS/CAS or `main`. The fixed-budget cross-fact/global/local
research in #2351 remains an independent sibling; do not overwrite its controls.

## Aim and decision rule

Select the Stem and differentiation architecture that minimizes **complete
lifecycle cost at independently verified task success and retention floors**,
not the architecture with the fewest weights or highest retrieval score.

Three orthogonal questions must be isolated:

1. **Shared weight and forward reuse**: same 421M original weights, tokenizer,
   actual input bytes and Head checkpoint under shared versus replicated
   residents. Expect identical deterministic answers; any difference is a
   protocol or implementation failure, not extra learning.
2. **Text Stem choice**: original fixed-budget 421M, original Granite97,
   mmBERT-small and EmbeddingGemma2 text path, with identical training
   examples, physically equal Head parameter budgets, recorded training
   compute and fixed Reader. Do not call nominally equal step counts equal
   FLOPs, or a new model's pretrained capacity a Cell-learning benefit.
3. **Multimodal differentiation**: source-exact text-only, real OCR-to-text,
   frozen native, learned native Head, physical modality lesion and media
   shuffled ablation. Frozen versus learned native must use the **same model
   input SHA** and frozen checkpoint; lesion/shuffle must **change** the actual
   model input, not just the arm label. All arms retain the identical original
   source and question identity, and publish original answer hashes and
   measured cost before labels are opened.

The `legacy421` slot is deliberately **unresolved until the original exact
checkpoint is named and pinned**. Do not invent its weights or replace it with
a nearby model. Parameter sizes in `stem_selection_v7.SLOTS` are approximate
planning counts except the recorded Granite97 97,441,152 parameters; they are
not claims about loaded tensor counts or runtime RSS. EmbeddingGemma2's text,
text+vision and full modular configurations are distinct resident-memory
scenarios, *not* three independently selected Cell Encoders.

## Materials, ownership and boundaries

`build_plan` requires all six named model material records, each with an
immutable 40-character Git revision and actual SHA256 bytes for weights,
tokenizer and preprocessing, plus the same Reader digest and complete
source-first case roster. Question/source SHA, modality list, case and
source-family IDs are fixed before inference; labels, target answers and
publisher supports may not enter the producer plan. No guessed model SHA is
committed in this repository.

A nonempty original multimodal SOURCE roster may include mixed text/image,
text/audio and text/video cases. Modality *presence* is not proof of modality
*necessity*; independent human source-level or causal witness review remains
mandatory for such a claim. Original source-family labels are descriptive until
independently authenticated and transitively de-duplicated. The future-study
target is 200 source-independent groups and two prospectively witnessed windows.

Each arm's original answer is represented by its answer-bytes SHA256 (the
original raw answer journal must be retained securely outside this public
repo). Counts and numeric self-reports are validated but do **not**
cryptographically prove that inference ran. A complete source-only audit returns
`stem_winner_verified=false`, `production_authorized=false`, and
`independent_semantic_review=false` **unconditionally**. A separate independent
reviewer and model-host owner would need to authenticate actual outputs before
any scientific superiority or deployment claim.

The `cache_identity` key includes principal/purpose, generation/authority
fence, exact model and tokenizer/normalizer material, modality and complete
input digest. A change in any dimension invalidates reuse. `group_reuse` is a
logical count, not a measured Transformer forward count, GPU GEMM throughput
or a trusted production feature cache. In particular, per-Cell Encoder prompts
may increase the number of distinct input groups until sharing is ineffective.

## Cost protocol

The `weight_budget` function reports arithmetic *illustrations* only:

```
weights = model_params * resident_copies * dtype_bytes
        + logical_cells * private_head_params * dtype_bytes
        + task_family_bridge_params * dtype_bytes
training_example = active_training_heads * private_head_params * 16
```

The 16 bytes per training parameter are a simplified extra FP32
master/gradient/Adam-m/v example; optimizer implementation and mixed-precision
master-weight duplication must be physically measured. Not included:
activation/KV/cache objects, runtime allocator, graph or index, loaded
Tokenizers, host IPC, mmap page sharing, storage, checkpoint history, replay,
old Encoder-cache generation and recovery. **Weight arithmetic is not RSS,
CPU/GPU computation, p95 latency, energy, or throughput.**

The accompanying `STEM_V7_WEIGHT_BOUNDS_20261015.json` is generated from the
source function and explicitly marked `planning_only`. The real scale test must
run original 64/256/1024/4096 Cell workloads with consistent Scope and
source-independent cohorts, record actual Encoder forward counts, cache hits,
CPU/wall, GPU/VRAM, p50/p95/p99, resident/peak RSS, training optimizer state,
index size, input/output tokens, failed attempts, energy or explicit null,
WAL/revocation/reopen, and overhead of adding one Cell. Batch equal logical
IDs != physical shared Encoder execution.

## Physical experiment handoffs (do not synthesize)

- **Text and binding**: reuse source-only V5/V6 model work/heldout contracts in
  PR #2338; keep #2351 fixed-budget cross-fact/global-pool/local variants
  source-identical but scientifically separate. V6 passed fitting 3/3, yet its
  primary continuation retention failed 1/3 seeds; do not open its previously
  blocked feedback/fresh panels by assertion.
- **Multimodal**: reuse original ScienceQA/DINO/Granite/OCR/Gemma2 producer
  and heldout label-owner arms from #2227 and hardened descendants #2315,
  #2329 and #2336. Check their *current exact SHA* actual hosted
  pretrained/reader/label jobs and published negative/prospective limits
  before incorporating external immutable receipts.
- **Native sharing**: Rust Worker V2 #1498 has immutable Arc binding and gated
  Q24 shadow-head support; genuine pretrained shared Encoder and signed
  production FinalUse plus target-host fleet lifecycle must be proved
  separately. No V7 source-only check authorizes that path.
- **Reader sufficiency and semantics**: independent adjudication and the same
  Reader are required; original historical #2085 shows Head retrieval proxy
  changes need not become answer-quality gains. No V7 task score is manufactured.

## Reproduce the source-only gates

```
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v \
  qualification/stem-cell-v1/test_stem_selection_v7.py
PYTHONPATH=qualification/stem-cell-v1 python3 -O -m unittest -q \
  qualification/stem-cell-v1/test_stem_selection_v7.py
python3 -m py_compile qualification/stem-cell-v1/stem_selection_v7.py
```

All test fixtures use fabricated digests and synthetic answers and must never
be described as real model outputs. A valid external original receipt is still
`original_physical_unverified` until original model-host provenance and
independent semantic/citation review have been authenticated. Do not permit
`main` merge, automatic Cell split/fusion, model selection or FinalUse.
