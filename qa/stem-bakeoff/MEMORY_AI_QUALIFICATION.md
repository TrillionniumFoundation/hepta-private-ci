# Memory A–I preregistered qualification

This is a **SHADOW_ONLY / DENY_ALL / HOLD_NO_GO** research protocol, not proof of model memory superiority.

## Required experiments

A BM25; B dense+BM25+reranker; C Graph-RAG; D typed untrained memory; E frozen shared Encoder+one trained Head; F multiple typed Heads; G F+learned Router; H G+learned Meta-Graph; I H+split/merge evolution.

Required matched ablations: E_FROZEN, F_SWAPPED, G_FIXED, H_PERMUTED, I_STATIC. All nine arms and all five controls must use the same question census, source cut, forget frontier, Reader/tokenizer/prompt/decoding and Top-8/4096 byte/64 output token bounds. Never fill gaps using runs from different cohorts or older SHAs.

## Prospective freeze

The checked-in `memory_ai_protocol_v1.json` precommits to eleven paired causal contrasts, two independent future windows, 200 independent source families per window, seeded family-level bootstrap with simultaneous multiplicity correction, and baseline/cost/safety floors. The protocol must be frozen before observing future answer labels or predictions. Hold out gold in an independent scorer.

## Mandatory refusals

Fail if any (question, arm) row is absent, if source/forget/Reader digests drift, if an arm fabricates result availability, if a model trains on future sources, if a control changes its budget or source ancestry, or if the independent evaluator disagrees with the sealed answer/evidence record. Unsupported citations, wrong-pair learning and removal of essential premises must remain visible.

None of the existing PR #3125 LoCoMo, Procedural Head, Router and split experiments can be spliced into a prospective A–I result: their tasks, cohorts and budgets differ; several measured quality gates already fail. PR #2085 explores a different nine-arm matrix with additional missing original-run evidence.

## Open blockers

No complete original A–I physical run, truly prospective future source windows, independent answer/citation judgments, authenticated original model/Reader execution receipts, full TCO, source withdrawal/unlearning witness, multi-host qualification or terminal exact-head blocking CI is established here. No new facts are written and no trained weights or topology are promoted.

The complete Python scorer, 35 local adversarial tests, and detailed schema/runbook are retained in the companion review artifact. Actual external model and source authority is required before scientific or production claims.
