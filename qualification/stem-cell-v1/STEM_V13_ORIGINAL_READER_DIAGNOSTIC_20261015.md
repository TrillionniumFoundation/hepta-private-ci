# V13 addendum — original Reader examination of untrained lexical source differences

**RESEARCH ONLY · SHADOW_ONLY · DENY_ALL. No task-quality/Stem win, no main merge, no production authority.**

This is a physical original-weights **diagnostic subset** of the V13 retrospective full-source retrieval study. It does not upgrade that study into independent prospective inference. In the original 829-case historical heldout census, the preregistered no-training BM25+phrase+character candidate reached publisher-weak evidence any Hit@3 383/829, compared with original BM25 372/829; by source root the deltas were +3, −1, +2, +7. Original generation is necessary before calling that a Reader task gain.

## Pre-score cohort and genuine model material

- The original 1,986-question source-only V13 routes are frozen by SHA before Reader dispatch. Without publisher evidence/answer labels, extract all query IDs for which the original BM25 and frozen `phrase_char` Top-3 **source sets differ**, then select exactly the SHA256(ID)-first **four original questions per historical heldout root**. Source-set disagreement counts before selection were **38 / 53 / 47 / 52** in `conv-47/48/49/50`. The resulting 16 original questions have no duplicated ID; this is intentionally a **source-disagreement-conditioned, retrospective sample**, not a representative blinded experimental cohort.
- Two source selections per original question, three untruncated original source passages in each Reader prompt, 32 exact original Reader requests. Prompts explicitly require citations `[E1]` etc. Same 30-layer archived original BF16 135M Llama-family Reader, SHA `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`, and original ByteLevel tokenizer SHA `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`, reusing the existing V12 manual FP32 PyTorch model owner `v12_reader_runtime.py`. Not official Hugging Face operator/tokenizer parity, no model-host attestation.
- Complete original Reader request plans and all fsynced pre-attempt starts were retained **privately**; all original answer bytes and generated token IDs were sealed before opening original publisher `evidence` annotations in an entirely separate scorer process. No original LoCoMo dialogue/answers, raw Reader text, tokenizer, original model tensors, held publisher labels or per-case raw routes are committed.

## Original observed results (not semantic accuracy)

| Observation | Original BM25 | Frozen `phrase_char` |
|---|---:|---:|
| Original Reader requests | 16 | 16 |
| Publisher-annotated source represented in delivered Top-3 | **5/16** | **5/16** |
| Original Reader input tokens | 2,600 | 2,629 |
| Actual Reader generated tokens | 370 | 372 |

Original output bytes differed between arms on **5/16 questions**. There is no observed positive publisher-weak retrieval delta in this selected subset and **no independently judged question correctness, hallucination rate or semantic citation entailment**. Token costs are not matched. One can change the model answer without making the answer more correct.

Two *separate, completed* authentic archived-Reader CPU processes produced **32/32 bitwise-identical raw answer texts and token sequences**, with **772 forward calls in each**. First run actual original model CPU/wall **101.9686 / 52.6263 seconds**; second run CPU/wall **102.0081 / 52.5732 seconds**. These exclude retrieval ranking, prior V11 training, original Encoder cache creation, model archive download and independent scoring. The independent review validates all 32 original request bytes, original token IDs, source-bound precommits, both result file digests and computed forward-call counts. These are reproducibility observations for a manually implemented inference kernel, not official HF parity.

## Correctness repair before the second run

The source-only protocol's adversarial tests exposed a real weakness: prompt SHA equality alone did **not** forbid an attacker from changing the separately declared `source_ids` metadata without modifying the prompt. The original first run used the legitimate immutable inputs but had an insufficient plan-intake check. The new Reader producer now **rebuilds the entire source-first 16×2 plan from the separately pinned original source-only packet, preregistered retrieval config and 1,986-question route snapshot**, and refuses a byte-unequal claimed Reader plan **before loading the original model**. The second full physical Reader run executed this stricter intake. The independent reviewer separately recomputes the SHA-sorted source-only selection, verifies exactly delivered three source IDs per arm, forbids changed metadata/answer tokens and checks the original model forward count from emitted token sequences. It returns `PRIVATE_ORIGINAL_RECOUNT_NO_GO`.

## Separate, reproducible steps

With the **original privately staged** SHA-pinned LoCoMo and original Reader material present (and the existing V12 model adapter available on `PYTHONPATH`), run:

```sh
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v13_original_reader_followup.py prepare \
  --source PRIVATE/source-only.json --registered-plan PRIVATE/plan.json \
  --ranked PRIVATE/routes.json --output PRIVATE/reader-plan.json
python qualification/stem-cell-v1/v13_original_reader_followup.py generate \
  --reader-plan PRIVATE/reader-plan.json --reader-root PRIVATE/reader \
  --source PRIVATE/source-only.json --registered-plan PRIVATE/plan.json \
  --ranked PRIVATE/routes.json --output PRIVATE/reader-output.json
python qualification/stem-cell-v1/v13_original_reader_followup.py score \
  --reader-plan PRIVATE/reader-plan.json --raw-answers PRIVATE/reader-output.json \
  --original PRIVATE/locomo.json --output PRIVATE/reader-score.json
```

Repeat `generate` into a distinct create-only output, then independently run `v13_reader_independent_review.py` with the plan, two original output files, original source/rank and gold-owner file. The standalone hosted Action only runs the **82 source-only negative/adversarial unit tests** and inspects sanitized aggregate digests; it does not download private original weights or pretend to re-run these physical CPU processes.

**Scientific decision:** HOLD/NO-GO. The complete original V13 829-case +11 is an old weak evidence proxy across only four correlated conversation roots (one regressed), while the exact original Reader 16-case changed-source-set subset shows **zero** additional publisher witness hits and no verified task success. There is no equal-lifecycle-cost superiority against a tuned low-cost RAG baseline or the previously trained Head bank. V6 seed41 continual retention remains failed; independent future-family and calendar-window validation remain absent. Do not enable a Cell promotion, automatic fission/fusion, System2/NDU, FinalUse or production serving from this candidate.
