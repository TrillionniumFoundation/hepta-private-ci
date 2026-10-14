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

## 2026-10-14 exact-source public-labelled capability panel

The additive `public_agnews_panel.py` checks two preregistered public Apache
2.0 AG News parquet SHA256 values at fixed dataset revision. It selects a
deterministic, source-deduplicated 128-train / 32-calibration / 64-test binary
world/sports panel. Every arm can consume the same canonical question/options/
state and source digest, without synthetic answer labels.

The read-only `hepta-stem-public-panel.yml` retrieves and rehashes actual
public dataset bytes and retains only a bounded sample/receipt. This is
**cross-sectional capability data**: it is NOT a future time window,
production outcome receipt, model-execution claim, or Laya/Gemma proof.
Real matched model inference and independent future learning evaluation
remain mandatory. No selected artifact, FinalUse, main merge or release.

## 2026-10-14: pinned same-task physical Laya/Gemma capability execution

A new isolated, **read-only** physical model comparator binds all candidate
answers to the existing frozen AG News world/sports **cross-sectional** panel.

- `agnews_paired_shadow.py` evaluates three distinct arms: **frozen
  Laya421**, **Gemma2 256d + identical-initialization frozen DynamicCell Head**,
  and **Gemma2 256d + actual SGD-trained 2K Head**. The same 128 balanced train,
  32 calibration and 64 held-out test inputs are source-hash-bound. Laya uses
  its documented typed-choice prompt realization; Gemma uses the canonical
  full joint question/options/state with its registered Classification prompt.
  This distinction must remain explicit and is **not** a claim of identical
  tokenizer input bytes or equal model capacity.
- The new `hepta-stem-paired-capability.yml` Pins both public model revisions,
  both dataset asset SHA256s, checked runtime packages and complete local
  checkpoint file inventories, and executes the Gemma encoder/Head and
  Laya physical model in separate Python processes on one CPU runner.
  It uploads **no pretrained weights**. A dependency, source, model or
  individual-case receipt failure aborts the experiment without fabricated data.
- The independent case-level checker rejects wrong cohort counts, wrong
  source/label/option identity, repeated case IDs, missing arm predictions,
  modified task digests, nonfinite probabilities, nonpositive observed wall
  time and any invented independent/outcome authority. It reports accuracy,
  Brier, descriptive 8-bin uncalibrated ECE and observed inference timings.
- Crucially **no** source publication, prior checkpoint reproduction,
  train/test split or public benchmark run creates a future1/future2/future3
  outcome. No paired statistical-screen pass, causal learning, calibrated OOD,
  matched full training+serving+migration+pretraining cost, physical kernel
  forward count or FinalUse is certified here.

This is a diagnostic between model families, not a decision to replace Laya.
The original physical smoke workflows and existing native owners remain
unchanged; PR remains **Draft / Shadow / DENY_ALL** until full independent
acceptance and `blocking-ci` are demonstrably complete.


## Independently recomputed public three-arm numerical audit

The optional `paired_independent_audit.py` is a **separate read-only
consumer**, not the encoder, Head trainer or Laya interpreter. It ingests
the original SHA-256-bound AG News panel and source receipt plus all three
raw per-case model arm reports and the combined report. It independently
recomputes every calibration/test accuracy, Brier, eight-bin descriptive
ECE and measured serving-time sum, rather than trusting the model
runner's summary. It rejects recycled/missing cases, changed input
hashes/labels, unexpected model revisions, frozen/learned Head lineage
mismatch, and any claim of independent origin/equal total cost/true future
windows or production authority without separate owner evidence.

The three arms are Laya421 Frozen, Gemma2 Frozen Head and Gemma2
Trained Head. This verifier retains the exact source/output/report SHA256
identities, explicitly distinguishes allocated shared-batch wall time
from an independently measured per-request latency, and reports test-only
descriptive pairwise deltas. It does **not** authenticate the upstream
dataset signer, native Worker, physical Transformer forward counts,
Foundation pretraining cost, causal effect or three future windows.
It never grants production promotion; its only disposition is `DENY_ALL`.

The paired physical workflow now runs this independently implemented
post-hoc review and retains its result as a distinct artifact next to
the original raw model reports. This is an integrity gate, not an
independent future-time learning claim.


## 2026-10-14: first real public three-arm result and exploratory calibration

The [real paired public run #38521871187](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38521871187)
completed on **source commit `1f231584124e62a11cf932d937ea4a7ad2437ab2`**
with the exact SHA-256-bound panel
`2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`.
The distinct read-only numeric verifier recomputed 96 calibration/test
source-and-prediction records and verified the following descriptive **64-row
cross-sectional test** scores:

| Arm | Accuracy | Brier | 8-bin ECE |
| --- | ---: | ---: | ---: |
| Laya421 frozen | 1.000000 | 0.00569167 | 0.027680 |
| EmbeddingGemma2 frozen 2018-param Head | 0.406250 | 0.25001414 | 0.093812 |
| EmbeddingGemma2 trained 2018-param Head (40 SGD steps) | 0.937500 | 0.24867517 | 0.436124 |

Training changed the Cell decision boundary substantially, but the trained
probabilities remained clustered near 0.5 and badly calibrated. **This public
panel does not establish a production improvement over frozen Laya.**
It is cross-sectional, may overlap upstream pretraining and lacks matched
Foundation pretraining, target-host end-to-end, owner-authenticated outcome
and three later future-window evidence. CPU batch-wall allocation is
not independently observed per-Cell latency.

A follow-up pure-probability `exploratory_temperature_probe.py` analyses
only these immutable three raw reports. It tries a fixed, bounded set of logit
multipliers, chooses the scale using the 32-row **calibration** Brier and
descriptively reports the 64-row test result without changing any model
or selected artifact. In the already-reviewed public panel, factor 1024
moved trained-Head test Brier from `0.248675` to approximately `0.045749`,
and descriptive ECE from `0.436124` to approximately `0.027045`; category
accuracy remained 93.75%. **Researchers had already inspected the test
result before adding this experiment, so it is post-hoc exploratory and
not a confirmatory held-out win.** A new preregistered untouched dataset
and real longitudinal episodes remain necessary.

### Real multimodal runtime failure and targeted fix

[Gemma physical run #38521871198](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38521871198)
failed while decoding audio because the Ubuntu runner did not have the
FFmpeg shared `libavutil.so.58` runtime required by the pinned
`torchcodec==0.10.0`/`torch==2.10.0` CPU path. This was a real
decoder-environment failure; it is **not** a measured model accuracy
failure. The dedicated media job now installs the distribution's FFmpeg6
runtime before downloading the large model, validates the TorchCodec
decoder import, and persists separate vision/audio receipts so a later
audio error cannot discard the completed vision numeric evidence.
The fix itself needs a fresh exact-head CI result before it can be
called successful.

## 2026-10-14: nonoverlapping val2 source replication protocol

**Shadow-only preregistered continuation; no outcome claims.** The public
128-train/32-calibration/64-test AG News three-arm study has already been
inspected. Its exact source panel SHA-256 is
`2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`.
This independent *new-file* replication uses a different, reviewed upstream
asset: `szhuggingface/ag_news` at source revision prefix `98c5322`,
`data/val2-00000-of-00001.parquet`, whose exact source file SHA-256 is
`51ea52a70f2751cbd13183773186dfc833099c7a17f2664535688baa85aa68f9`.

`public_agnews_confirmatory.py` freezes its deterministic label-stratified
source-hash selection before model loading: exactly 64 new world and 64 new
sports rows. All original 224 source digests are excluded. The bounded
selector uses an explicit domain SHA-256 and never uses model predictions,
scores, or cost estimates. No model checkpoint or Head tensor is updated
from these new labels.

The existing physical three-arm runner receives the original and new panels
in the *same* model-loading process. It keeps the baseline output and extends
only the read-only study with a fourth *report arm*:
Laya421 frozen, Gemma2 frozen Cell Head, Gemma2 trained Cell Head and the
same trained Head transformed with the **previously chosen fixed multiplier
1024**. The scaling is a monotone postprocessing operation, not a new model
or 1024 independently trainable parameters. No new source outcomes are used
for the 40 initial Head training steps or to refit the multiplier.

`paired_confirmatory_audit.py` is a separately invoked read-only verifier:
it rehashes the **entire original val2 parquet** and reconstructs source
labels and deterministic selection, checks case and model/Head lineage,
recomputes all 128 predictions per arm, and independently reports accuracy,
Brier, eight-bin descriptive ECE and nominal paired bootstrap Brier
differences. It rejects missing/duplicated/mismatched cases, modified
weights, scale drift, independent-authentication overclaims and unsupported
authority. The paired workflow binds this audit to the exact tested Git
head, saves the original/replication inputs and reports separately, and
keeps all outputs `DENY_ALL`.

**Limits:** Although val2 is a different pinned source file and selected
cases are disjoint from the earlier local study, it belongs to the same
public AG News dataset family. This is *not* an independently observed
chronological future episode, a proof of absence from foundation
pretraining, or a preregistered task family fixed before the previous
test results were examined. The 95% paired bootstrap is descriptive and
not corrected for all research searches. Exact model-origin signing,
real physical-forward attribution, target-host lifecycle cost, independent
outcome authority, future1/future2/future3 and `blocking-ci` remain open.
