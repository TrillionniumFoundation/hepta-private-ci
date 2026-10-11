# MemoryCell: calibrated strong RAG before any new parameter adaptation

This is an opt-in **development diagnostic**, not production adoption, a new
reader, an independent future-source sample, or a semantic-citation certificate.
It reuses the existing frozen event inputs, persistent hybrid BM25+dense index,
original full source bytes, `EventPresentationReader`, fixed Qwen2.5-3B research
revision, evidence bundle, 2,048 input-token ceiling, 64 generated-token
ceiling, deterministic decoding and constrained program worker. It neither
trains reader/Cell weights nor changes DecisionCell/HNMF/CNS owners.

## Why this experiment comes next

The historical Qwen event-reader run on `59f9eadd` (workflow 38063870516,
artifact `11674741321`, ZIP SHA-256
`831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`)
contains 48 actual answers. The pinned eight-task strict-success vector was:

| Condition | Strict task successes |
| --- | ---: |
| empty | 0/8 |
| hybrid top-four | 3/8 |
| entity/time | 8/8 |
| organized | 8/8 |
| program-bound support | 8/8 |
| support with one stated prerequisite omitted | 4/8 |

The **hybrid top-four already covered all annotated source IDs in 8/8**. In
the frozen original candidate order, support coverage is top-1 3/8, top-2
4/8, top-3 7/8, top-4 8/8 and top-6 8/8. These are *offline support counts*,
not reader accuracy. The previous 0/8 omitted-premise claim is false for the
pinned Qwen archived file: four answers survived the omission. None of those
program-designated support groups is independently human certified sufficient
or individually necessary.

The plausible alternative explanation for the organizer's result is that it
removed reader-distracting but correctly retrieved evidence. A tuned, otherwise
unchanged RAG top-k reader is the necessary control before claiming memory
organization, learning or parameter adaptation superiority.

## Frozen experiment contract

The historical source is archive `11669174727`, ZIP SHA-256
`23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
It contains 108 source events in 16 authored scopes, eight explicitly named
calibration tasks and eight separately designated evaluation tasks. The index,
encoder catalogue, source-view and original plan SHA-256
`9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`
are pinned. Index retrieval is replayed at the already selected hybrid lexical
weight (0.5). The original eight test candidate lists, timestamps, source cuts
and query bytes must reproduce **exactly**; otherwise execution fails closed.

**Phase 1 — precompute and isolate calibration.** Prepare outputs only the
original calibration scopes, raw source documents, ranked candidates, and
calibration-only labels. The calibration runner is invoked without the original
test plan, test questions or test labels. It performs no index/parameter fitting.
It cannot use test answer annotations to choose top-k. Source prep does
inspect the already public original test plan to verify retrieval reproduction;
therefore these are previously exposed development questions, not a prospective
blinded population.

**Phase 2 — actual reader calibration.** For all eight calibration questions,
the SAME frozen reader executes `k = {1, 2, 3, 4, 6}`, with original source text,
matching prompt construction, shared decoder and complete-source token bound.
All 40 actual responses or errors are written to `raw-answers.jsonl` and fsynced
*before* calibration-only answers are opened for scoring. The criterion is
strict task success (including actual execution of constrained procedure
choices), then fewer observed total prompt tokens, then smaller k. Any missing
or failed calibration arm leaves the selection **unqualified** and prevents
creation of a frozen k. Both reading and calibration cost count; no hidden
model-learning benefit is credited.

**Phase 3 — distinct-process evaluation.** With frozen `frozen-policy.json`
(exact model identity, source/plan pins and earlier generation hashes), perform
eight arms on every original eight-case evaluation question:

| Arm | What it isolates |
| --- | --- |
| `selected_k` | Actual-reader-calibrated, annotation-blind top-k prefix |
| `hybrid_k4` | Historical fixed RAG top-four, newly generated in this run |
| `hybrid_k6` | More retrieved evidence and possible extra distractors |
| `hybrid_k4_reversed` | Same four exact bytes, reverse presentation order |
| `entity_time` | Entity/revision filtering without relation completion |
| `organized` | Existing deterministic entity/revision/bridge selection |
| `program_support` | Diagnostic upper bound, NOT a human-certified oracle |
| `empty` | Zero-evidence control under the same reader |

All arms use the same original retrieved pool, fixed reader, source bytes,
question, permitted test-program worker, prompt and generation configuration.
The no-evidence and program-support arms are included to make reader failures
interpretable; oracle-derived labels **never** choose the RAG k or its ranking.
No source bytes are truncated. A context overflow is a retained failed attempt,
not a silently removed hard example. Final answer labels are parsed only after
all eight-arm raw outputs are durable; `preflight` may hash the file for identity
beforehand but does not interpret its target contents. An answer without the
specified narrow identifier grammar is a strict failure. Program answers are
checked by actual bounded worker execution. No generated citation is repaired.

Reports preserve every case/arm/status, emitted source labels, native citation
requests, per-kind strict success, token and inference costs, and paired
win/loss/tie/unknown counts. Missing pairs widen *logical bounds*, which are
**not** statistical confidence intervals. A larger reader is a reader-capacity
axis, never a learned MemoryCell gain. The earlier eight-case answer exposure,
tiny authored task count, same-family dependence, possible alternative valid
support, and narrow program grammar forbid any prospective generalization claim.

## Execution and source of truth

The read-only `.github/workflows/hepta-memory-strong-rag.yml` triggers on
branch-scoped strong-RAG source/test/workflow pushes. It checks repository formatting,
restores the exact audited archive and Python environment, runs the entire
MemoryCell Python regression set, stages the publisher-pinned encoder and
research-only Qwen2.5-3B model, then executes in separate Python processes:

```sh
python3 scripts/memory_cell/strong_rag_trial.py prepare \
  INPUTS/observations INPUTS/plan ENCODER PREP --plan-sha PLAN_SHA
python3 scripts/memory_cell/strong_rag_trial.py calibrate \
  PREP MODEL CALIBRATION --prep-sha PREP_SHA --stage-sha STAGE_SHA
python3 scripts/memory_cell/strong_rag_trial.py evaluate \
  INPUTS/plan INPUTS/observations MODEL CALIBRATION RESULTS \
  --plan-sha PLAN_SHA --stage-sha STAGE_SHA --policy-sha POLICY_SHA
```

Artifacts retain exact producing commit, pinned inputs, all raw responses,
failed attempts, scores, frozen policy, costs, source files, environment and
SHA256SUMS. **A successful workflow is a completed evaluation, not proof of
superiority or production qualification.** Do not borrow a prior commit's CI
result for a newer head, and do not relabel historical model responses as newly
generated. This Qwen revision is used for non-commercial research under its
published license; model weights are not uploaded to CI artifacts.

No maintained read-time production cost or distributed recovery/withdrawal
cost is measured here. Original evidence and index bytes remain counted. Total
production lifecycle cost, independent sufficient-context reviews, actual
future collection, >=99% independent citation-entailment precision, real task
breadth and production cutover/rollback all remain **unknown/unaccepted**.
Do **not** train or adopt an experience-specific parametric module based only
on this authored baseline; require reproducible advantage over the best
eligible, same-tools organized and tuned-RAG readers on fresh sources first.

## Separate read-only receipt replay (next validation gate)

The `independent-replay` workflow job runs **after** the actual model-generation
job succeeds, in a separate checkout/process. It does not load the Qwen weights,
train a parameter, emit a new language-model answer, sign on behalf of a human,
or rewrite the original artifact. The verifier also re-fetches the immutable
historical source ZIP and checks the ZIP digest and all inner `SHA256SUMS` pins.

`strong_rag_receipt.py` verifies the downloaded model artifact's **entire** file
census, not only its success report. It binds the emitting commit, frozen policy,
reader inventory and source partitions; confirms calibration never contained
an evaluation source scope; and checks every saved selected source against its
original event JSON, UTF-8 excerpt, correction/valid-time representation,
delivered order, identity and native citation request. The request is rebuilt
using the existing unsigned citation capture protocol and must match the saved
record exactly. Reader profiles, input/output ceilings, untrained base and raw
answer non-postprocessing are enforced per attempt.

The scorer is replayed from the original **unmodified** raw JSONL answers after
checking the full question-by-arm census. Every bounded procedure worker is
re-executed and compared on its request, stdout, stderr and exit code; elapsed
time and process observation timestamps are measured anew, not falsely equated
with their historical values. The eight calibration questions must reproduce
the exact selected `k` using the frozen success-first selection rule, original
prompt-token totals, and the same source/model SHA pins. All evaluation arm
counts, paired win/loss/unknown bounds and frozen reader parameters are then
recomputed and compared to the persisted report. When identical source lists
are shown to the same question, their recorded prompt-token IDs must agree.

This is a **read-only reproducibility and causal bookkeeping gate**, not an
independent semantic citation judgment, independently sampled held-out source
family, deployment observation or evidence that MemoryCell learned useful
parameters. Earlier public author-created cases remain exposed development
cases. The tool continues to emit `production_accepted=false`,
`independent_semantic_judge=false` and `statistical_superiority=false`.

Run when the completed exact source artifact exists:

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/strong_rag_receipt.py \
  ARTIFACT_DIRECTORY PINNED_ORIGINAL_INPUT_DIRECTORY \
  --generating-commit EXACT_SHA \
  --output NEW_RECEIPT.json
```

A later committed verifier cannot retroactively change the identity or scoring
of an earlier generating commit. Failure of the separate replay **blocks any
positive research claim**; a successful replay establishes faithful execution
and bookkeeping only, and must not be relabeled as production qualification.

## Frozen-reader repeatability on exactly matched evidence

When two arms deliver the same **ordered original evidence** to the same
frozen reader, the source/prompt identity must match, including full rendered
input token digest, complete delivered excerpts, reader profile and token
budget. These comparisons are now written to `same_prompt_consistency` in the
actual evaluation report and recomputed by the separate read-only replay.
An output/decoded-answer/task-result disagreement is retained as instability,
not counted as a memory gain; missing executions stay in the planned paired
denominator. There is no promotion from this diagnostic to semantic or
statistical acceptance, even when all observed repeats agree.

A model-free audit of the already executed Qwen 48-answer event-reader archive
(`11674741321`, source `59f9eadd`) found **24 matched ordered-evidence
pairs and zero disagreements** in answer bytes, output-token digests or task
success. This is historical generated evidence checked read-only, not new
inference or independent future sampling.


## Leave-one-calibration-question-out sensitivity (no additional inference)

Five top-k choices on only eight exposed authored calibration tasks can select
an idiosyncratic winner. After all 40 original calibration answers have been
fsynced and scored, `strong_rag_stability.py` separately omits each of the
eight calibration questions and **reselects k using only the other seven**.
For the omitted question, the frozen answers for this selected k are contrasted
against fixed k=4. All eight folds, their chosen k values, win/loss/tie/missing
counts and worst-case missing-outcome bounds are recorded.

This does **not** produce eight independent experiments: folds share most
training questions, source stories are authored, and none of the eight final
test labels is involved. A stable choice does not establish generalization,
a statistical confidence bound or MemoryCell's learned benefit; instability
is evidence to distrust this tiny calibration. The predeclared full-eight-case
choice still controls the evaluation and is never retuned from its answers.

The actual calibration report retains the full sensitivity record. The
frozen policy contains its digest, while the separate read-only replay
recomputes the eight omissions from sealed raw answers and rejects a changed,
missing or inconsistent stability receipt. The independent replay job also
runs the new leakage, failure-denominator and digest-integration tests.

This is a **calibration-quality diagnostic only**. Independent source families,
real future tasks, semantic source review, and production qualification remain
unmet; `production_accepted=false`.

## Branch-scoped Actions scheduling (2026-10-11)

The research workflow now runs on a **push of relevant strong-RAG code** to
`codex/memory-cell-evidence-20261008`, not a `pull_request` `synchronize`.
Pull-request path filters operate on the overall PR file set. In this large
ongoing PR, unrelated concurrent Stem commits repeatedly queued the frozen
reader job. A branch-scoped push path filter does not match these unrelated
changes. The workflow itself and this document remain included in the trigger.

Calibration, evaluation, saved evidence and separate replay now check out the
same exact `github.sha` of the triggering push. Research concurrency is
scoped to the branch, so pending duplicate research work is bounded without
automatically cancelling a reader that is already executing. The source-only
`experiment-format` gate still runs before actual Qwen inference.

The broad `format` job is preserved and checks the current default-branch
comparison. It is separately observable but is not a reader prerequisite,
because unrelated files can fail it. The repository's independent required
`blocking-ci` and other PR-wide gates are unchanged; their failure still
blocks merge and production qualification. The scheduling contract is
regression-tested by `test_strong_rag_workflow_scheduling.py`.

Previously queued PR-triggered runs are not retroactively cancelled, renamed,
or counted as successful push-triggered experiments. Running code checks alone
establishes no Qwen task accuracy, parameter advantage, semantic judgement,
future observation, or production acceptance. Only a completed exact-source
40-answer calibration, 56-answer evaluation and separate artifact replay can
supply the next bounded result.

## Simple filtering versus relation-completion control

The pinned historical Qwen reader had strict task successes of **8/8** for
`entity_time` and **8/8** for `organized`, with the same ordered original
evidence selected in 6/8 cases. For SmolLM2 the corresponding success counts
were 2/8 and 3/8. These are authored previously exposed cases, not
independently reviewed source families or future-window samples.

To isolate the actual incremental effect of relation completion, the fixed
`entity_time` arm now joins the SAME pretrained reader/prompt/decoder/tool
controls in the new model evaluation. It uses the original selected evidence
IDs from the frozen plan, never original test gold answers for selection.
All original evidence bytes remain unchanged. This changes the test-stage
census from **8 x 7 = 56** to **8 x 8 = 64** real answer executions, while
calibration remains **8 x 5 = 40** model calls. This addition supersedes the
prior 56-call proposal; incomplete historical runs are not rewritten.

The independent artifact verifier repeats every original-source, prompt,
citation, task-success and procedure check for this arm, and recomputes
`entity_time_minus_hybrid4` and `organized_minus_entity_time` contrasts.
Matching source selections must preserve prompt identity; any answer drift
counts as repeatability instability, not a graph benefit. A nominal task
improvement on eight authored cases is still neither statistically independent
superiority nor production admission.
