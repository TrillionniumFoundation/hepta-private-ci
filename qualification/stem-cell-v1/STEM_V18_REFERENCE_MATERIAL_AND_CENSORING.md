# V18 — pinned Qwen material admission and missing-gold censorship (research only)

**DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No main merge, FinalUse, learned Cell selection or Cell Split.**

## Two concrete V17 blockers

1. The V17 physical inference path required an operator-generated full-file SHA256 manifest without a reproducible pinned-model staging command. `v18_reference_material_stage.py` stages only the exact Qwen/Qwen3-0.6B revision `16706fc57485378d4ffaf54139b29ccc66ae08fa`, matches the publisher's SHA256 for LFS weight bytes, copies private regular files to a new directory, hashes every file, records the existing V17 strict model-spec format, and rejects symlink escape, changed revision, missing files, mixed generations and partial output. HTTP metadata and local checks are **not** a signed publisher or model-host attestation.
2. The prior V17 weak publisher-gold scorer aborted when any historical publisher answer was absent, even though original V18 diagnostics in PR #2429 explicitly retain **five missing answer fields**. Its postseal scorer now records separate `publisher_answer_known` and `publisher_answer_unknown` counts in every paired arm, refuses wrong non-string values, and does not turn missing labels into correctness failures. The original 32-case retrospective population and its four correlated roots remain unchanged.

## Private physical sequence

Only use a host that is explicitly admitted for the historical source and weights. Do not put original questions, source text, publisher answers, original model or generated tokens into GitHub commits, logs or Actions artifacts.

```bash
export PYTHONPATH=qualification/stem-cell-v1
mkdir -m700 PRIVATE/qwen-cache
python qualification/stem-cell-v1/v18_reference_material_stage.py \
  --cache-dir PRIVATE/qwen-cache \
  --model-dir PRIVATE/qwen-regular-model \
  --model-spec PRIVATE/qwen-frozen-spec.json
python qualification/stem-cell-v1/v17_reference_reader_physical.py \
  --plan PRIVATE/v16-plan.json \
  --source PRIVATE/source-only.json \
  --bm25 PRIVATE/original-bm25-private-routes.json \
  --model-dir PRIVATE/qwen-regular-model \
  --model-spec PRIVATE/qwen-frozen-spec.json \
  --output PRIVATE/v17-reference-answers.json
python qualification/stem-cell-v1/v17_reference_independent_review.py \
  --plan PRIVATE/v16-plan.json \
  --source PRIVATE/source-only.json \
  --bm25 PRIVATE/original-bm25-private-routes.json \
  --model-dir PRIVATE/qwen-regular-model \
  --model-spec PRIVATE/qwen-frozen-spec.json \
  --answers PRIVATE/v17-reference-answers.json \
  --starts PRIVATE/v17-reference-answers.json.starts.jsonl \
  --candidate PRIVATE/v16-original-answers.json \
  --review-output PRIVATE/v17-independent-byte-review.json
```

A separate postseal gold holder may add `--original-gold` and `--gold-output` to the independent reviewer after both physical model outputs have been sealed. The weak literal/exact tallies are **not** independent semantic correctness, source entailment or human sufficiency.

## Validation and scientific boundaries

The source-only regression set is **43/43 local tests**, repeated successfully under regular Python and `python -O`. Thirteen new model-free tests include real temporary physical fixture bytes, private file permissions, publisher SHA checks, symlink escapes, mutation/partial cleanup and five missing-label cases. These are synthetic mechanism tests, not Qwen neural forwards.

**Still missing:** staged original Qwen weights on this execution host, 128 new real reference-model forwards, independent human-reviewed sufficient evidence and semantic answers, prospective source-disjoint windows, matched complete CPU/GPU/token/energy cost, qualified cross-model comparison and production approval. Keep all authority flags false.
