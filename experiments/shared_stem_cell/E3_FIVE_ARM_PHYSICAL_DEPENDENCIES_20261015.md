# E3 five-arm historical ScienceQA — real model dependencies and phase gates

**RESEARCH ONLY · DRAFT · SHADOW_ONLY · DENY_ALL.** Parent: independent actual ScienceQA archive audit #2192 at exact SHA 42ef8845064c0e2e0dbc66a8d468b41f5f048284. This child never changes original #2173 source, weight, text/DINO runners, Cell owner, Q24 journal, CAS, Worker, FinalUse, CNS, NDU, production selection or main.

## Scope and honest scientific boundary

The goal is one *same-source*, historical, natural-image **five-arm** readout.
It is **not** a three-future-window, image-necessity-adjudicated or target-host
performance experiment. A successful local or hosted mechanism test alone is
not a physical multimodal outcome, and the *five-arm* success condition is
all original source, OCR, native and independent held-out scoring stages green.

The original pinned ScienceQA dataset is
lmms-lab/ScienceQA-IMG@b9984af01798586705cee1fbdfa80a6dcbef04f1.
Original immutable source digest:
a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202.
Original TRAIN+CAL digest:
e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e.
Original held TEST labels digest:
b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3.

Every producer independently restages the identical 96 TRAIN, 32 CAL, 64 TEST
source panel and must match all three originals. The origin of these
historical source/label digests is the physically completed #2173 [Actions
run 38678847948](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38678847948)
artifact 11947722496; a separate #2192 audit reverified this archived source.

## Exact five arms, no model-type alias

1. **text_only** — original real Granite97 frozen text baseline from #2173.
2. **ocr_text** — 192 original source PNG/JPEG byte inputs run through real
   English Tesseract 6-PSM CLI, then a separate actual publisher-pinned
   Granite97 CLS+L2 Encoder. Even empty OCR output counts as a genuinely
   processed source, with a separately reported nonempty census.
3. **unaligned_vision** — original real DINOv2 unaligned-equal-fusion
   negative control from #2173.
4. **aligned_bridge** — original TRAIN-only 147,840-scalar DINO-to-Granite
   Ridge Bridge plus private 769-scalar / 80-step learned Cell gate from
   #2173; the calibrated/no-image/rotated controls remain in the original
   separate evidence.
5. **native_multimodal** — actual google/embeddinggemma-2 at source
   914f7f89142e33e77833254d9c9b90c3cef7303b, frozen text+vision,
   audio tower disabled, 256D normalized text, image, text+image and
   choice vectors. Train an independent complete 769-scalar/80-update
   text-vs-joint gate from original 96 TRAIN labels only.

The pinned original Google model snapshot and runtime verification are
reused from isolated #1775 exact commit
f8d168a7689eb3624d97c44751791badd069e521.
That owner is *checked out by exact SHA*, not merged into current Cell
runtime. No anonymous fallback, arbitrary remote code, unpinned checkpoint,
synthetic pretrained vectors or unsigned model promotion is allowed.

## Independent study architecture

- **Contract job**: standard-Python and -O 28-case negative/positive
  research-only tests. No real model or efficacy proof follows from them.
- **Physical OCR/Granite job**: original source bytes, real Tesseract,
  actual pinned Granite model loads and forward counts. Emits original
  source TEST predictions, never original media or held labels.
- **Physical native Gemma2 job**: separate CPU runtime and verified local
  pinned safe weights, original source-only input and TRAIN labels, actual
  native joint image+text forward API and new private Head training.
  Original held TEST labels are not accepted as CLI arguments.
- **Independent reviewer job**: reopens the immutable original #2173
  64-case prediction byte artifact (SHA256
  e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7),
  takes original+OCR+native source-only reports, requires exact 64×5
  case/arm Cartesian parity, writes prediction seal **before** staging
  the original held labels, then computes Accuracy/Brier, rescued/harmed,
  exact two-sided McNemar and Holm adjustment. All outputs are
  nonauthorizing.

## Original native shared-context admission (research preflight only)

Before **every** EmbeddingGemma2 text, image or mixed-text/image
`SentenceTransformer.encode()` call, the separate stdlib-only
`e3_gemma2_budget.py` validates the model-reported sequence limit and
executes the original loaded tokenizer with `truncation=False` and
`add_special_tokens=True`. It includes the registered default model
prompt, refuses unregistered interleaved `<|image|>` / audio /
video placeholders, and charges **1,120 image soft tokens** for each
local original image. This is the upper end of the documented permitted
image budget and is intentionally conservative. Missing tokenizer,
untrusted prompt, excess tokens, unseen image or unsupported modality
blocks encoding instead of silently truncating.

The complete run must account for **1,344 preflighted individual inputs**
(192 question-only, 192 question+image, 192 image-only, 768 answer options),
and preserve the largest conservative input-token charge. The independent
five-arm composer now refuses a native receipt with any missing/different
preflight census, a changed context or a claim that actual image Token count
was physically verified. Dedicated **20** source-negative unit tests and
**six** additional five-arm denial cases run in both ordinary and optimized
Python; all remain fixture checks until the latest exact-commit Actions
finishes.

This guard is not an instrumentation of the model's internal multimodal
processor. The actual image-token count and internal Transformer forwards
are **not** independently witnessed. Passing a conservative envelope is a
necessary precondition, not authorization or proof of zero truncation
inside an uninspected model implementation. No inference is allowed if
a modified source cannot fit the bounded conservative envelope.

## Matched native-Head text-vs-vision diagnostic (nonpromoting)

The original five-arm comparison changes the Encoder, learning method and
input modality simultaneously, so it cannot by itself attribute gains to
vision. New **within-EmbeddingGemma2** negative/positive controls address
part of that confounding:

- Reuse the **same actual frozen EmbeddingGemma2 checkpoint, tokenizer,
  original 192 source inputs and complete original feature materialization**.
  Construct 768-dimensional *per-candidate* feature inputs of
  \`[query, choice, query*choice]\` for text-only and for text+image.
- Train **two distinct complete 769-parameter Linear Heads** from
  **byte-identical initialization**, using the identical 96 original TRAIN
  labels, AdamW with learning rate 0.01 and **80 updates each**. Every
  underlying pretrained feature is explicitly detached; no Encoder weights
  can receive a gradient. Original CAL and TEST labels never enter fitting.
- Preserve sealed TEST probabilities for **both** 64-case Head predictions
  in a separate sidecar, without passing the outcomes or Head weights to
  the original five-arm Predictor. The original native gate and five-arm
  definitions remain unchanged. Do **not** apply softmax twice: the matched
  module already returns normalized probabilities; the producer only checks
  and stores them.
- The original-label reviewer is a **separate stdlib-only module**, not an
  Encoder or Head import. It matches every Test ID/group/source SHA against
  the sealed five-arm prediction and independently opened original held
  labels, then reports Accuracy/Brier, rescued/harmed and exact McNemar.
  This extra result is post-hoc exploratory, not an additional preregistered
  fifth-arm p-value and **does not authorize a Stem winner**.
- Local CPU-Torch **12/12 actual numeric training and negative tests**
  and **11/11 independent stdlib readout tests** passed in normal and
  Python \`-O\` modes on explicitly **synthetic features and labels**.
  The four pushed Git blobs have been checked against those locally tested
  originals. This is **not** pretrained Head efficacy or latest hosted CI.

Even these same-architecture Heads do not imply **equal inference cost**:
the text+image inputs incur a vision Encoder; the original study does not
supply matched hardware/energy or independently adjudicated visual
necessity. The extra control is a within-model *capacity-matched* contrast,
not a production or equal-total-TCO qualification. Any missing original
matched-Head source, model, case, label, probability or live owner receipt
blocks the extra independent result rather than creating a false advantage.

## Cost and evidence caveats

- Separate physical jobs and CPU environments mean *time/RSS across arms
  is not controlled*. Model loads, text/visual forwards, Tesseract time,
  Head training, process peak RSS and decode count are reported without
  pretending to be a matched isolated total-cost comparison.
- The native SentenceTransformer encode batch-call count is **not**
  an attested internal transformer forward count. It must not be used
  as physical FLOP equivalence with Granite/DINO.
- The original ScienceQA public TEST release is retrospective. The
  experiment does NOT know which cases unambiguously require an image;
  labels are not independently re-adjudicated and changed-image labels
  cannot be invented. Human/source-group three future windows remain
  unobserved.
- Student/teacher, generation, robust OCR language coverage,
  real negative transfer and current deployed E0 no-change are absent.
- Even a physically successful five-arm score never selects a Stem,
  issues NDU authority, installs model weights, or permits Cell Split.
  **No p-value alone is an admission decision.**
- GH Actions steps must be reviewed at their exact source SHA. Queued,
  skipped, missing, incomplete or failed model jobs are NOT a five-arm PASS.

## 2026-10-16 original real OCR evidence and native runtime failure

**Original immutable Actions receipt:**
[run 38825811927](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38825811927)
at source HEAD `bc3280d56fb7dfddf473bb0f0e104c4e0e0d7c80`.
Source-contract job **SUCCESS**; real OCR+Granite job **SUCCESS**; original
Gemma2 native model job **FAILURE** after complete exact-publisher source
and safetensors verification, but **before any scored original native
embedding**; original five-arm independent review **SKIPPED**.

The original OCR physical artifact:
- Artifact ID: 12027769435 (Actions ZIP SHA-256
  `c80d5b9cda23a8a6ee144aeba459dc516b6b67c854c2c5fe86d3b2ba94884964`).
- Original `e3-ocr-observed/sealed-ocr-predictions.json` SHA-256
  `96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885`.
- Source SHA `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`;
  original Granite97 revision `835ad14087e140460703cf0fae09f97d469d65c2`,
  model pipeline digest
  `76c18899adf8587cce3449802e1ac8c0c0760941bffe3518c1ec8df27608c8b0`.
- Original Tesseract over **192 physical natural image records**; **110**
  yielded nonempty OCR text; **60 original frozen Granite97 forward
  batches**, source-bound **64 unique original TEST predictions**.
- Source-self-reported full model acquisition plus OCR wall **57.051462221
  seconds**, summed OCR subprocess wall **22.894919887 seconds**,
  GitHub-runner peak process RSS **1,335,164 KiB** (~1,303.87 MiB).
  These are a single-host descriptive physical pilot, not isolated
  model-only RAM or production-target reproducible latency/energy p99.
- The OCR ZIP does **NOT** carry original held TEST answer labels; these
  numbers are physical execution evidence, **NOT OCR accuracy or a
  statistically selected Stem**.

The first native Gemma2 failure was the fail-closed source Token preflight
`NativeBudgetError: native SentenceTransformer context ceiling absent or
unreviewed`. A second original physical attempt [#38868183394]
(https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38868183394)
**also failed before actual embedding computation**, now at
`NativeBudgetError: unexpected pre-existing native context would silently truncate`.
The exact upstream safetensors and SentenceTransformer loaded successfully;
the checked original `max_seq_length` had a populated but apparently
shorter-than-8,192 default. The failure log does **not expose the precise
default value**, so no specific lower default value is claimed.
The original model's public model card states an 8,192-token shared
multimodal context. A default SentenceTransformer inference length need
not be equal to that maximum. The repaired
`bind_verified_native_context` must run only **after** verifying the
exact original model snapshot, owner profile and tokenization components,
and must explicitly set the supported SentenceTransformer runtime setter
to 8,192, then re-read both its public property and first Transformer
module's property. It never modifies weights, grants authority, permits
truncation or attests actual internal image token counts. Missing/short/
unsupported runtime context remains **blocked**.

**New independent OCR readout**:
`e3_ocr_original_audit.py` and its adversarial tests consume only
immutable original Granite/DINO source (SHA256
`e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7`)
and already completed real OCR predictions (SHA256
`96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885`).
A **separate Actions job** must seal/reopen both original predictions,
only then re-stage the original historical 64 TEST labels in a separate
reviewer, and compute original text vs OCR Accuracy/Brier, paired rescued/
harmed counts and exact McNemar. It is independent of the native model
job, publishes only numeric nonauthorizing evidence, does not
independently adjudicate visual necessity, and is never promoted to a
five-arm or prospective-NDU result before that actual review job succeeds.

**Updated result rule:** original real OCR **PASS**, original native
Gemma2 physical forward **NOT YET PASS**, five-arm independent TEST
**NOT YET PASS**, newest context fixes and 17 extra OCR-readout negative
unit methods **await their exact-SHA CI results**. No source-only or
CPU-standalone test may substitute for missing original model outcome.

### Second runtime context admission repair

After exact pinned source/owner/weights verification, permit an actual
SentenceTransformer default of `None` or an **integral 128–262,144**
as *original state only*; a shorter default (such as 512 or 1,024)
is no longer itself mistaken for absence of the model's documented 8K
capability. **Nothing is inferred from that default**: immediately
set the SentenceTransformer public property to 8,192 and check its
first Transformer module property has also changed to exactly 8,192
BEFORE any model `encode`. Unregistered source/profile, non-integers,
bool, unreasonably small defaults, longer than registered bound, missing
setter or mismatched readback always fail closed. All actual input
sequences are still independently tokenized without truncation, with
the conservative 1,120-per-image budget. The exact-head CI and actual
original-model forward are required; these new negative fixtures are
not yet a real model pass.

## Next gates

After the original five-arm same-source held score and independent
statistical review, require: visually necessary task adjudication
separated from the predictors; source-family-independent genuinely
prospective data; capacity-matched frozen/learned no-change and retention
controls; matched complete end-to-end resource/accounting against one
shared Laya421 and EmbeddingGemma2; native Worker and signed
FinalUse/WAL/CAS/recovery. Until then all outcomes DENY_ALL.
