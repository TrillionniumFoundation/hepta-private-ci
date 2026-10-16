# V19 — original Reader question-only context-window recovery

**2026-10-16 · ORIGINAL PHYSICAL SHADOW · HOLD_NO_GO · DENY_ALL.**

## Experimental question and strict ancestry

V18 found that a question-overlap-selected single sentence can both remove the original publisher answer string from the delivered evidence and reduce the original frozen Reader's literal answer extraction. V19 asks whether retaining a *contiguous source context window*, without publisher answers used at inference, recovers answer-containing evidence and original Reader responses at some remaining token savings.

Exact immutable parent is the existing V18 original source-first 2×2 corpus: 32 historically and **answer-conditionally** selected LoCoMo questions from just four conversation roots, original source IDs and same SHA-pinned 135M 30-layer Llama-family Reader `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c` and archived ByteLevel tokenizer `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`. The original 10-family LoCoMo dataset bytes are independently pinned. There is **no new Encoder training, Cell Head training, official HF parity, future source-family data, external human judgment, strong reference Reader or FinalUse**.

## Actual intervention

Preserve the V18 original question, source IDs, model, tokenizer, instructions, full-source title and deterministic greedy output ceiling (24 tokens). Independently vary only the primary publisher-annotated witness text in E1:

- `full_original`: full original E1, with identical header, reuse already sealed original V17 answer.
- `single_sentence`: one question-overlap-selected original sentence E1, with *the same full-source header*, reuse already sealed original V18 answer.
- `window_plus_1`: contiguous byte-exact original E1 span containing selected sentence and up to one original sentence on either side.
- `window_plus_2`: same with up to two original sentences on either side.

The selector uses only question words and source text. It never accesses publisher `answer`, gold labels, retrieved-model feedback or heldout target when building the input. Its source-first plan is reconstructed and independently checked before model loading. Crucially, the **historical 32-case panel was itself selected by looking at publisher answers** in V16; that makes every subsequent comparison retrospective and exploratory, even though this V19 source selection does not inspect answers.

32 × 2 new-arm logical slots = **64**, of which 40 are *byte-identical* V17 requests and one new request is duplicated across both V19 arms. Only **23 unique new Reader inputs** needed genuine new execution. All original V17/V18 costs and weights are historical sunk work, not zero lifecycle cost.

## Actually executed and independently recounted

Two *separately initialized* local CPU processes loaded identical SHA-pinned BF16 original Reader weights using the original candidate FP32 Torch implementation. Each executed **23/23 actual novel natural-language prompts**, **526 physical Reader forwards**, **3,919 input tokens and 506 generated tokens**; observed CPU time **84.6455 s / 83.2604 s**, wall time **43.9390 s / 43.2132 s** respectively. Second original outputs had identical 23/23 input IDs, generated token IDs, answer text, source identity and final response SHA. There is no claim of hosted model execution, independent model issuer signature, or official HF operator/tokenizer parity.

A separate independent implementation reconstructed all 32 original source/question cases, precisely re-derived each contiguous text span, refused altered source/input/authority fields, retokenized all 23 model prompts, validated every fsynced pre-attempt start and all exact output tokens, recomputed 526 original forward counts, and re-counted the private postseal publisher outcomes. The output hashes and sanitised aggregates are in the companion JSON. The original dialogues/questions, raw outputs, model weights, private source inventories, golden answer labels, raw per-case decisions and review blinding seed are **not uploaded to GitHub**.

## Postseal-only historical publisher-string observation

| Condition, identical full-source heading | Answer string retained in source (16 cases) | Original Reader answer contains publisher answer (16 cases) | Input tokens (16 cases) |
| --- | ---: | ---: | ---: |
| Full witness | 16 | **9** | 2,854 |
| Question-selected single sentence | 7 | **5** | 2,448 |
| Question sentence ±1 context sentence | 12 | **8** | 2,664 |
| Question sentence ±2 context sentences | 14 | **9** | 2,744 |

Paired against single sentence in the literal-in-source historical cohort: ±1 window **3 gained, 0 lost**, ±2 window **4 gained, 0 lost**. ±2 versus full witness **0 gained, 0 lost** in the publisher-substring proxy; its 16-case input token count is 110 lower than full. These small, historically outcome-conditioned changes are **not statistical or causal generalization evidence**, and the token savings are not proven total lifecycle inference cost savings.

The second 16-case cohort has **5 publisher-answer fields missing** and **zero answer-string matches** under these conditions; missing targets are `unknown`, not silently false negatives. Strict complete response string equality with publisher answers is zero for all four arms. The answer-string presence in source does **not** certify source sufficiency, and its presence in model response does **not** certify semantic correctness or source-grounded citation entailment.

## Reviewer, validation and outstanding gates

The source-only suite tests hostile source-span mutations, parser ambiguity, wrong budget, source IDs, forged utility and authority. It is separate from the original model runs and cannot attest physical execution. 128 new arm-blind **private review tickets** and a distinct owner-only ticket mapping were generated; neither is in the public Git tree and **zero human evaluations have been received**. A ticket is an invitation to judge, not evidence of review.

**NO-GO conditions remain:** V6 seed41 retained paired-world failure; no independent human semantic judgment or truly human-confirmed sufficient-source receipt; no distinct physically executed stronger reference Reader; no provenance-authenticated original source issuer; no independent future calendar windows or 200 disjoint source families; no equal-total-lifecycle 421M vs Granite/Reader Head advantage; no multimodal benefit, NDU/FBSDE or System2 claim. `production_authorized=false`, no selected model, Cell fission/fusion, FinalUse, `main` merge or gate bypass.
