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
seven arms on every original eight-case evaluation question:

| Arm | What it isolates |
| --- | --- |
| `selected_k` | Actual-reader-calibrated, annotation-blind top-k prefix |
| `hybrid_k4` | Historical fixed RAG top-four, newly generated in this run |
| `hybrid_k6` | More retrieved evidence and possible extra distractors |
| `hybrid_k4_reversed` | Same four exact bytes, reverse presentation order |
| `organized` | Existing deterministic entity/revision/bridge selection |
| `program_support` | Diagnostic upper bound, NOT a human-certified oracle |
| `empty` | Zero-evidence control under the same reader |

All arms use the same original retrieved pool, fixed reader, source bytes,
question, permitted test-program worker, prompt and generation configuration.
The no-evidence and program-support arms are included to make reader failures
interpretable; oracle-derived labels **never** choose the RAG k or its ranking.
No source bytes are truncated. A context overflow is a retained failed attempt,
not a silently removed hard example. Final answer labels are parsed only after
all seven-arm raw outputs are durable; `preflight` may hash the file for identity
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

The read-only `.github/workflows/hepta-memory-strong-rag.yml` triggers for
PR #1452 on source/test/workflow changes. It checks repository formatting,
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
