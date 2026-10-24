# Frozen 0.5B Reader lexical-factorial archive audit

This is a **read-only post-seal** audit of an ALREADY COMPLETED 320-call
frozen Qwen2.5-0.5B-Instruct experiment in the draft PR #1546. The audit
does not invoke a Reader, modify answers, generate references, train an
Encoder/Cell, select a favorable prompt, merge main or touch serving.

## Immutable source and exactly observed hosted status

Source workflow: [38333959891](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38333959891),
source commit `4fe8ac3d75132a21abf2c3e9d172c637e1bb6f91`,
tree `a128abb8082e86734aa0d573176a74d20fc0dcce`,
artifact ID **11784676839**, GitHub ZIP SHA256
`0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19`.
Hosted run completed successfully: **320/320** Reader calls, zero execution
errors; **1,384 Python tests passed, 49 skipped** (1,433 total), and
scoped Ruff checks passed. Original experiment disposition:
`lexical_factorial_not_qualified`.

The frozen parent 160-call Reader is separately externally pinned by SHA256
`853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37`,
GitHub artifact **11768355664**. Both experiments use the exact same
Qwen2.5-0.5B-Instruct snapshot revision
`a338b55dd21219a5f4da42bc11a9313d1a27d4cc`, model identity and
greedy 64-token decoding. No current model access or provider API is needed
to replay the saved evidence.

## Why a second, strictly read-only analysis

The registered four profiles vary **two lexical factors simultaneously**
over **twenty fixed correlated fictional task identities**:

| Factor | Levels |
| --- | --- |
| Relation wording | clearance token / inventory code |
| Identifier spelling | TOK- / TAG- |

The four evidence conditions are a single correct relation, a correct
relation plus a competing code, one wrong-code fact, and no fact. The
original overall success can obscure a poor answer-yield rate if refusals
are scored together with answers. Never count an appropriate refusal on
insufficient input as useful evidence-grounded answering.

Audit steps, all required before interpreting any score:
1. Verify **both externally pinned ZIP hashes**, every internal SHA256
   inventory member, original source Git commit/tree, factorial plan and
   full raw-answer seal.
2. Confirm every planned 20×4×4 question/arm/profile start/result and its
   exact source excerpt bytes/identifier, delivered E labels, bundle/query
   digests, single Reader identity and recorded model/token/cost receipts.
3. Recompute all 320 saved score fields, all 16 archived summary groups and
   the unchanged fixed-primary promotion threshold. Any mismatch aborts;
   omitted or failed answers cannot become synthetic negative targets.
4. Within each matched question and evidence arm, report wording-only
   transitions at fixed TOK/TAG prefix, prefix-only transitions at fixed
   wording, and their descriptive 2×2 interaction. Keep distinct counts
   for exact answers, appropriate refusals, **over-refusals**, unsupported
   identifier copying and actual CPU/token totals.

The effects are observational fixed-hypothesis diagnostics of generated
synthetic strings. Different prompt words also change tokenizer input,
so this does **NOT** identify the model's internal safety policy, establish
causality under equal FLOPs, independently confirm natural-language
semantic support or establish NDU/FBSDE benefit. No winning alternate
profile may be selected after seeing the 320 scores: only
`inventory_tag` was registered for possible independent follow-up.

## Reproduction

With an exact checkout and the two downloaded ZIP files:

```sh
PYTHONPATH=scripts/memory_cell python \
  scripts/memory_cell/system2_reader_lexical_sealed_audit.py \
  /tmp/factorial-320.zip /tmp/original-qwen-160.zip \
  /tmp/lexical-audit.json
```

A separate pinned GitHub Actions workflow runs the full MemoryCell
regression and Ruff checks, then performs this same zero-inference
archive audit and publishes its complete per-arm, per-factor cost and
quality record. It does not re-run the original 320 model calls.
`production_accepted=false` and `independent_natural_task_evidence=false`.
