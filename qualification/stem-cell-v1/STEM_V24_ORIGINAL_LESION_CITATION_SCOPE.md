# V24 — Original 135M Reader: source-scoped citation instruction

**RESEARCH / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / no main merge / no FinalUse / no automatic Cell Split.**

## Motivation and exact causal intervention

Predecessor PR #2527 V23 physically executed 96 source-bearing original Reader requests and deterministically abstained on 32 no-source questions; all 96 original Reader outputs were byte-identical to the separately sealed V22 full-original experiment. Structural audit of those original 96 real answers found 64 with in-range citation syntax, 29 with no citation, and three with **out-of-range** references. All three happened in the 32 two-source **lesion** requests. The V16 source-bound prompt had hardcoded "using [E1], [E2] or [E3]" even though lesion provided only `[E1]` and `[E2]`.

V24 changes **only** that one source-ID instruction clause to "using [E1] or [E2]" for the 32 lesion requests. All original questions, complete evidence bytes, source IDs and order, archived 135M model, manual frozen FP32 Torch inference, greedy decoding, 24-token cap, cohort, and generation context remain unchanged. No publisher answer enters preparation or model inference. The code reconstructs the immutable V16 128-request plan and independently verifies the source-only corpus SHA, all 1,986 original BM25 Top-32 routes, and exact private lesion request identities; a new 32-request plan is private/create-only.

The intervention is **a fixed prompt-format contract comparison, not a learned Cell, new inference policy with proven semantics, or NDU**. It does not claim equal input-token costs because the two instruction clauses tokenize differently.

## Real observed first original-model execution — 2026-10-16

The original Reader weights are SHA-256 pinned to `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`, tokenizer `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` and config `8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a`. The source corpus and V16 plan stay pinned to the same original V21/V22 controls.

- The modified private 32-request plan SHA-256: `b6df57f17d12c01e56bf66a2c1e56a845b878838192293fd217ea0215a66a1c5`.
- First **genuine physical original 135M CPU model run**: 32/32 model requests, **775 original model forward calls**, 3,829 input / 746 generated tokens, **104.733353 CPU seconds, 54.313821 wall seconds**. Every request start was written and fsynced before model dispatch; raw model outputs were create-only and retained locally, not committed.
- Previous V22 physically executed original 32 lesion controls: **767 forwards, 3,957 input / 741 generated tokens**. Different-run CPU/wall and token counts are descriptive only, not a speed comparison.
- A separate reviewer re-tokenized all 32 new inputs, decoded and rehashed every actual generated token sequence, reconciled the forward count, reproduced the original immutable V22 128-request source/answer receipt, and opened original publisher answer fields **after** the new output was sealed.

### Citation syntax outcome (not semantic entailment)

| Original lesion answer category | V22 exact original baseline / 32 | V24 source-scoped clause / 32 |
|---|---:|---:|
| One or more citations, all reference indices in 1..2 | 22 | **26** |
| No `[E#]` citation | 7 | 6 |
| At least one reference index outside 1..2 | 3 | **0** |

Actual paired transitions: 22 in-range→in-range, 3 out-of-range→in-range, 1 absent→in-range, 6 absent→absent. This is a structural output improvement, not evidence that citations *entailed* the generated answer.

### Negative outcome retained

Only **27/32** historical questions have nonempty publisher answer text. On the 16 historical answer-literal-in-witness cases, neither original lesion nor V24 produced the publisher answer as a literal substring. Among the 11 other known-answer questions, the original lesion baseline had **1 weak literal substring hit**; V24 had **0** (0 gained, 1 lost). Five unknown labels remain censored, not scored wrong. Neither substring match nor its disappearance independently determines semantic correctness; no "winner" or automatic rollout can be declared from these results.

## Strict scientific and operational boundaries

- Sample: 32 retrospective answer-dependent LoCoMo questions from **four correlated historical roots**. This is not 32 independent sources or prospective new-time generalization.
- No actually executed Qwen3-0.6B reference-model evaluation, stronger Reader efficacy, independent human evidence sufficiency/semantic entailment, official HF tokenizer/operator parity, full matched model lifecycle efficiency, new Cell learning, NDU/FBSDE, multimodal generation or any 10T/100T equivalence.
- The complete local private inputs, publisher target labels, original Reader weights, raw generated tokens, process start journals, private original answers and per-case routes **never enter Git**. Commit only source-only mechanism code, adversarial tests, this runbook, and digest/count-only sanitized receipts. GitHub workflow must not fetch private models, make model calls, or upload any artifacts.
- Source-only CI can verify **consistency** of committed count/digest receipts, not independently re-perform the actual private model computation. Physical execution must be verified in a separately admitted runtime, and CI success may never substitute for `blocking-ci`, model selection, FinalUse or production authority.

## Private exact-byte reproduction

```bash
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v24_lesion_source_scoped_citations.py prepare \
 --source PRIVATE/source.json --routes PRIVATE/routes.json \
 --original-plan PRIVATE/v16-plan.json --plan PRIVATE/v24-plan.json
python qualification/stem-cell-v1/v24_lesion_source_scoped_citations.py execute \
 --source PRIVATE/source.json --routes PRIVATE/routes.json \
 --original-plan PRIVATE/v16-plan.json --plan PRIVATE/v24-plan.json \
 --reader PRIVATE/reader --output PRIVATE/v24-physical-answers.json
python qualification/stem-cell-v1/v24_lesion_citation_independent_review.py \
 --source PRIVATE/source.json --routes PRIVATE/routes.json \
 --original-plan PRIVATE/v16-plan.json --new-plan PRIVATE/v24-plan.json \
 --old-answers PRIVATE/v22-original-answers.json \
 --old-starts PRIVATE/v22-original-answers.json.starts.jsonl \
 --new-answers PRIVATE/v24-physical-answers.json \
 --new-starts PRIVATE/v24-physical-answers.json.starts.jsonl \
 --reader PRIVATE/reader --original-gold PRIVATE/locomo.json \
 --output PRIVATE/v24-private-review.json
```

Use new, empty private paths for every independently reloaded repeat process. Retain all negative controls, old V23 no-evidence budget savings, and the Qwen reference branch without mutation. **Do not merge this research PR into main or authorize live routing.**

## Exact independent second original-model process

A **freshly loaded, separate original 135M CPU process** completed the same source-scoped 32 requests: **32/32**, **775 real forwards**, **103.906879 CPU seconds**, **53.946643 wall seconds**. A separate process re-opened the exact original source, model/tokenizer and postseal historical gold, re-tokenized and reviewed all 32 physical new answers, and the non-authorizing repeat comparer verified **byte-identical generated token/answer lineage and source IDs** across both processes. The first and second complete physical receipts have different measured CPU/wall and hence different complete receipt digests. This observation is restricted to the tested CPU/operator implementation, not HF official numerical parity.

Public source-only safety checks include the report `V24_ORIGINAL_LESION_REPEAT_20261016.json`. Its digest consistency gate **cannot** independently reproduce those CPU processes; never label a source-only CI pass as physical model attestation. Total newly executed workload across the two V24 processes: **64 new original Reader requests / 1,550 forwards**. Their new costs are not hidden or double-counted as previously executed V22/V23 forwards.
