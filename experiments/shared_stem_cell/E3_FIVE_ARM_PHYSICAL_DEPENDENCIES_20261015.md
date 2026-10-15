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

## Next gates

After the original five-arm same-source held score and independent
statistical review, require: visually necessary task adjudication
separated from the predictors; source-family-independent genuinely
prospective data; capacity-matched frozen/learned no-change and retention
controls; matched complete end-to-end resource/accounting against one
shared Laya421 and EmbeddingGemma2; native Worker and signed
FinalUse/WAL/CAS/recovery. Until then all outcomes DENY_ALL.
