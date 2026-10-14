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
  model invocation is not an independently signed model receipt. A test-injected
  stub is labelled `deterministic_stub_contract_only` and will be rejected by
  the paired media evaluator. Encoded-call counts are scoped to each request.
  A pinned model tokenizer is used for a nontruncating 8,192-token check
  (including task prompt) for text; **multimodal model-internal token budgets
  are not yet independently verified** and must not support capacity claims.
- Potentially executable, pickle or legacy Torch serialized model files are
  rejected even when declared in the complete SHA256 inventory. External source
  origin remains unverified until independent provenance attestation.

## Stage 3 — optional vision, audio, video qualification

- `embeddinggemma2_shadow.py` verifies local image/audio/video bytes, sizes,
  extensions and media SHA256; network URLs and symlinked paths are forbidden.
  It uses official `SentenceTransformer.encode` modality dictionaries and
  supports only four whitelisted selective-load profiles.
- `embeddinggemma2_pairs.py` runs true encoded text/media pair retrieval on
  independent test/future groups with chronological ordering and anti-leakage
  checks. Duplicate positive media or text bytes *within* one ranking cohort
  are rejected, as well as asset reuse across windows. At least two independent
  case groups per ranking cohort are required. It generates **two real text
  embeddings per case** with distinct `SearchQuery` and `Document` prompts
  (one per search direction), so the reciprocal search task is not silently
  scored with a query-prompt vector as a corpus-document vector; both API
  invocations and cost must be counted.
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

## Stage 4 — frozen real Cell Head pilot

`embeddinggemma2_cell_study.py` is an executable integration with the **existing**
`cell_learning.DynamicCell` trainer in the same research stack. Its exact
`hepta.gemma2.binary-cell-study.v1` input requires external labels, true frozen
production no-change probabilities, original grouped source identities and a
canonical full question/options/state for every example. Six disjoint ordered
windows are mandatory: train, calibration, test, future1, future2 and future3,
with at least eight cases and two source groups in each. This runner trains an
actual 2K/8K/16K dynamic Cell Head on already pinned 256d Q24 features,
compares identical-initialization frozen and trained Heads against the external
no-change distribution, retains both loss and calibration metrics for all five
post-training windows and never uses future labels for any optimizer step.

```bash
python3 qualification/neuron-dynamic-learning/embeddinggemma2_cell_study.py \
  --manifest /approved/stem/manifest.json \
  --cases /approved/evaluation/frozen_binary_cases.json \
  --head-budget 2048 --steps 40
```

**This is an experimental integration, NOT a claim of a completed study:**
no actual EmbeddingGemma 2 weights, external outcome labels, signed independent
no-change predictions, independent evaluator attestations, train/test/future
datasets, or end-to-end GPU measurements are provided. Even a favorable
observational result is `DENY_ALL`; independent owners must verify evidence,
provenance, selection, artifact availability and revocation before promotion.


## Next execution slice: real public weights and paired audit (2026-10-14)

**All additions are research-only and DENY_ALL.** Existing Laya, selected
artifacts, production inference, FinalUse and `main` remain unchanged.

### Real-weight preparation and shadow execution

`prepare_gemma2_snapshot.py` optionally downloads from Hugging Face after
checking an **exact 40-character upstream revision**, model-card Apache-2.0
license, safe file extensions, per-file source LFS SHA-256 where available,
complete local file digests, pinned inference package versions, and a bounded
4 GiB total downloaded size. It publishes a local manifest atomically, but
does not independently authenticate the upstream signer. Unsafe executable
files, pickle weights, symlinks and floating revisions are rejected.

`.github/workflows/hepta-gemma2-physical-shadow.yml` adds a narrowly scoped
pull-request study running the public `google/embeddinggemma-2` revision
`914f7f89142e33e77833254d9c9b90c3cef7303b` as CPU/fp32 text-only
256d. It compares duplicate inputs and records API calls, environment,
source bytes and wall time; it does not assign fabricated physical forward
counts, model accuracy, longitudinal utility, or production authority.
The approximately 1.5 GB checkpoint is never checked into the repository.
Until this job actually completes, real EmbeddingGemma 2 execution is missing.

### Multimodal input preflight

`embeddinggemma2_shadow.py` now rejects malformed images, overlarge pixel
surfaces, non-16kHz/mono or excessive-duration audio, and videos whose default
1fps/140-token-per-frame sampled budget is too large. The preflight bounds
follow Google's default 8,192-token model context, 280 tokens per image and
25 audio tokens per second. Decoder resource preflight is **not** an independent
receipt for actual processor token usage or configurable video sampling.

### Same-task, matched-lifecycle Laya/Stem evidence

`equal_budget_audit.py` requires a preregistered panel of identical cases
for every declared model arm, with `test/future1/future2/future3` separated
by source, group and observation time. It rejects missing predictions, duplicate
arms, cross-window leakage, unbounded probabilities and missing measured
cost. Its paired report includes per-window Brier and latency, a conservative
cluster-bootstrap future gain bound and total measured cost across serving,
training, evaluation, migration, storage and source re-reads.

A statistically favorable **screen** requires positive LCB, positive benefit
in each of three future windows, and no higher matched lifecycle cost.
It never self-authenticates model, source, outcomes or receipts. All results
retain `production_promotion=DENY_ALL`.

```bash
python3 -m unittest discover -v -s qualification/neuron-dynamic-learning -p 'test_*.py'
python3 qualification/neuron-dynamic-learning/prepare_gemma2_snapshot.py \
  --revision 914f7f89142e33e77833254d9c9b90c3cef7303b \
  --destination /approved/outside-repo/gemma2 --profile text --dimension 256
python3 qualification/neuron-dynamic-learning/equal_budget_audit.py \
  --panel /approved/outside-repo/observed_pairwise_panel.json
```

The default tests never download public weights or invent future data.
Remaining hard blockers: completed physical inference, actual Laya 421M/322M
equal-budget controls, multimodal pairs, independent evaluation, real future
episodes, calibrated OOD, signed Worker receipts, artifact CAS/revocation,
WAL/crash recovery, exact candidate CI and owner promotion approval.

## 2026-10-14 follow-up: adversarial evidence review

Paired Laya/Stem evidence now rejects recycled owner outcomes, reused model
prediction receipts, and model/policy identities disguised as distinct arms.
All four windows require at least eight independent source groups, and
multiple comparisons use a Bonferroni-corrected one-sided cluster bootstrap
lower bound before a cost screen can pass. Original per-arm 95% bounds remain
descriptive only. These inputs are still externally supplied and **unsigned**:
positive screens cannot authenticate real model outcomes or enable FinalUse.

## 2026-10-14 empirical pairing repair (incremental)

The equal-budget screen now counts all model predictions including `test`
(and future1/future2/future3), not just the future test windows. The report
explicitly excludes inherited foundation-model pretraining and marks opaque
cost units and shared overhead as not independently authenticated. A favorable
study-observed cost ratio is **not** a model lifetime-cost conclusion.

`embeddinggemma2_cell_study.py` now uses source/Cell/case-bound IDs rather
than a reused per-microbatch ordinal. It checks that every real-weight feature
row, source digest, Cell identity, purpose, generation, epoch, Q24 content
digest and pipeline matches its corresponding labelled case before training.
Reordered or mixed Worker rows hard-fail. These local binding checks are not
independent source or inference authorization.
