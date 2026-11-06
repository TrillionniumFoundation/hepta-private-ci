# Frozen-model finite-action development: correct tool execution, failed baseline gate

This new development procedure establishes a narrow actual path from a frozen
pretrained language model through an allowed operation and a real SQLite/source
worker to an exactly correct answer. It also gives a clear negative comparison:
the same-information literal router is correct on all eight tasks and is much
faster. The NDU scaling gate remains **HOLD**.

This is a different, deliberately easier task contract. It does not recover the
earlier eight free-form SQL/source questions, rewrite their 48 failed episodes,
or provide an independent scientific confirmation. The original three procedures
and all 54 historical model responses remain unchanged.

## What changed before any forward

The same Qwen/Qwen2.5-0.5B-Instruct revision
`7ae557604adf67be50417f59c2c2f167def9a775` is used, with no parameter updates and
no additional model selection. Ten public operations cover five table counts
and five exact function-declaration lookups. Tasks explicitly name their desired
table/function. All ten operations are shown to the model for every task.

A single forward computes the next-token logits for the ten single-token action
labels. The highest-scoring legal label is selected. This is finite-action
likelihood selection, not unconstrained text generation, JSON repair, training,
or an NDU identification algorithm. The worker executes the exact selected
operation and delivers its typed value unchanged. No second model rewrites the
observation. The parent alone computes the evaluation reference.

The **literal_router** control receives the same question, catalog and actual
tools. It matches the single named table/function. It has no gold answers,
private expected values or outcome-based fallback. **stop** makes no call and
receives zero quality. These three arms were frozen together and run exactly once
for all eight tasks, rotating execution order. No prompt or option changes,
retries, exclusions, model search or post-outcome rescoring occurred.

`freeze.json` binds the complete runner, protocol and input files before the
first forward. The local freeze time is 2026-11-06T16:51:57.097902Z. It was **not**
a remote publication or external preregistration. The run completed at
2026-11-06T16:54:09.131265Z. Tasks are newly authored development questions using
the same two previously disclosed source clusters, Chinook and CPython. Easy
named-operation tasks are not an untouched benchmark.

## All observed outcomes

| Arm | Episodes | Completed typed transport | Task-type-compatible answers | Exactly correct | Actual model forwards | Actual tools | Inclusive episode wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frozen model selector | 8 | 8 | 4 | 3 | 8 | 8 | 121.977763 | 173.673060 |
| Literal router | 8 | 8 | 8 | 8 | 0 | 8 | 0.736405 | 0.678934 |
| Stop | 8 | 0 | 0 | 0 | 0 | 0 | 0.000074 | 0 |

The distinction between transport and task compatibility matters. Four model
selections chose the wrong operation family and therefore returned the wrong
JSON scalar type. Another selected Artist instead of Album. All five remain
zero-quality outcomes. Only the Artist count, Genre count and linear_regression
signature are exactly correct.

| Requested operation | Model label | Observed operation | Exact result |
| --- | --- | --- | --- |
| Artist count | A | Artist count | Correct |
| Album count | A | Artist count | Wrong |
| Genre count | C | Genre count | Correct |
| Invoice count | I | correlation signature | Wrong type |
| mean signature | A | Artist count | Wrong type |
| median signature | C | Genre count | Wrong type |
| quantiles signature | C | Genre count | Wrong type |
| linear_regression signature | J | linear_regression signature | Correct |

All 24 episodes completed within their declared 70-second deadlines. Model
subprocesses have 60-second supervision; tool subprocesses have 5 seconds.
Every dispatched call has a durable pre-launch intent, one terminal record,
original stdout/stderr and a hash. All 24 calls succeeded at transport level;
the 48 corresponding ledger entries reconcile. There are no hidden retries.

The total run takes 122.771143 wall seconds and 174.351994 child CPU seconds.
Model inputs total 1,110 tokens. Each forward selects one legal action token;
there are eight such decisions, not eight new free-form generated responses.
Forward computation itself consumes 11.569322 seconds. Weight verification,
loading, before/after parameter hashing and process teardown are all inside the
model request and episode clocks. Nested times must not be added again.

## Why this fails the benefit gate

On every observed task the literal router has at least as much quality, the same
number of tool calls and strictly less measured elapsed time. Thus, for the
explicit descriptive score `quality - lambda * elapsed_seconds - k * tool_calls`,
it strictly dominates this model selector whenever `lambda > 0` and the same
per-call charge `k` applies. At zero delay price it is better on five tasks and
ties on three. This is a finite realized comparison, not a population confidence
bound. Heterogeneous provider fees or actual host invoices are not available;
no monetary-net-benefit claim is made.

The model arm's cold load overhead is substantial. Warm serving could reduce
that cost, but cannot turn 3/8 observed correctness into a quality advantage over
8/8. The evidence does not rule out another prospectively defined controller;
it rejects advancement of this one. Adding a larger experiment or training run
is not justified by these outcomes.

## Frozen identity and verification

Every actual forward records the same before/after parameter fingerprint:

`815634c0b4c921ad07b4a32437ff872342e745b15a386f6ca8f5a2d4974e0c13`

This matches the previous Qwen execution. All model files are checked against
the inherited publisher SHA-256/Git blob manifest. Inference uses only local
safetensors, frozen parameters, float32, two CPU threads and eager attention.
The reused runtime reports Python 3.12.14, torch 2.15.0+cpu and transformers
5.22.1. Runtime version reports and hashes do not amount to independent host
attestation.

`audit.py` separately reconstructs the complete schedule, receipts, raw output
hashes, action argmax, public-only request payloads, model identity, parameter
invariance, expected answers, deadline completion and paired descriptive
comparisons. **173 checks pass.** It performs zero additional model forwards and
zero task-tool calls; evaluation source/database reads are disclosed. This audit
was written by the same implementation author and is not an independent or
external review. The parent/coordinator can review the raw records separately.

## Reproduction

Use a fresh output directory. The frozen local model files and corresponding
runtime are required. An execution cannot overwrite earlier outputs.

```bash
python study.py run \
  --runtime /path/to/pinned/runtime/bin/python \
  --model-dir /path/to/pinned/Qwen-model \
  --output /path/to/new-run
python audit.py --results /path/to/new-run --output /path/to/new-audit.json
```

Do not regenerate `freeze.json` to disguise a changed source; a different method
requires a separately declared procedure. `results/run-01/result.json` and every
raw per-request/per-episode file are included. The old study files and model
weights were only read, never edited.

## Remaining scientific gates

- The generic interface can now produce actual correct tool-assisted answers in
  this narrow class. Task-type compatibility and controller correctness remain
  poor for the current frozen model selector.
- No candidate NDU policy or paid identification mechanism was tested here.
- Two familiar source clusters and easy named operations do not establish
  independent generalization.
- Full preparation, engineering, hardware and monetary lifecycle costs remain
  unpriced. Recorded CPU/wall measurements are resource evidence only.
- The complete required direct/fixed-budget/myopic/planner comparison and
  simultaneous independent net-gain confirmation have not run. Since the cheap
  public-information control already dominates this candidate, this development
  result does not authorize advancing it to that expensive confirmation.

Sources and prior negative provenance are in `inputs/sources.json`,
`inputs/model_manifest.json`, `protocol.json` and the upstream status checkpoint
`7bf0472af73eb9fbd92dff44cb15cc9526cb5d80` in
TrillionniumFoundation/hepta-private-ci.
