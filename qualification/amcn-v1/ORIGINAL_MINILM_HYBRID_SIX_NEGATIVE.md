# Original LoCoMo six-question physical hybrid retrieval floor — negative result

**Authority: SHADOW / DENY_ALL. Not strong-RAG qualification, model learning, independent evaluator, or production.**

This is an actual, source-first 6-question study run in a local isolated analysis container on 2026-10-15 **not the user's dot host**. It studies a necessary prior question: does a cheap, frozen, shared pretrained MiniLM Encoder improve which source passages the *same* frozen Reader sees, compared with BM25 on the identical corpus? The model and data derive from original SHA-pinned historical GitHub Actions archive `11586991191`; the archive outer SHA-256 is `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`. **No new Head parameters are trained**, so this does not establish effects of learning or Cell types.

## Physical chain and isolation

1. Independent preparation opens the original LoCoMo source `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`, retains **788 source turns** from two original conversation families, and writes **source-only** questions, evidence and dates. Publisher answers and weak-label support do not appear in that output. Recomputed original BM25 Top-3 passages exactly match the original single-arm answer trial (independent original `public_6.json` SHA-256 `60593b01bddd1e7c39acd0f94c269e1d113d6eaedbe83d087527c612cc454e53`).
2. The ranking process receives only that **externally SHA-pinned source-only file**. It validates original MiniLM safetensors `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`, WordPiece vocab and tokenizer hashes. It performs 57 real CPU Torch batches over **38,584 original source/question token positions**, using all six original 384-wide BERT layers in FP32. Its six-token numeric reference CLS digest equals the independently implemented previous `amcn_original_numeric_probe.bert_probe` digest exactly. It ranks the *full source roster* by a preregistered equal 50/50 blend of per-question BM25 maximum-normalized scores and cosine similarities of original-MiniLM mean-pooled vectors, picking exactly 3 original source IDs per question. There is no heldout-label lookup or scoring at this stage.
3. The six hybrid-selected source packets are delivered to the **same** original archived 30-layer 135M Llama Reader (`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`) and the existing original `amcn_original_locomo_trial.generate` original answer owner. Both arms use `top_k=3`, the exact existing prompt, deterministic greedy generation and `max_new_tokens=24`. The Reader process receives no withheld publisher answer path. Completed raw answers are sealed create-only *before* original publisher annotations are opened by a separate scoring step.
4. Post-seal scoring binds both original Reader answer files, same original question IDs/wording/Reader SHA, exact source selections, original unchanged publisher answer file and original source-only retrieval receipt by externally supplied SHA-256 digests. The original and mixed arms **are not input-token exact-matched**: their totals are 1,416 and 1,387 input tokens, respectively. This is matched final *evidence-slot/output-token-ceiling* diagnosis, **not** the fully equal-token-and-compute nine-arm causal study required by the user.

## Honest original observed result

| Original two-family historical six-question diagnostic | Original BM25 Top-3 | Frozen MiniLM + BM25 Top-3 |
| --- | ---: | ---: |
| Original questions | 6 | 6 |
| Publisher-weak support present in final evidence | 3/6 | 3/6 |
| Strict literal equality of generated answer and publisher answer | **0/6** | **0/6** |
| Actual Reader input tokens | 1,416 | 1,387 |
| Reader generated tokens | 106 | 103 |
| Full original source turns admitted | 788 | 788 |

The hybrid changed the selected source IDs **or order** for 4 of 6 questions, without improving source coverage or literal answer matches. Literal equality is *not* independently judged semantic task success. Historical publisher weak support is not independently verified entailment. These 6 queries arise from only two published families; source-family confidence bounds and two real prospective calendar windows are unavailable. Strong hybrid RAG (e.g., a verified production hybrid retriever), trained two-Head Cell specialization, learned graph end-to-end, source-issuer authentication and production acceptance are **not** demonstrated by this test. No promotion or Main merge.

### Exact original local execution identities

- Complete source-only 788-turn receipt: `d0a5e8b3b2d2e96929cdd2b53ff8c2ab886df7412c8e4144a528e7bdeb18d9b3`.
- Original pretrained Encoder hybrid public queries: `9b5fff238f3e66f88420550c73228769f7bf40d1d9770ec918633d75f4b8b594`.
- Original MiniLM 57-batch retrieval receipt: `f2bad6de8cee3577617448392513fa297dd6fc3203172ef76de6bb1ed117de27`.
- Six original hybrid Reader raw-answer bytes: `b2dad25858351b7f9eea822ac16708e4b4822effa94040b2904012f0bbc34544`.
- Original prior BM25 Reader answers: `21ace00e57d8a24d3a68f4543ac01a296a8676c6954e1fcd8a9536388923ad22`.
- Original independent publisher target file: `e22268bc250f5d938a25290cf29ac787456ef2618fac5fa7251ba3425e3871cf`.
- Post-seal paired weak-support/literal-only score: `f3fb0fb9fff5b2d7338a315618e512fc2ad671d63d0a267239fcf17b4c19f47f`.

The source/weight files and raw publisher targets remain **outside the repository**; only code, negative aggregate and reference hashes are committed. All operator numerical/tokenizer implementations here remain **candidates, NOT official Hugging Face parity**; the separate fail-closed official HF parity workflow remains required. The new Torch retrieval workflow is read-only and does not bypass `blocking-ci`.

## Reproduce with separately SHA-pinned original material

```bash
# Step 1: source-only prep. The publisher labels are not part of this output.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_hybrid_floor.py prepare \
  --original-root "$ORIGINAL_ROOT" \
  --original-public "$BASE_PUBLIC" --original-public-sha256 "$BASE_PUBLIC_SHA" \
  --output /private/new/hybrid-source-only.json

# Step 2: fully source-first physical pretrained MiniLM ranking.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_hybrid_floor.py rank \
  --source /private/new/hybrid-source-only.json --source-sha256 "$SOURCE_ONLY_SHA" \
  --encoder "$ORIGINAL_ROOT/encoder" \
  --output-public /private/new/hybrid-public.json \
  --output-receipt /private/new/hybrid-rank-receipt.json

# Step 3: use EXISTING archived Reader owner for each independent arm:
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_locomo_trial.py generate \
  --public /private/new/hybrid-public.json --public-sha256 "$HYBRID_PUBLIC_SHA" \
  --reader "$ORIGINAL_ROOT/reader" --max-new-tokens 24 \
  --output /private/new/hybrid-reader-answers.json

# Step 4: independently pinned, post-seal scoring. The independent scorer
# uses original baseline/answer/gold files not visible to Step 2 or Step 3.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_original_hybrid_floor.py score \
  --original-public "$BASE_PUBLIC" --original-public-sha256 "$BASE_PUBLIC_SHA" \
  --original-answers "$BASE_ANSWERS" --original-answers-sha256 "$BASE_ANSWERS_SHA" \
  --hybrid-public /private/new/hybrid-public.json --hybrid-public-sha256 "$HYBRID_PUBLIC_SHA" \
  --hybrid-answers /private/new/hybrid-reader-answers.json --hybrid-answers-sha256 "$HYBRID_ANSWERS_SHA" \
  --withheld "$ORIGINAL_WITHHELD" --withheld-sha256 "$ORIGINAL_WITHHELD_SHA" \
  --hybrid-retrieval-receipt /private/new/hybrid-rank-receipt.json \
  --hybrid-retrieval-receipt-sha256 "$HYBRID_RANK_RECEIPT_SHA" \
  --output /private/new/paired-postseal-score.json
```
