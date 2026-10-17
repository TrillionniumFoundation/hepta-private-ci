# HDSI G6 — coverage-first original LoCoMo reranking (research / DENY_ALL)

**Status:** DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE · NO STEM PROMOTION · NO NDU SYSTEM2 LIFT · NO AUTOMATIC CELL SPLIT · NO FINALUSE.

## Scope and design

This additive research follow-up is stacked on G5 [PR #2627](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2627) and therefore also on the G0–G3 [PR #2617](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2617). No original Rust `hepta-neuron`/`hepta-ndu`, selected Stem, Model Worker, CAS/CNS, FinalUse, authority, learning-ledger writer or protected `main` paths are changed. No new NDU subject class or solver is introduced.

G5 showed that fixed SHA-selected 256 documents/root cover at least one human evidence address for only 31 of 96 historical held questions; rank-8 learning on that incomplete view fell from frozen cosine 12/96 Hit@5 to 2/96. G6 directly isolates the **retrieval ceiling** from the **scoring/learning** decision:

1. Keep the *identical* original SHA-verified LoCoMo source, same **six TRAIN / four HELD original dialogue roots** and exactly the same 24 source-first questions per root, no future-window or cross-publisher claims.
2. Preserve the G5 original *TRAIN 256 documents/root*, 384D BF16-pretrained six-layer MiniLM reference converted to float32 CPU, seed 7347, rank-eight **6,144 trainable scalar Head**, exactly 100 AdamW steps and a matched wrong-supervision Head. Neither Head sees HELD answers or evidence labels.
3. For every HELD root, scan **all original conversation utterances**, using registered deterministic BM25 (k1=1.2,b=.75) and source-ID lexicographic tie breaking. Total **2,447 unique HELD source dialogue entries** (689/681/509/568), not a manually chosen answer-positive subset.
4. For each of 96 questions, restrict neural reordering to exactly the **original BM25 top 64**. Encode only the per-root union of these candidates (with independently scoped shared feature cache). The other documents *must* retain their original BM25 order and cannot enter the first 64 positions by a neural route.
5. Freeze six output arms *before* opening HELD gold: `bm25_full`, `bm25_64`, `cosine_64`, `rank8_64`, `sham_64`, and **untrained reciprocal-rank fusion** `rrf_64` using the fixed 20-rank denominator. The fusion uses BM25 and frozen cosine, not a post-test fitted threshold.
6. Independently rebuild original SHA-pinned publisher questions and complete transcript; recompute every BM25 ranking from original words, bind all full permutations/candidate sets to the pre-label prediction seal, validate training budget and original model sequence/batch accounting, then open publisher gold and score evidence retrieval. **No natural-language answer correctness is measured.**

Research security: the **model worker may only receive the four checked Encoder files and the source packet** containing TRAIN support but **no HELD evidence labels**. `g6_material_custody.py` extracts only allowlisted original ZIP entries and removes the original full `locomo.json` before handoff; the separate postseal reviewer reacquires the original public publisher bytes on a different Actions job. No original checkpoint weights, dialogue, questions or per-case prediction lists are committed here; only source/tests and aggregate sanitized local JSON are retained. All outputs are create-only and fail on digest drift, duplicate JSON keys, source substitutions, incomplete rankings and unknown resource fields.

## Actually executed local original-source physical run

- Original archive: GitHub historical artifact `11586991191`, full outer SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`. Original LoCoMo SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`; original six-layer MiniLM weight SHA256 `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`. Four preprocessor/model files checked before loading tensors.
- Actual frozen **3,623** complete six-layer pretrained MiniLM sequence forwards, **232** physical 16-input batches, **112,055** input token positions, and **3,624** scoped logical feature borrows. The model was not repeatedly loaded for each logical Cell. G6 both Heads actually complete 100 learning steps at matching 6,144 scalars each, trained exclusively on **55/144** TRAIN questions with an available reference in their frozen training documents.
- An initial physical prelabel run was **correctly rejected by the independent reviewer**: unordered set iteration in BM25 produced cross-process near-tie ordering differences. It was not scored as a positive outcome. Both producer and independent reviewer were repaired to iterate sorted unique query terms. A separate cross-process `PYTHONHASHSEED=1` vs `=2` original model-free lexical ranking had an identical SHA256; then **all 3,623 original full-model forward sequences were performed again**, predictions freshly SHA-sealed and independently scored successfully. The negative rejected prelabel is retained only in the local authoring environment, not promoted or passed to the current-review evidence.
- New accepted original model/feature run: **57.39 seconds CPU / 57.39 seconds wall** (research-host self-report, not signed target-host measurements), maximum RSS **about 529 MB**, no GPU/energy/p95/p99 target data. Also paid **58,728 full-corpus BM25 question/document scores** and training/evaluation cost. This is a different resource scope than G5, and CPU/wall are overlapping totals rather than additive step timers.

### Original human **evidence** outcomes (96 HELD questions, 4 correlated conversation roots)

| Frozen experimental arm | Original Hit@5 | Original Hit@10 | Complete evidence set within top 5 |
| --- | ---: | ---: | ---: |
| BM25 full (identical to BM25-64 before rerank) | **48 / 96** | 56 / 96 | 36 / 96 |
| BM25 Top-64 + frozen cosine | 40 / 96 | 56 / 96 | 28 / 96 |
| BM25 Top-64 + trained rank-8 Head | **23 / 96** | 35 / 96 | 16 / 96 |
| BM25 Top-64 + wrong-supervision rank-8 Head | 7 / 96 | 19 / 96 | 6 / 96 |
| **Predeclared RRF fusion BM25 + frozen cosine** | **53 / 96** | **63 / 96** | **40 / 96** |

The independent full-document support ceiling is **96/96**; BM25 *top 32* covers **69/96**, and *top 64* covers **74/96**. RRF versus BM25: **11 rescues, 6 harms, 79 ties**. Learned Rank-8 versus BM25: **6 rescues, 31 harms, 59 ties**. Only four correlated historical held source roots exist; the 5-question RRF lift is **descriptive**, is not a statistical confidence-bound win, and does not justify selecting a new stem or training policy. Strong BM25 alone spends zero neural forward calls; **RRF has strictly additional inference cost**, so net NDU resource utility remains unverified. This is not multimodal generation or a learned System 2 reasoning result.

The source-bound original scorer and aggregate result are in `G6_LOCAL_ORIGINAL_SCOPED_REVIEW_20261017.json`; local original input/prediction bytes were not committed. Source/adversarial suite: **16 normal + 16 Python -O PASS with real original material**, including genuine independent full 96-question human evidence recount; in source-only `python -S` and `python -O -S`, **15/16 PASS, 1 deliberately SKIPPED** requiring original publisher/model evidence. Original G5 source-only Torch-ingress CI issue is fixed separately in PR #2627, not papered over here.

## Release and next-science gate

This confirms that **coverage-first retrieval**, not additional Cell fission or a new NDU FBSDE layer, is currently the larger source of attainable task improvement. It does **not** establish genuine future-time learning, cross-family transfer, source-independent human semantic answer correctness, causally improved System 2 policy, total production cost saving, sustained retention or 4,096 learned-cell utility. Any later NDU continuation controller must compare `stop / BM25-only / paid frozen rerank` under the **same frozen objective, actual marginal call cost, exact candidate support and ordinary Bellman baseline**; no policy may train against or inspect these historical held labels and then call them prospective.

The read-only `hepta-hdsi-g6-original.yml` replays independent source contracts, historical archive SHA, genuine full model, SHA-sealed predictions and independently reacquired original human label scoring on separate jobs. Until **this exact commit** succeeds, local original success is not an Actions result. Even a complete successful research-only workflow cannot bypass global `blocking-ci`, architecture, operator and FinalUse admission. All result readers return `HOLD_NO_GO` unconditionally.
