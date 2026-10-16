# V18 — physically isolate evidence body truncation from heading wording

**RESEARCH / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL.** This is an additive study stacked on V17, not a change to production Neuron Cells, model selection, NDU, CAS/CNS, FinalUse, or `main`.

## Causal question and exact 2×2 material

V17 simultaneously changed a section heading and truncated the first annotated source passage to a question-token-matching sentence. V18 crosses these interventions using the same 32 **historically publisher-answer-conditioned** LoCoMo questions and the **identical SHA-pinned archived 135M BF16 Reader** used by V16/V17. Actual FP32 manual Torch decoding remains unverified against official Hugging Face operator/tokenizer semantics.

| Source passage | Heading: complete passages | Heading: relevant sentence |
| --- | --- | --- |
| Full original source | V17 `formatted_full` (immutable prior original output) | **V18** `full_focus_heading` |
| Question-token-focused verbatim source span | **V18** `focused_full_heading` | V17 `formatted_focused` (immutable prior original output) |

The three evidence **source IDs** are identical in every arm. All headers, instructions, and Reader material except the specified heading/body factor are the frozen V17 values. Original V16 selection used publisher answers to form these two 16-case diagnostic cohorts. Within V18, the selection of the verbatim source sentence is **question-only**; neither publisher answer fields nor independent adjudication are loaded during source preparation or model execution.

Of the 32 original source passages, **29 are actually shortened**, and 3 remain unchanged. Those three cases cause exactly 6 cross-arm requests to be byte-identical to the prior V17 prompts: they are reused from actual previously sealed V17 answers, not executed again or counted as six new model calls. The **58 novel** inputs are each generated twice in entirely separate new original-model CPU processes, with durable preattempt start journals and no resume-as-success. There are **128 logical case-arm slots**, **122 unique physically executed request identities across V17 and V18**, but V18 newly executed only 58 unique requests per process.

## Original executed physical work and independent recount

- First V18 real physical run: **58/58** completed, **1,360 Reader forward calls**, **9,779 input and 1,311 generated tokens**, **216.275 CPU / 112.304 wall seconds** (isolated analysis host, not user dot).
- Second freshly loaded original-model process: **58/58**, also **1,360 forwards**, **211.913 CPU / 110.017 wall seconds**. Every original request, output token ID, raw answer text, source membership and input/output token count matches the first process exactly.
- Read-only independent tokenizer/source/journal reviewer checks all 58 original requests and reconstructs the entire 32×4 comparison from immutable V17 outputs plus V18 outputs. Original raw outputs, full source passages, original questions, original model tensor files and publisher labels remain outside public Git.
- The **38** local source/adversarial tests passed in ordinary Python and `python -O`. Hosted source-only CI has **no physical pretrained weights or private answers** and cannot attest model execution or complete `blocking-ci`.

## Outcome: historical publisher answer *substring*, NOT semantic accuracy

For 16 questions whose annotated source literally contains the publisher answer string, across two independent input factors:

| Body/Heading | Complete-passage title | Relevant-sentence title |
| --- | ---: | ---: |
| Full body | **9/16** | **7/16** |
| Focused body | **5/16** | **3/16** |

On the **same 16 questions**, the paired **shortening-only** contrast is **0 gained / 4 lost** under each fixed heading. The paired heading-only contrast is **1 gained / 3 lost** for the full body, and **0 gained / 2 lost** for the focused body. Factor-interaction sum is zero at the aggregate level, not a proof of no interaction in the underlying task. In the other 16 historical questions no arm produced a known publisher-answer substring; **five publisher answer fields are missing and counted as unknown**, not failures. Strict complete-answer literal equality is zero throughout.

By condition, actual **logical** Reader input tokens across all 32 cases are 5,679 / 5,871 / 4,884 / 5,076 (full+complete title / full+focus title / focused+complete title / focused+focus title). This is **not matched input-token cost**. Costs of the original V17 executions are historical, not counted as free training/work; the two new V18 processes independently record their new work. Neither lower prompt length nor change in substring match is equivalent to end-to-end semantic task success or improved Cell utility.

## Evidence and privacy boundaries

A separate post-seal label-owner process reads the original benchmark only after the original Reader answer file was create-only sealed. An independent after-seal reviewer reports literal publisher answer substring/exact proxies by cohort and by the **four original source families**; 32 questions are not 32 independent source roots and there are **zero prospectively witnessed calendar windows**. Reproducible raw private answers are verified by hashes but no externally authenticated model-host signature, signed independent evaluator, reference Reader, or human semantic adjudication has been supplied.

An independent reviewer intake produces **128 randomized blinded tickets** and a separate owner-only HMAC mapping. **Zero external reviewers have returned actual judgments.** The owner secret and mapping must never go to reviewers or public CI. Tickets and original text are not uploaded to GitHub.

No official Hugging Face numerical parity; no independent human sufficiency or semantic citation entailment; no new source-family/temporal generalization; no matched total lifecycle cost; no V6 seed41 retention repair; no production or selected Stem. **All acceptance gates remain HOLD_NO_GO / DENY_ALL.**

## Local reproduction commands

With registered original full source and Reader files already present, run only into **new** private create-only output paths:

```sh
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v18_factorial_original_reader.py prepare --source PRIVATE/source-only.json --ranks PRIVATE/original-bm25-private-routes.json --v16-plan PRIVATE/v16-plan.json --v17-plan PRIVATE/v17-plan.json --out PRIVATE/v18-plan.json
python qualification/stem-cell-v1/v18_factorial_original_reader.py run --source PRIVATE/source-only.json --ranks PRIVATE/original-bm25-private-routes.json --v16-plan PRIVATE/v16-plan.json --v17-plan PRIVATE/v17-plan.json --plan PRIVATE/v18-plan.json --reader-dir PRIVATE/reader --out PRIVATE/v18-first.json
python qualification/stem-cell-v1/v18_independent_original_review.py --plan PRIVATE/v18-plan.json --new-answers PRIVATE/v18-first.json --new-starts PRIVATE/v18-first.json.starts.jsonl --v17-plan PRIVATE/v17-plan.json --v17-answers PRIVATE/v17-original-answers.json --reader-dir PRIVATE/reader --out PRIVATE/v18-first-recount.json
```

Repeat original Reader independently with a fresh output and compare the original results in the read-only auditor. Run the original-label scoring **only after** answer sealing; never pass benchmark label fields to the producer. For public source-only negative conformance:

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest discover -s qualification/stem-cell-v1 -p 'test_v18_*.py' -v
PYTHONPATH=qualification/stem-cell-v1 python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_v18_*.py' -v
python qualification/stem-cell-v1/v18_public_no_go.py --receipt qualification/stem-cell-v1/STEM_V18_FACTORIAL_ORIGINAL_NEGATIVE_20261016.json
```
