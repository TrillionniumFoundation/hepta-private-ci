# V21 — Independently reconstructed original V13→V14→V16 source and 128-request plan

**RESEARCH / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO PRODUCTION / NO MAIN MERGE.** This branch is an additive, source-first child of PR #2445. It deliberately does not mutate the parent's queued public Qwen physical smoke run.

## Why this increment matters

PR #2445 has a concrete frozen 128-request reference Reader entry point, but its original prompt roster was previously based on the V16 producer's private plan and a reported digest. The local V21 reproducer independently re-opens the **original physical LoCoMo corpus** from historical Actions artifact `11586991191`, computes 5,882 source turns and 1,986 questions across the full ten-family panel, reproduces V14 source-only BM25 Top-32 for every query, reconstructs V16's historically answer-dependent 32-case two-cohort selection and all 128 actual original raw prompt-byte identities, and independently compares the complete source/rank/plan SHA-256 against **existing exact historical hashes**.

This is a byte-reproduction test, NOT a new 135M or Qwen neural forward, NOT proof of evidence sufficiency, NOT prospective enrollment and NOT independent semantic adjudication. Original data, source-only texts, question IDs, exact prompt bytes, private ranking rows and model inputs are kept out of Git and Actions artifacts. The committed sanitized receipt is only an aggregate and fixed digests.

## Actual local execution (2026-10-16)

Using independently extracted original `memory-inputs/locomo.json`, byte SHA `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`:

| Verification | Independently recomputed SHA-256 | Historical source |
| --- | --- | --- |
| V13 source-only snapshot | `9d707c297dc743cffe00d94ead04198b7039f72027743dc6d6e02c826a623a8c` | `v14_primary_only_cost.V13_SOURCE_SHA` |
| V14 full BM25 1,986 × Top32 | `b0b38675d2d5458795d0577d5c861b796dfbdf9e7d4cd089838895c419831697` | `v15_original_candidate_four_arm.source_and_rank` |
| V14 private route envelope | `2f8ee6b1a73b63d57f858ad3bcf4f74554952258b8d3649524ecfcfed14e9342` | V21 original-source recomputation |
| V16 32 × 4 original request plan | `26a4d5a4883c98d61d9405f739dda7e49f433370c30290275f0f04441d7067c8` | Original V16 sanitized receipt `V16_LITERAL_READER_ORIGINAL_NEGATIVE_20261016.json` |

All SHA checks PASS on the original physical file. The original 32 cases were **retrospectively selected using publisher answer literals** and originate from only four correlated historical families. Reconstructing the plan does not undo that selection bias. In the original cohort five publisher answer fields remain unknown, not counted incorrect. Zero new Reader or Qwen physical calls occurred during this V21 reconstruction.

## Reproduce on admitted host (private originals required)

```bash
export PYTHONPATH=qualification/stem-cell-v1
python qualification/stem-cell-v1/v21_original_plan_rebuilder.py \
  --original PRIVATE/locomo.json \
  --receipt PRIVATE/v21-source-parity-receipt.json \
  --private-source PRIVATE/v21-source.json \
  --private-routes PRIVATE/v21-bm25.json \
  --private-plan PRIVATE/v21-v16-plan.json
```

The private source/plan outputs can be passed to the existing PR #2445 Qwen inference path **only with the same frozen model revision and original 128-request validation**. They are create-only. The original archive, source and publisher labels must stay on the admitted private host.

The public source-only CI does **not** open these original files:

```bash
python -m unittest discover -s qualification/stem-cell-v1 -p 'test_v21_original_plan_rebuilder.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_v21_original_plan_rebuilder.py' -v
python qualification/stem-cell-v1/v21_original_plan_rebuilder.py \
  --public-receipt qualification/stem-cell-v1/V21_ORIGINAL_SOURCE_PLAN_RECEIPT_20261016.json
```

## No-go and next scientific predecessor

- Physically execute exactly pinned Qwen3-0.6B on all original 128 matched requests, validate all token and prompt bytes through the independent private reviewer, and preserve actual CPU/wall/peak RSS/temperature/precision and model loading cost. The existing public one-question smoke job is not this study.
- Obtain an independent human-reviewed evidence-sufficiency and semantic-answer/citation-entailment dataset; answer literal containment and source annotation alone cannot prove sufficiency.
- Calibrate against a stronger model with exact source alignment and complete costs; correct for correlation by historical root, not per answer/cell invocation, and evaluate new source-disjoint future windows before any Stem/Cell Split/NDU efficacy assertion.
- All trusted model selection and effect-authorizing runtime owners remain unchanged; `blocking-ci` is not waived. A redacted public receipt is descriptive, not independent signed execution evidence.
