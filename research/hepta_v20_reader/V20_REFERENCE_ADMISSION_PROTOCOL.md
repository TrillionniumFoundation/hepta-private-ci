# V20 Qwen3 source-first preflight / token alias conservation

**DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO MAIN MERGE.**

## Lineage and why this change exists

This is a strict research descendant of [V19 PR #2523](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2523), at **`aa807d61edd0f5e88178ab9812e59eabe2613f20`**. It does **not** replace, revise or claim results from the physical V17/V18 original 135M Reader experiments. It does not modify production Neuron, NDU, Worker, selected models, CNS, CAS or FinalUse. V19's real Qwen3 branch has not yet yielded any terminal exact-HEAD physical reference result in this observation.

V19's original physical workflow ran a costly 135M reference **before** discovering whether Qwen model downloads and native tokenization succeeded. This V20 change stages the exact immutable Qwen publisher model bytes, verifies the model snapshot and all 120 model-specific native Chat inputs, and only then executes the original 135M and Qwen model steps. Fail-fast is operational resource conservation **only**; it is not model success.

## Three actual gates

1. **Static source/material admission (before heavy model calls):** require the original V17/V19 exact immutable source/plan, 10 conversation roots, 30 questions, four original evidence arms, **120 original logical requests / 96 unique Qwen inputs**. Confirm publisher answers and raw full corpus have already been removed from inference source directory. Recheck exact official Qwen publisher SHA/size metadata, staged model bytes, native tokenizer and every untruncated input. Each distinct source message must correspond to exactly one physical input token sequence and vice versa; repeat references must have bit-identical encoded inputs. A private `0600`, fsynced, create-only, source-content-free receipt records only hashes and token counts.
2. **Actual-model execution (only after admission):** the existing, unmodified V17 135M and V19 original Qwen3 executors are called on the inherited exact source-first prompts. V20 does not contribute new model weights or learned Heads, does not claim pretrained inference from source-only tests, and never substitutes synthetic material for original model weights.
3. **Alias and charged input accounting (after sealed Qwen, before publisher labels):** independently recompute logical-to-physical grouping from the Qwen-produced `requests_by_id` and token lengths. Each physically shared encoded input is charged **once**; all 120 logical requests remain present but cannot multiply actual physical input cost. A forged or re-signed different alias map, model revision, source digest or token length is rejected before source-gold recovery. **No semantic entailment, real accuracy, human evidence sufficiency or NDU benefit is inferred.**

The existing independent V19 postseal scorer still opens publisher answers only after both physical model outputs have sealed, performs separate original source/model-token/forward review, and keeps missing source answers as censored/unknown rather than false wrong answers.

## CI and negative controls

The V20 child branch adds 21 source-only negative/mechanism tests. These use synthetic model-token implementations **only to check contracts**, not to infer any accuracy. Retain all **40 inherited V19** tests; run both suites under ordinary Python and `python -O -S` without skipping checks. Exact HEAD and all required global `blocking-ci`/Architecture checks remain mandatory. The deployed GitHub Actions research workflow uses the actual pinned public Qwen3 revision; if access fails or jobs never run, there is no Qwen success.

No claim of model winner, fair same-token comparisons, independent semantic adequacy, trained structural Cell benefit, stochastic FBSDE/NDU improvement, production readiness or eventual 4,096-Cell scale. Original 10 LoCoMo roots are historical, not prospective evaluation windows.
