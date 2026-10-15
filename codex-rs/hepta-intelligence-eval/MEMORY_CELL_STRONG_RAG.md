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
nine arms on every original eight-case evaluation question:

| Arm | What it isolates |
| --- | --- |
| `selected_k` | Actual-reader-calibrated, annotation-blind top-k prefix |
| `hybrid_k4` | Historical fixed RAG top-four, newly generated in this run |
| `hybrid_k6` | More retrieved evidence and possible extra distractors |
| `hybrid_k4_reversed` | Same four exact bytes, reverse presentation order |
| `single_hop` | Only the first entity/attribute edge; no subsequent traversal or supersedes pruning |
| `entity_time` | Full entity/attribute path traversal, without supersedes pruning |
| `organized` | Full path traversal plus explicit supersedes correction pruning |
| `program_support` | Diagnostic upper bound, NOT a human-certified oracle |
| `empty` | Zero-evidence control under the same reader |

All arms use the same original retrieved pool, fixed reader, source bytes,
question, permitted test-program worker, prompt and generation configuration.
The no-evidence and program-support arms are included to make reader failures
interpretable; oracle-derived labels **never** choose the RAG k or its ranking.
No source bytes are truncated. A context overflow is a retained failed attempt,
not a silently removed hard example. Final answer labels are parsed only after
all nine-arm raw outputs are durable; `preflight` may hash the file for identity
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
choice still controls the evaluation and is never re-tuned from its answers.

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

The broad format check remains in the separate PR workflow
`.github/workflows/hepta-memory-review-format-final.yml`; it is no longer
duplicated inside the exact-source reader experiment. The standalone PR
format check and `blocking-ci` continue to report independently and must
be assessed before a merge or production decision. Removing duplicate
research-job work does not waive either PR-wide quality obligation.
The scheduling contract is
regression-tested by `test_strong_rag_workflow_scheduling.py`.

Previously queued PR-triggered runs are not retroactively cancelled, renamed,
or counted as successful push-triggered experiments. Running code checks alone
establishes no Qwen task accuracy, parameter advantage, semantic judgement,
future observation, or production acceptance. Only a completed exact-source
40-answer calibration, 72-answer evaluation and separate artifact replay can
supply the next bounded result.

## Actual single-hop versus multi-hop versus correction controls

The original `EventProjection.select` implementation iterates through
**all attributes in `lookup.path` in BOTH `entity_time` and `organized`**.
The only algorithmic difference is that `organized` removes explicitly
superseded events at each path step. Consequently, the original
`organized_minus_entity_time` comparison is a *correction/conflict pruning*
contrast, NOT evidence of extra relationship traversal.

A new `single_hop` test arm selects only the first attribute using the
same source `EventProjection` with `mode=entity_time`, the same retrieved
candidate pool, valid-time cut and 4-source limit. It does not read target
answers or program-support labels. Before loading Qwen, the evaluation
process independently re-derives the historical full-path entity/time and
organized source lists from the original frozen public question declarations,
and refuses any drift. It then seals `single-hop-control.json` **before**
the answer journal. The read-only job independently rebuilds the exact same
manifest from the pinned original inputs and rejects altered bytes/decisions.

In the frozen eight-task authored population, four composition/procedure
questions gain one source by advancing from single-hop to full path;
two correction questions differ between unpruned and explicitly corrected
full path; the two new-fact questions need neither. Those are **source-set
changes**, not reader success metrics. The actual new census is
**8 x 5 = 40** calibration generations and **8 x 9 = 72** development
test generations. The previous 56- and 64-answer designs remain historical
plans; neither is relabelled as completed inference.

The preregistered task comparisons now distinguish
`entity_time_minus_single_hop` (relation traversal) from
`organized_minus_entity_time` (explicit correction pruning), alongside
strong RAG and same-prompt controls. All selected snippets retain original
source content and independent citation/replay checks. These are public
authored development tasks, not independent future observations, semantic
sufficiency certificates, statistically reliable superiority or production
qualification.

## Exact-commit concurrency correction (2026-10-11)

The preceding per-branch Actions concurrency group with
`cancel-in-progress: false` serialized *different* frozen research revisions.
The earlier push source `b8b39191` remained `queued`, while the later
eight-arm source `33e3aa13` stayed `pending` without jobs. This is a
workflow scheduling dependency, not a failed Qwen inference.

The group is now keyed by exact `github.sha` instead of `github.ref`.
Each immutable generating source gets a distinct scheduling identity,
while attempts of the same source remain grouped. Automatic cancellation
remains disabled so that a running model is not interrupted before its
original answers are journaled. The branch/path trigger, scoped preflight,
reader controls, independent replay and broad PR gates are unchanged.

This removes the workflow's own cross-SHA scheduling dependency; it cannot
guarantee GitHub runner capacity or completion. Previously queued runs are
not relabelled or treated as the latest model result. Production admission
and parameter memory advantage remain unestablished.

## Formal citation-chain fidelity as a separate research axis (2026-10-11)

The original Qwen frozen-reader archive had **8/8 strict answers** in each of
`entity_time` and `organized`, but only **4/8** of those answers cited
all program-declared sources; the other four two-hop composition/procedure
answers omitted the first-hop citation. SmolLM2's three correct organized
answers cited none of their sources. Those counts are from previously generated,
eight-case authored development outputs, **not** independent semantic
citation precision, new model inference or generalization evidence.

The new nine-arm evaluation now reuses the pinned
`historical_event_citation_chain.audit_evaluation` rule on its **own 72
original answers**, after they have all been durably journaled and scored.
Every planned attempt remains in the denominator. The report keeps these
three outcomes distinct: strict answer correctness, full citation of the
author-program-declared support IDs, and whether **only the actually cited
original event JSON** forms the public question's specified path to the
parsed answer under the declared revision cut. A formally connected path is
not a human-certified entailment judgement or a necessity/sufficiency proof.

The separate `independent-replay` job retrieves original pinned source
questions and labels, reexecutes the bounded worker, recalculates all
per-arm citation-chain totals and case-level details from the original
unmodified saved answers and exact delivered evidence, and rejects a
changed report or mismatch with the strict task totals. It cannot modify
answers or sign for an independent reviewer. The original citation
entailment precision remains `null`, and
`independent_semantic_adjudication=false` and
`production_accepted=false` remain explicit.

The model-free historical audit's 10 existing tests and the new six nine-arm
bridge regressions run before real Qwen staging; both are rerun by the
separate replay job. They do not replace the frozen-model experiment or
any PR-wide quality checks.

## Research-workflow result isolation (2026-10-11)

The hosted source `02c12b4a` passed `experiment-format`, but its duplicate
research `format` job failed on **36 unrelated changed MemoryCell Python files**.
The separate PR-wide `MemoryCell reviewed source formatting` check remains.
Because the reader/replay job did not depend on that duplicate, the model
could run, but the scientific workflow would be marked failed even if
the exact-source model results and independent replay succeeded.

The frozen-reader workflow therefore keeps only its source-scoped Ruff and
model-free regression prerequisite, actual calibrated Qwen generation,
and the read-only independent replayer. It does not issue merge approvals.
Full-repository formatting and required `blocking-ci` remain independent.
The previous completed run is not retroactively reclassified, and currently
queued reader jobs remain source-pinned without synthetic model results.

Research success still requires completed **40 calibration plus 72 evaluation**
generations, immutable source artifact and separately checked citation/score
replay. A passing research workflow does not itself qualify production.

## Intermediate calibration evidence checkpoint

The hosted CPU reader runs forty Qwen calibration calls before the distinct
nine-arm development evaluation. The original workflow only uploaded the
final artifact after both stages. If evaluation subsequently failed, the
expensive calibration evidence lacked an independently downloadable stage
record. The new checkpoint step runs **between calibration and evaluation**
and also runs on a non-successful calibration step (if that step was started).

`memory-strong-rag-calibration-checkpoint` contains the generating commit
(`tested-commit.txt`), any completed `prep` and `calibration` directories,
reader inventory/stage and resource logs when available, plus a complete
`SHA256SUMS` file census. Model weights and evaluation labels are not copied.
Every entry is from the exact checked-out `github.sha`; no score is repaired
or replaced. A partially written calibration journal remains a **partial
failure artifact**, never an eligible selected-k policy.

The original later `memory-strong-rag-calibrated-reader` artifact and
separate `independent-replay` still require successful generation and
complete frozen-source verification. The checkpoint alone is not an
independent model effect, semantic citation judgement, or production
acceptance. It does not rescue files from a runner killed by its overall
job timeout if GitHub does not execute subsequent `always()` steps.

## Host runtime evidence and bounded-reader fail-fast (2026-10-11)

The prior source-pinned [run 38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963)
reached actual Qwen2.5-3B BF16 inference but was cancelled before completing
calibration. Its 26-file diagnostic artifact `11696974258` has ZIP SHA-256
`129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`.
The complete artifact manifest is verified. Original `calibration/raw-answers.jsonl`
contains **four succeeded calls, all for one question**, with measured
input-token / model-seconds pairs (504, 923.31), (787, 1457.51),
(1076, 2045.60), and (1370, 2641.52). No selected k, held-out result
or independent replay was produced. These four raw answers must not be
relabelled as a complete 40-call calibration.

The archived successful Qwen reference run `38063870516` used the same
research model revision, BF16/eager reference reader and OMP/MKL two-thread
environment, yet generated 48 answers in the historical reader stage.
The very large observed throughput difference is an **unresolved host
performance/CPU instruction-set issue**, not evidence about memory quality.

New runs now store `calibration/runtime-preflight.json` and
`evaluation/runtime-preflight.json` using the existing bounded host
snapshot facility. Each is SHA-256 bound to its phase's immutable `run.json`
and must be independently checked against the final artifact manifest.
The records include Torch intra/inter-op threads, allowlisted CI runner
metadata, CPU features reported by `lscpu`, CPU affinity and host memory.
They contain no model weights, user data or credentials. The frozen
reader parameters, source bytes, prompts and answer scoring are unchanged.

To stop repeatedly burning a 360-minute model slot on a host demonstrably
too slow for a **40 + 72** call experiment, `_journal_answers` now fsyncs
each exact raw answer before applying a **180-second observed per-call
research feasibility bound**. A slower completed call raises an explicit
resource infeasibility error, preserving that answer, the failed run and
the host evidence, and refusing to issue a frozen k or model-gain claim.
This is a **research resource gate, not a task metric, quality failure,
hardware guarantee or production SLO**; it cannot prove an adequate runner
exists. An accepted full census still requires 40 calibrated and 72
matched Qwen generations with an independent read-only replay, followed
by genuinely fresh independent source families for any generalization
or production conclusion.
