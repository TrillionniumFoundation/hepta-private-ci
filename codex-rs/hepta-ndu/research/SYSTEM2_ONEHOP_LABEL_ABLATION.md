# Frozen one-hop Reader label-echo causal ablation

**Research-only follow-up to PR #1546**. No Reader weight, tokenizer, Encoder,
Cell, NDU/FBSDE/Riccati backend, default serving, native memory writer or
production policy change. The existing original 80 answers and the subsequent
140 cardinality comparisons are not regenerated.

## Completed motivating evidence

GitHub Actions run `38266329906` completed at generating commit
`0abf776ccb577755ddba36dea3fa21a078308ad7`. Artifact
`11756357532` has externally reported and locally verified ZIP SHA256
`9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`.
All 25 inner manifest entries verified, along with the original raw-answer
SHA256 `cc04bd7fd7ecc5aed4234f9512c344eb6feffe8dd0e858507bf1688dff4cda61`.

Full MemoryCell hosted regression: **1296 passed, 24 skipped**, with Ruff
passing. **140/140** new Reader attempts completed, no execution failures.
Under the original frozen Reader and original citation-requesting prompt,
adding just one competing device/token fact yielded **0/20** correct target
mentions and **20/20** label-only outputs (`E1`, `E2`) when the correct
fact was first. Moving it last did not help (0/20 target mentions,
19/20 label-only). With 1 or 2 unrelated *non-token* context facts,
target mentions were 3/20 or 8/20, but none became strict grounded,
source-cited answers. Original sole-fact historical control was 18/20
target mentions; no-evidence outputs were not the mandated refusal.
This is one synthetic 20-question corpus repeatedly interrogated, NOT
140 independent queries or a natural-language competence benchmark.

## Completed frozen-Reader outcome and strict decision (October 14, 2026)

The registered test **has completed** on GitHub Actions
[38273406637](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38273406637):
**140/140** real frozen-Reader calls, **zero execution failures**, full
MemoryCell regression and scoped lint passed. GitHub artifact **11760345185**
has external ZIP SHA256
`a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a`.
The separate exact-source, model-free
[qualification run 38492538441](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38492538441)
also completed successfully; its artifact **11862283420** has GitHub ZIP
SHA256 `ca22a3147f79d0d89f0e98df506fdae7301c3498e46e4872638d9b40cb64328a`.
These receipts do **not** make the synthetic results independent.

The observed per-arm results are:

| Same 20 exposed questions | Labeled exact answers | Labeled label echoes | Unlabeled exact answers | Unlabeled label echoes |
| --- | ---: | ---: | ---: | ---: |
| Single correct fact | 0/20 | 12/20 | **0/20** | 0/20 |
| Correct fact plus competing Token | 0/20 | 12/20 | **0/20** | 0/20 |
| One irrelevant Token fact | 0/20 | 10/20 | **0/20** | 0/20 |

The separate no-evidence control also produced **0/20** exact registered
refusals. All **60/60** new *unlabeled, nonempty* responses used the entire
64-token decoder allowance, rather than recovering answer-only behavior.
For the three paired groups, removing labels reduced input tokens by five,
ten and five tokens **per question**, respectively. The prompt/input compute
is therefore not exactly matched.

**Disposition: `reader_label_removal_not_qualified`.** Removing visible
`E1/E2` fields cures one surface symptom (label-list echo), **not** grounded
answer extraction, safe abstention, or supported citations. Do not promote
the Reader or attribute an NDU/FBSDE improvement. Original raw model
responses and proof-carrying *external system* answers remain separate.

## What this experiment isolates

Hypothesis: the original explicit `E1`/`E2` evidence labels interact with
citation instructions to induce a label-list completion, concealing an
otherwise accessible token extraction ability. The trial removes the
citation-requesting task instruction **in both paired conditions** and
instructs the same frozen model to output **only** an exact token or a
fixed explicit refusal.

For the paired arms, the model, SYSTEM message, question, document order,
observed times, all excerpt bytes, JSON field values (except the absent
`label` property), token limit and greedy decoder are identical:

* `labeled`: evidence item is `{label, observed_at, text}`;
* `unlabeled`: same evidence item is `{observed_at, text}`.

No gold answer is consulted in source choice, prompt compilation or generation.

Fixed source conditions per existing one-hop question:

| Evidence condition | Paired labels? | Actual model calls |
| --- | --- | ---: |
| Original single direct fact | yes | 40 |
| Direct fact then one competing token fact | yes | 40 |
| One unrelated token fact, without the target fact | yes | 40 |
| Empty evidence | one unlabeled presentation | 20 |
| **Total** | | **140** |

The zero-evidence arm has no per-document labels, so duplicating identical
tokenizer inputs would add zero scientific information; only one run per
question is planned. Other source arms reuse original document identities and
all of their original source bytes; this is NOT a fresh held-out test set.

## Frozen protocol and admission

Pre-model: verify the external GitHub ZIP digest, every member SHA256, the
historical commit/tree, all 140 raw answers and prediction seal, the full
registered source/score census and exact original Reader identity.

Run all 140 attempts in deterministically rotated arm order. Record a
fsynced start event and completed/failed event, source bundle digest, encoded
input-token hash, Reader profile, original model identity, original delivered
source byte spans, generated IDs hash, actual input/output tokens and elapsed
cost. Seal the raw answer file **before** comparing any output with the
programmatic target token. A failed attempt remains missing/unknown and makes
the experiment incomplete.

Metrics are deliberately **answer-only**, not semantic citation proof:
exact single-token output, bare target-token mention, exact required refusal,
invalid label-only completion, unsupported token generation, and paired
labeled versus unlabeled differences for identical source excerpts.
Any citation supplied later by a proof-carrying wrapper is a **system**
citation, never a newly learned Reader citation.

The *unlabeled* competing-token arm is the predeclared primary; it must yield
at least 15/20 **exact answer-only** outputs while the unlabeled irrelevant-
token arm and the empty-evidence arm each yield at least 18/20 exact refusals,
merely to merit **independent confirmation**. The study is an
explicitly exposed 20-question synthetic development diagnostic. It is
not a human semantic sufficiency review, a calibrated confidence estimate,
compute-matched NDU Cell advantage or production qualification.

Even a passing answer-only floor cannot substitute for correct source
citations, robust refusal, future unseen paraphrases or a stronger frozen
Reader baseline.

## Reproduce

From a pinned checkout, with the completed 140-call archive and the
unchanged frozen model staged:

```sh
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  python scripts/memory_cell/system2_onehop_label_ablation.py \
  /tmp/cardinality-original.zip /tmp/memory-inputs/reader \
  /new/answer-only-label-ablation --development
```

For a **zero-model** archive audit:

```sh
python scripts/memory_cell/system2_onehop_label_ablation.py \
  /tmp/cardinality-original.zip /tmp/unused /tmp/unused-output --audit-only
```

The isolated workflow runs full MemoryCell regressions, Ruff, source/identity
preflight, 140 frozen inference calls, post-seal scoring and SHA256 artifact
inventory without disabling inherited CI gates. New hosted CI results must
not be presumed before completion.

`production_accepted=false`, `reader_adequacy_established=false`,
`no_new_encoder_or_head_training=true`,
`independent_natural_task_evidence=false`.
