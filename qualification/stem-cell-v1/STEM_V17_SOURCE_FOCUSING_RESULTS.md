# V17 — original frozen Reader, source focusing, private blinded review handoff

**DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. Not production, no main merge, no model or Cell promotion.**

## Exact scientific question

Does a cheap **question-only, label-blind sentence selection** improve the existing small Reader's ability to exploit an originally delivered publisher-annotated witness passage? Compare two new prompt representations with the **same three physical source IDs**, the same historical 32 V16 questions, the exact same original 135M Reader/tokenizer, original output cap (24 tokens), and no new learned Cell parameters.

This is not a new prospective held-out experiment. V16 selected **four literal-answer-bearing** and **four nonliteral-answer-bearing** cases from each of four retrospective LoCoMo conversation families **using original publisher answer and evidence annotations**. V17 does not read those answer labels during source focusing or model inference; however, the inherited cohort remains answer-conditioned and previously exposed. Do not count seeds/rows as new independent families.

## Physical execution actually completed

- Preserved V16 original sealed SHA lineage and source-only family/Rank Top-32 inventory. Reconstructed **32 exact original questions** and **64 new original Reader requests**, with two arms `formatted_full` (all source content) and `formatted_focused` (one verbatim source sentence chosen using question word overlap). Both retain the witness followed by the same two BM25 sources; original evidence IDs are unchanged.
- The source text is actually shortened in **29/32** questions. Both arms use the same instruction template, **but their section headings differ**; this is therefore a *presentation-plus-focusing* comparison, not a perfect isolated deletion-only causal experiment. The question-only focus algorithm reads **no publisher gold**.
- Exact archived original Reader safetensors SHA `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`; original ByteLevel tokenizer SHA `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`. Physical CPU PyTorch FP32 manual Llama implementation, **not official Hugging Face operator/tokenizer parity**. Original pretrained model input digests, fsynced attempt starts and complete output journals remain private.
- First new process: **64/64 completed**, **1,502 physical forward calls**, **10,755 input + 1,449 generated tokens**, CPU **242.2493 seconds**, wall **125.9730 seconds**. Its full formatted arm used **5,679 input / 754 output** tokens; focused arm **5,076 input / 695 output** tokens. Arm-level first-process observed Reader CPU totals: approximately **126.670 s** full and **115.439 s** focused, not optimized deployment throughput or matched total lifecycle cost.
- Independently loaded the **same original weights/tokenizer again** in a separate second CPU process; **64/64 exact answer, source and original token-ID replays**, again **1,502 forward calls**, CPU **248.3628 seconds**, wall **129.4567 seconds**. Full serialized journal files differ due to measured timings; complete model-output/token identity digest matches. Separate source+token+forward audits independently recounted both.

## Strict postseal publisher *weak string* proxy (not semantic correctness)

| Historical, answer-containing witness cohort (16 original questions) | Publisher answer appears as output substring | Full literal equality |
| --- | ---: | ---: |
| Historical original V16 witness prompt | 8/16 | 0/16 |
| New V17 complete witness, reformatted | **9/16** | 0/16 |
| New V17 question-selected witness sentence, reformatted | **3/16** | 0/16 |

On the other 16 historical selected questions whose publisher answer did **not** appear inside the annotated source, all three delivered-witness arms scored **0/16** on this weak string proxy. **Five of those 16 have no usable publisher `answer` string field**: separately accounted as `publisher_answer_unknown=5` in every arm, not silently reclassified as verified wrong answers. All 32 original cases remain in the denominator.

**Paired source-group diagnostic:** among the 16 answer-literal cohort questions, focused-vs-reformatted-full gained **0** and lost **6** original-question string hits. Reformatted-full vs V16 gained **2** and lost **1**. These are *retrospective* paired observations in four original conversation roots, not independently adjudicated task successes or statistically established generalization.

The full/focused source IDs are the same and answer text may change for multiple reasons: the displayed evidence has fewer tokens, section labels differ, and model input/output token costs differ. Result does not identify a causal learned-Head, NDU, stem or globally superior evidence policy.

## Private blinded original-source review handoff

A separate pre-result-independent reviewer intake contains **96 private tickets**: the 32 original questions crossed with the V16 original witness response and both V17 responses. Tickets contain the original question, *exact delivered* source text for each variant and original generated answer. A secret private seed conceals case and arm identities in ticket IDs; mapping stored **separately** and withheld from evaluators. The review prompts ask for (1) actual evidence sufficiency, (2) semantic correctness, (3) citation entailment. The source text can itself contain publisher answer wording, but the **publisher answer label field is not included**. No independent person has signed, judged or returned any ticket. Ticket generation is not an independent semantic score and cannot grant production authority. Tickets/source strings/secret seed are never in the Git tree or uploaded CI artifacts.

## Strict blockers

- Original pretrained **candidate-only** Reader; **zero physically executed stronger reference Reader**.
- **Zero independent human judgments**, zero authenticated publisher evidence sufficiency/necessity and no semantic citation entailment.
- Four historical, correlated LoCoMo conversation families, **zero prospective calendar windows**, original cohort chosen using answer labels before this intervention.
- Original Hugging Face parity unqualified, no matched full lifecycle cost, Reader/Cell causal utility unverified, original V6 seed41 retention failure still open.
- No source owner model signer, no automatic split/fusion, NDU/System2, model selector/FinalUse, or production effects.

Only public source scripts, exact original material SHAs, the source-only CI, a sanitized immutable count receipt and adversarial tests are committed. Private original conversations/answers/model weights, route rows and 96 reviewer tickets do not enter public Git or Actions.

## Reproduction

Run source-only tests without original material:

```bash
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v17_*.py' -v
PYTHONPATH=qualification/stem-cell-v1 python3 -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_v17_*.py' -v
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/v17_public_no_go.py --receipt qualification/stem-cell-v1/STEM_V17_ORIGINAL_READER_FOCUS_NEGATIVE_20261016.json
```

Private optional original model run requires **the user's original external verified model and source archive**, exact V16 source/rank/plan and create-only new output location:

```bash
python qualification/stem-cell-v1/v17_source_focusing.py prepare \
  --source PRIVATE/source-only.json --ranks PRIVATE/original-bm25-private-routes.json \
  --v16-plan PRIVATE/v16-plan.json --out PRIVATE/V17-FRESH-plan.json
python qualification/stem-cell-v1/v17_source_focusing.py run \
  --source PRIVATE/source-only.json --ranks PRIVATE/original-bm25-private-routes.json \
  --v16-plan PRIVATE/v16-plan.json --plan PRIVATE/V17-FRESH-plan.json \
  --reader-dir PRIVATE/original-reader --out PRIVATE/V17-FRESH-original-answers.json
```

The physical run MUST refuse missing/mismatched original safetensors/tokenizer, mutated source prompts, duplicate results or an already-sealed output. Do not treat source-only CI as proof of a newly rerun pretrained model or human review.
