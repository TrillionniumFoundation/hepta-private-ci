# MEM14 preregistration: a new generated-source cohort

## Purpose and separation

MEM14 is an independent follow-up after MEM12 exposed a measurement problem:
the frozen actor asked for a single color, while some generated answers expressed
the fact in a sentence. The old MEM12 endpoint and scores are not changed. Its
v1 plans always use the original parser and eight-source, two-record limits.
This source introduces no retrospective relabeling API or command-line override
for existing plans.

The new primary endpoint is **factual answer correctness under a fixed grammar**.
Accepting one sentence does not establish compliance with the actor's one-color
instruction. MEM14 reports v1 format acceptance and v1 correctness alongside the
primary v2 score as descriptive columns. They cannot replace the primary endpoint
after results are observed. Differences between MEM12 and MEM14 are not a causal
estimate of changing the parser or retrieval count: the new design changes both
and uses new random sources.

The intended real cohort has 32 fresh independent generated sources, three
arbitrary parcel-to-color facts per source, one unchanged task template and the
same ten arms. There are **32 paired sources and 320 planned generation rows**,
not 320 independent memory-benefit episodes. The source, actor bytes, model
profile, parser, case roster, limits and randomized arm ordering must be frozen
before any model output from this cohort is observed.

## Exact public v2 grammar

Only leading/trailing whitespace removal and Unicode case-folding are applied,
as in v1. The entire resulting output must be one of:

- One word from `red`, `orange`, `yellow`, `green`, `blue`, `purple`, `pink`, `white`.
- Bare `unknown`; this is valid format, but no truth label is `unknown`.
- Exactly `the courier must use a <color> badge.`, where `<color>` is one of the
  eight colors. Literal single spaces, `a`, and the final period are required.

There is no substring search, arbitrary prose parsing, alternative article,
optional explanation or second color. `Answer: blue`, `blue.`, a sentence with
`the blue badge`, and a sentence without its period are rejected by v2. V1 keeps
its existing optional `Answer:` prefix and punctuation behavior. The scorer
receives only output text and the frozen version, never the expected label.

## Fixed new plan and execution

```bash
PYTHONPATH=scripts python3 -m ndu_real_runtime.run_episodic_diagnostic \
  --prepare /absolute/new-mem14-cohort \
  --profile /absolute/unchanged-mem12-profile.json \
  --cohort-id mem14-new-fixed-cohort \
  --selector-version v2 --sources 32 --retrieval-records 1
```

This creates `hepta.mem14.controlled-diagnostic.v1`, with explicit selector
version, source count, analysis contract, source hashes and plan hash. Default
preparation remains v1 / 8 sources / 2 records and creates the legacy schema.
Preparation choices are not accepted on `--run`, `--report`, or `--writer`.
Loads reject altered case counts, duplicate source/arm rosters, changed parser
identity, unsupported limits, or a changed inference contract even if an editor
has recomputed `PLAN_PIN.json`.

The model, actor bytes, input/output caps, A writer, isolation, interventions and
evidence checks are unchanged. Every arm uses a **common maximum of one record**:
BM25, exact-KV, finite-context ICL and uniform replay all receive the same cap.
`off`, `retention_off`, `retrieval_off` and `delivery_off` retain their existing
separate meanings. Withholding delivery is not full memory-off. BM25-on is the
BM25 baseline itself.

Other common limits stay at 2,048 context bytes, 1,024 input tokens, 32 output
tokens and 60 seconds per model subprocess. Equal caps do not mean equal actual
token, retrieval, setup or runtime costs. Keep all observed costs and their
missingness, and charge the common A ingestion cost once. The outer supervisor
deadline for **320 rows** must be explicitly frozen by the execution owner before
launch; it must not silently inherit the old 80-row outer budget.

Use a new directory and operation key for this new registered study. Each arm
retains a fixed request ID; uncertain operations and existing arm directories are
not retried or replaced. New random source facts must not reuse MEM12 cases.
The execution owner alone schedules the real campaign after freezing source and
plan. This implementation's regression controls use synthetic provider receipts.

## Preregistered within-cohort analysis

The primary contrast is **on_bm25 minus off**. For source i, let D_i be the paired
binary correctness difference, bounded in [-1,1]. With all 32 paired outcomes
observed, the one-sided 95% Hoeffding lower bound is:

`max(-1, mean(D) - sqrt(2 * ln(20) / 32))`.

All nine on-versus-control contrasts remain visible. Their simultaneous
one-sided 95% Bonferroni-Hoeffding lower bounds are:

`max(-1, mean(D) - sqrt(2 * ln(9 / 0.05) / 32))`.

These statements assume the new source pairs are independent draws from the
declared generated-task population under the fixed actor/model/template. They do
not imply natural-task generalization. No bootstrap or resampling interval is
used. The confidence bounds are distinct from the report's existing descriptive
missing-label identification bounds.

If an outcome is missing, each pair first receives its conservative feasible
difference interval. The confidence lower bound uses the mean of the lower ends
over **all 32 planned sources** and the same fixed confidence radius. The exact
paired mean is reported as unavailable until identified. No missing or failed
row is deleted; an observed malformed answer is scored incorrect. Bare UNKNOWN
is likewise incorrect against any of the eight color truths.

The v1 descriptive score and format counts use the same verified original model
outputs, without changing the registered v2 primary endpoint. All nine contrasts,
complete denominators, original request/model-input bytes, A custody, isolation,
provider receipts and actual costs remain reportable even for a negative result.

## Gates that remain open

This still uses a Python research SQLite owner and deterministic A ingestion.
The original production owner, natural-source generalization, native model path,
authenticated observer and parameter consolidation remain separate gates. A
positive controlled-task bound does not authorize training, production adoption
or a weight-consolidation claim. `scientific_acceptance` remains `HOLD` for those
broader gates, while the separately named controlled-task bounds remain visible.

Software controls:

```bash
PYTHONPATH=scripts python3 -m unittest \
  ndu_real_runtime.test_run_episodic_diagnostic \
  ndu_real_runtime.test_episodic_diagnostic_protocol -v
```
