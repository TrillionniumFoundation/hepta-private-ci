# V23: Real original 135M evidence-absence abstention control

**RESEARCH ONLY · DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL.** This is a narrowly scoped bounded CPU experiment. It does **not** modify Hepta product inference, authorization, learning, NDU, Model Selection, CAS/CNS/FinalUse or `main`.

## Real predecessor and controlled intervention

Previous PR #2522 (V22) physically loaded the original SHA-pinned 135M model twice, running 32 LoCoMo historical questions under all four original evidence arms (128 model calls per process), with two byte-identical model output traces. The historical V16 plan digest was `26a4d5a4883c98d61d9405f739dda7e49f433370c30290275f0f04441d7067c8`. V22 physically recorded 2,951 model forwards, 16,264 input and 2,855 output tokens per run.

An independent inspection of those original model outputs exposed a **deterministic protocol failure**: all 32 `none` arms contained **zero delivered source IDs**, but not one returned the explicitly required `unknown`. The full 128 original outputs hit the 24-token generation cap in **99** cases; **3** responses included a numbered citation outside the delivered source inventory. These metrics are syntactic/protocol properties; the review does not certify natural-language semantic correctness or human evidence sufficiency.

V23 makes exactly one **input-admission intervention**:

- The 32 source-empty `none` requests return a typed, deterministic `unknown` without tokenizer or model invocation; they still produce one fsynced source-bound decision receipt each.
- The remaining 96 `retrieved` / `witness` / `lesion` requests are **physically executed again** by the same frozen original 135M model, same prompt, exact parameter and decode schedule, and publisher-gold-free input. Results must be byte-for-byte identical to the original V22 corresponding answers and token IDs, or the entire comparison fails.

No source IDs are added, no text evidence is edited, and no model weights are trained or altered. All 128 logical requests are preserved. The CPU/wall measurements of two distinct sequential physical model runs are descriptive, not a controlled hardware energy or complete lifecycle cost estimate.

## Fixed observables and expected no-source resource avoidance

These values are independently calculated from the original V22 exact sealed model output and represent the exact work spent on the 32 original `none` prompts, not simulated FBSDE tokens or assumptions that one request equals one forward:

| Physical source | Original full 128-model baseline | New source-empty guard target |
| --- | ---: | ---: |
| Logical question/evidence arm slots | 128 | 128 |
| Actual pretrained Reader request count | 128 | 96 |
| Deterministic source-empty responses | 0 | 32 |
| Original model forward calls | 2,951 | 2,293 |
| Model input tokens | 16,264 | 14,328 |
| Model generated output tokens | 2,855 | 2,210 |
| No-evidence protocol violation | 32/32 | 0/32 by deterministic guard |

The intervention thus avoids 658 of the 2,951 original model forward calls (22.3%) **in this fixed request inventory**. This is reduction of unnecessary original model inference work, not a learned Reader improvement, quality win, Qwen comparison or claim of service-wide 22.3% savings. Changes to call mix and model amortization change the result.

## Source-first private reproduction

The operator must possess the *independently authenticated* original V16 source/rank/plan, original 135M model weights and the original first V22 sealed answer and start journal, all at their SHA-pinned bytes. They are not committed to Git. On a qualified machine:

```bash
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v23_evidence_absence_shadow.py \
  --source PRIVATE/source.json --routes PRIVATE/routes.json --plan PRIVATE/v16-plan.json \
  --reader PRIVATE/original135m-reader --answers PRIVATE/v23-guarded-original.json
python qualification/stem-cell-v1/v23_evidence_absence_review.py \
  --plan PRIVATE/v16-plan.json --baseline PRIVATE/v22-physical-original-answers.json \
  --baseline-starts PRIVATE/v22-physical-original-answers.json.starts.jsonl \
  --guarded PRIVATE/v23-guarded-original.json \
  --guarded-starts PRIVATE/v23-guarded-original.json.decisions.jsonl \
  --reader PRIVATE/original135m-reader --receipt PRIVATE/v23-private-review.json
```

Both actions create output files with exclusive file creation. Every neural dispatch is preceded by an actual fsynced attempt record. All 32 source-empty skip decisions are also fsynced, even though no model forward is performed. The private reviewer uses the original selected tokenizer to independently recount every live model output; the original full baseline is verified separately, and any changed original source, missing/duplicate start, altered nonempty answer, invalid numerical token, fake reduction or changed model identity denies the result. Missing/interrupted physical work never creates a success seal.

## Current observed outcome and what is NOT established

The sanitized report `V23_ORIGINAL_GUARDED_PHYSICAL_20261016.json` records only counts, hashes, cost and explicitly false authorization flags. Source-only hosted Actions check test mechanics and sanitized-report consistency; they **do not** download raw sources or weights, rerun physical inference, or independently cryptographically attest the author's experimental host.

The historical questions were *retrospectively selected* with the publisher answer and cover just **four correlated original conversation roots**. Five have missing publisher-answer fields. The protocol abstention correction is independently checkable because the original source list is empty. No external reviewer has established full evidence sufficiency, grounded citations or semantic correctness. This experiment does not attempt automatic Cell Split/Merge, NDU/FBSDE advantage, multimodal generation, 10T/100T equivalent capability, actual Qwen3 baseline or production activation.

## Actual physical execution and independent recount (2026-10-16)

In an isolated CPU execution environment, the original SHA-pinned 135M Reader was loaded again, with all original V16 request/route SHA values verified before any output was created. The measured V23 execution completed **96/96 actual neural model requests**, exactly **2,293 counted original model forwards**, **14,328 original input tokens** and **2,210 generated tokens**, while **32/32 source-empty inputs** were handled by the deterministic gate with no model invocation. Total execution: **314.512339 CPU seconds** and **162.701465 wall seconds**. The process produced private, create-only, fsynced decision journals and sealed answers only after the full 128-row roster completed.

The separate reviewer re-opened the original V22 full-model output and journal; independently re-tokenized all 96 executed input prompts and their 96 output token arrays; verified **bit-for-bit equality of all 96 actual pretrained answer outputs** relative to the complete frozen V22 control; verified each of the 32 no-evidence decisions, complete 128 attempt ordering, original model identity, original 2,951-call control, and exactly 658 avoided original model forwards (plus 1,936 input / 645 output original tokens). The reviewer produced a separate digest-only, non-authorizing physical receipt. Local source/contract checks and optimized Python checks are independent of the neural execution and must never be counted as model invocations.

Compared with the prior full 128-model run at 403.84 CPU / 209.61 wall seconds, this single V23 run's CPU/wall are descriptively lower. Because the two runs were not randomized, balanced, repeated hardware-energy experiments, **no population-wide speedup or energy saving is claimed**. All other 96 answers remain identical, but their *semantic correctness* has not been independently human-reviewed. The 32 source-empty return strings are enforced policy abstentions, not learned model answers.

**Strict conclusion:** This is a real narrow protocol-resource experiment, not neural learning or a new Reader baseline. Original Qwen3 independent 128 paired outputs and grounded independent task evaluation remain mandatory, and the real product inference path remains unchanged (`DRAFT / SHADOW_ONLY / DENY_ALL`).
