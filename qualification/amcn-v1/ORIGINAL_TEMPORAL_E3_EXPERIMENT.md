# Hepta AMCN E3: original LoCoMo chronological candidate-graph mechanism

**Research-only / DENY_ALL.** This is a *descriptive historical graph-proxy* experiment, not learned causal edges, trained Encoder, complete strong RAG, independent semantic entailment or qualification for automatically increasing the MemoryCell network. This follows PR #2085, preserves original #1777/#1968 research owners, retains `blocking-ci`, and does not touch `main`, source authority, MemoryCell production writers or FinalUse.

## Real evidence and non-equivalent baselines

Source material is the previously pinned original LoCoMo artifact: exactly **10 conversations, 5,882 original dialogue turns, 1,986 original QA questions**. Original JSON SHA: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. An externally pinned `prepare` phase exports *three different files*: source/questions/label-blind chronological associations, original six-family TRAIN-only publisher weak-support labels (1,157 questions), and independently withheld labels for four other roots (829 questions). Only the first two files enter graph training; only public source/questions and six FP32 coefficients enter inference. Publisher labels open in a separate postseal process. A SHA proves bytes only, not independent source issuer.

**Topology is not a factual graph.** Within each source-original chronological session, a directed `temporal` edge points to the next dialogue turn and a directed `associative` edge points to the previous turn. These are only adjacency roles, not proven truth, implication or causation. Each edge has a deterministic support SHA linking both original source content digests and its source-root ID. Actual BM25 Top-16 lexical seeds discover at most 2 hops, under a 512-node candidate limit. There is no fabricated inter-family link, no hidden publisher-positive topology selection, and no new or retracted source. Every treatment receives exactly **Top-3 actual original dialogue evidence sources** from the same full corpus.

The existing `amcn_learning.train_relation_router` (the original HNMF owner) physically ran actual CPU PyTorch SGD on 3,505 TRAIN-only labelled adjacency examples from all **six original TRAIN roots**: 701 publisher-weak positives and 2,804 TRAIN negatives. It learned **six coefficients** with 96 optimizer steps. Only `temporal` and `associative` occur in this topology; the other original HNMF relation coefficients remain zero. Both learned weights are negative. Independent Python scalar SGD agrees numerically. **A second real PyTorch training invocation independently reproduced all six numeric weights exactly**, although raw receipt SHA differs due to original measured wall-time fields; cross-run acceptance must compare numeric/model/source/optimizer identities, not measured wall-time bytes.

### E3 weak publisher source recovery, two *retrospective* heldout roots (400 questions)

| Route, all at final Top-3 | Any publisher annotation found | All publisher annotations found |
|---|---:|---:|
| Original BM25 **as re-rendered in this experimental protocol** | 174 / 400 | 149 / 400 |
| Fixed signed chronological graph | 177 / 400 | 152 / 400 |
| TRAIN-learned chronological relation coefficients | 171 / 400 | 145 / 400 |
| Learned graph with predeclared single source-edge lesion | 171 / 400 | 145 / 400 |

Do not substitute or equate the older original MiniLM/BM25 182/400 with this 174/400 baseline: the original passage rendering differs. The correct **within-trial** learned-vs-fixed comparison is **−6/400** weak publisher any-support, not a graph benefit. The learned-vs-lesion tie on aggregate also does not prove source-edge relevance. All original questions, negative cases and missing support remain in the denominator. Only two correlated heldout source roots exist, not 400 independent experiments or actual future calendar windows.

### Physical original Reader treatment checks

The source-only plan selected, by a **predeclared SHA case-ID hash and before opening heldout annotations**, 3 questions from each retrospective family for which the learned and lesioned graph actually returned different source choices (9 eligible in `conv-49`, 6 in `conv-50`). These **six are deliberately selection-biased**, useful for diagnostic edge interventions only. Original 30-layer archived BF16 Llama weights `5af571...968ab8c` and original tokenizer bytes `9ca9ac...888e47c` were reloaded. A separate original fixed numeric input `[1,420,35,177]` reproduced the previous independent original logits SHA **exactly**: `0e213cba29020f3140dee7e72d5b8737ebcb2ce0e0189e5662b8415a09f71776`. This is still not official Hugging Face Transformers/Tokenizer parity.

All **24 actual Llama Reader calls** (six cases, BM25/fixed/learned/lesioned, same model and max 16 generated tokens) completed successfully with durable pre-attempt starts, exact generated IDs, raw text, per-arm token counts, and create-only seal. Only after all answers sealed did the scoring phase open original publisher annotations. All four arms recovered weak publisher support in **4/6** cases and all support in **3/6**; all had **0/6 strict literal answer equality**. The graph treatments changed real answer strings (learned versus fixed 3/6, lesioned versus learned 5/6). Total Reader input tokens: BM25 1,139; fixed 1,139; learned 1,122; lesioned 1,139. Total generated tokens: 94/94/96/94. **Five of six cases had naturally matched input tokens across all four arms**; there was no prompt padding/truncation. Input tokens, graph/Head training cost, and total compute are NOT strictly identical. Only 2 independent correlated historical family roots; **independent semantic whole-task success unknown**.

The original Reader's literal-output candidate was a byte-level GPT2/BPE and explicit FP32 Llama forward over genuine BF16 original safetensors; **never claim official HF parity**. When the physical experiment is rerun from an independently authorized checkout on the user-owned dot host, the original repository `amcn_original_text_reader.py` is imported directly (not a substitute Reader). The isolated-host numeric port is not committed as an approved inference implementation. **The GitHub check added by this increment is intentionally SOURCE-ONLY**: it compiles experiment files and checks 15 independent negative-receipt controls without downloading models, credentials, raw dialogue, hidden labels or running new Reader calls. It cannot qualify the 18 original-material tests or attest dot-host model execution.

## Reproduction from exact original archive (no gold exposed to train/rank)

Run in an isolated research directory with the original LoCoMo JSON SHA-verified, local installed Torch/safetensors/regex, repo `PYTHONPATH=.:qualification/amcn-v1`:

```sh
python qualification/amcn-v1/amcn_original_temporal_e3.py prepare \
  --original /original/locomo.json \
  --public /secure/original-public.json \
  --train /secure/original-train-only.json \
  --withheld /secure/original-heldout-withheld.json

python qualification/amcn-v1/amcn_original_temporal_e3.py train \
  --public /secure/original-public.json --public-sha "$PUBLIC_SHA" \
  --train-labels /secure/original-train-only.json --train-sha "$TRAIN_SHA" \
  --output /secure/actual-learned-weights.json --steps 96

python qualification/amcn-v1/amcn_original_temporal_e3.py rank \
  --public /secure/original-public.json --public-sha "$PUBLIC_SHA" \
  --weights /secure/actual-learned-weights.json --weight-sha "$WEIGHTS_FILE_SHA" \
  --output /secure/original-1986-rank-seal.json

# In a separate read-only process AFTER original rank is sealed:
python qualification/amcn-v1/amcn_original_temporal_e3.py score \
  --public /secure/original-public.json --public-sha "$PUBLIC_SHA" \
  --rank /secure/original-1986-rank-seal.json --rank-sha "$RANK_SHA" \
  --heldout /secure/original-heldout-withheld.json --heldout-sha "$HELD_SHA" \
  --output /secure/original-400-publisher-weak-score.json

# Optional real Reader after a frozen rank plan; no publisher answers in process:
python qualification/amcn-v1/amcn_original_temporal_e3_reader.py plan --public /secure/original-public.json --public-sha "$PUBLIC_SHA" --rank /secure/original-1986-rank-seal.json --rank-sha "$RANK_SHA" --reader /original/reader --output /secure/original-6-reader-plan.json
python qualification/amcn-v1/amcn_original_temporal_e3_reader.py generate --plan /secure/original-6-reader-plan.json --plan-sha "$PLAN_SHA" --reader /original/reader --output-dir /secure/original-24-attempts
python qualification/amcn-v1/amcn_original_temporal_e3_reader.py score --plan /secure/original-6-reader-plan.json --plan-sha "$PLAN_SHA" --reader /original/reader --journal /secure/original-24-attempts --corpus /original/locomo.json --corpus-sha 79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4 --heldout /secure/original-heldout-withheld.json --heldout-sha "$HELD_SHA" --output /secure/original-6-reader-negative.json
```

The exact source-only tests include 18 adversarial/identity controls; they exercise actual original files and historical negative receipts. Raw dialogue, publisher gold, original weights, unredacted Reader generated text, and original TRAIN rows **must never be committed or uploaded as Actions artifacts**. The sanitized `ORIGINAL_TEMPORAL_E3_20261015.json` contains only cryptographic pins, physical training metadata and aggregated negative results. **Status: NO-GO / DRAFT / DENY_ALL**, with independent strong-RAG, 200 source family roots, calendar-future tests, source revocation and full-task semantic QA still required.

## Current remote CI scope and authority

The source-only workflow `.github/workflows/hepta-amcn-original-temporal-e3.yml` is strictly a fast, read-only **NO-GO gate** with no artifact-download token, network request, pretrained model dispatch or production permission. It requires all 15 stdlib tests to pass on the exact branch HEAD. All 18 full-source/Torch/Reader tests and 24 genuine original Reader calls were executed in the **isolated local analysis container**; no claim of their rerun by the GitHub runner, dot host or official HF framework is made. A model-host replay must be run separately with independently authenticated source and Reader material when available, under the same future-window and production-owner controls. No fake green status may be borrowed from the quick gate.
