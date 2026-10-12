# Counterfactual Reader: separate answer yield from appropriate abstention

Research-only extension of [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). **No new Reader calls, new model, data collection, NDU/FBSDE computation or serving change.** Original counterfactual 16 pairs, two variants, and five experimental arms are unchanged. The primary frozen Reader still generates its original 160 raw replies, and their original scoring remains intact.

## Why this audit is necessary

In the original synthetic diagnostic, `strict_success` rewards a grounded correct answer if evidence is sufficient, **or** an appropriate abstention if evidence is insufficient. This combined metric is useful for safety conditional on supplied evidence, but a weak retriever can get the same `strict_success` by withholding useful information and refusing. It cannot be treated as end-to-end reasoning accuracy or proof that a learned selector improves helpfulness.

The new registered read-only audit separates on the full 32-question denominator:

* `programmatically_sufficient`: fixed selector supplied a typed multi-hop source chain;
* `useful_verified_answers`: returned exactly one matching synthetic token with citations covering every required original source;
* `correct_refusals`: no complete typed chain was provided and the frozen Reader precisely refused;
* `unsupported_target_copies`: matched the synthetic target despite missing the necessary chain;
* `counterfactual_pairs_both_correct`: BOTH variants of a relation swap were answered and cited correctly, over 16 distinct pairs;
* `actual_reader_input_tokens`, `actual_reader_generated_tokens` and `unknown_failed_costs_not_free`.

A failed model call remains **unknown**, not a negative training target or a synthetic prediction. Yield and appropriate-refusal bounds retain all incomplete attempts, and paired failures do not disappear from denominators. This is a synthetic string/citation judgment, **not** independent semantic review.

## Deterministic *test* positive control

A tiny typed symbolic responder only reads source snippets supplied to the Reader and generates citations from their actual positions. It cannot access the generated gold answer, hidden source documents, or preferred selection IDs. This checks that the benchmark contains sufficient executable information and that the scorer rewards grounded answers and refusals correctly. It is **not the frozen neural Reader** and must never be merged into its reported accuracy.

On the same fixed 16 counterfactual pairs (32 question variants), the **deterministic test responder** gives:

| Arm | Complete typed evidence | Useful answered and cited | Correct refusals | Old combined strict success | Both variants answered |
|---|---:|---:|---:|---:|---:|
| BM25 top3 | 10/32 | 10/32 | 22/32 | 32/32 | 3/16 |
| Joined top3 | 32/32 | 32/32 | 0/32 | 32/32 | 16/16 |
| Reversed-joined top3 | 32/32 | 32/32 | 0/32 | 32/32 | 16/16 |
| Missing first relation | 0/32 | 0/32 | 32/32 | 32/32 | 0/16 |
| Terminal-only | 0/32 | 0/32 | 32/32 | 32/32 | 0/16 |

This demonstrates the *metric's* failure mode, **not** an empirical Reader result. Naively citing “32/32” across all arms would be misleading.

## Immutable real-Reader audit

After the original Reader run, the add-on:

1. Verifies the original `plan.json` question IDs, source manifests and exact generating commit against current fixed cases;
2. Rehashes the original `raw-answers.jsonl` and checks its `raw-seal.json` (`scoring_started=false`);
3. Re-evaluates every original answer and requires byte-for-byte-equivalent structured original `scored.json` and `summary.json` (no scoring rewrite);
4. Rejects inconsistent Reader inventory/profile across completed calls, missing observed input/output token counts, duplicate/missing question-arm identities, malformed citations and missing evidence;
5. Writes separate yield/abstention/pair-bound diagnostics to a NEW output directory, without modifying the original raw answers or the trained frozen Reader.

The workflow executes the symbolic preflight **before staging the Reader** and the read-only audit only **after the original Reader results have been sealed**. A failure of any earlier step fails closed; artifact upload retains original logs and evidence. All existing test and Ruff F/E9 gates are preserved.

## Verification and scope

**12 new focused local tests passed** against the exact preceding counterfactual source modules. Cases cover copying a correct token without a path, false or partial citations, wrong-counterfactual answers, reversed citation labeling, honest abstention, corrupted raw-answer SHA, score tampering, missing token receipts and inconsistent Reader identity. Python syntax tests passed. Full-repository hosted checks and actual neural answers remain separate until a completed exact-head workflow confirms them.

There is no native language/sufficiency evaluator, external human judgment, calibrated NDU/FBSDE policy improvement, Riccati speed result, or multimodal transfer claim. The original dataset is a small, correlated, synthetic grammar test, not a prospective external benchmark.

Reproduce in a source checkout with `PYTHONPATH=scripts/memory_cell`:

```bash
python scripts/memory_cell/system2_counterfactual_scorer_audit.py /tmp/symbolic-preflight
python scripts/memory_cell/system2_counterfactual_scorer_audit.py /tmp/model-audit \
  --sealed-reader-run /tmp/system2-counterfactual/native
```
