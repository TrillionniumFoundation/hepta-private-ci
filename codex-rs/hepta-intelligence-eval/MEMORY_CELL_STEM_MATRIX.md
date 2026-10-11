# Shared-stem persistent Cell development matrix

## Scope and authority

This is a research experiment under the existing MemoryCell evidence lab. It does
not register a production model, write cognitive memory, grant source access,
install an inference owner, approve a candidate, or replace CNS/HNMF governance.
No main update, PR merge, production switch, CI waiver, independent signature,
future observation window, or statistical superiority follows from this code.

Use the exact executed commit and terminal Actions receipt. A green older commit
is not validation of a newer head. The first stem mechanics run, `38097948545`,
validated source `6807ec3cae2230b7317f257a7fbc49e39cf09dd6`: 455 Python tests passed,
including 22 new head/cache tests. That run predates the native matrix and the
encoder-Adapter/protocol/runtime extensions described below. It is mechanics
validation, not a pretrained native-task result. New runs retain their own exact
source/tree, environment, tests, failures, model outputs and SHA-256 manifest.

## Six matched arms

| Arm | Shared input and task | Learning |
| --- | --- | --- |
| `frozen_rerank` | Cached hybrid retrieval, pinned pair Encoder, fixed Reader | None; use native relevance logit |
| `prototype` | Same candidates, pair Encoder and Reader | Per-cell positive/negative sufficient statistics |
| `linear` | Same candidates, pair Encoder and Reader | Per-cell linear residual and null readout |
| `gated` | Same candidates, pair Encoder and Reader | Per-cell gated rank-16 residual and readouts |
| `lineage_lora_gated` | Same retrieval/candidates/Reader; one adapted pair Encoder shared across two Cells | Encoder attention LoRA once, then persistent gated heads |
| `independent_lora_gated` | Same retrieval/candidates/Reader; separate pair Encoder copy per Cell | Separate attention LoRA once, then persistent gated heads |

The baseline is the existing bounded hybrid retrieval plus frozen cross-encoder,
not an assertion of globally optimal RAG. Every arm uses forced top-1 selection
unless the candidate pool is empty; no arm gets a different abstention threshold,
reader prompt, decoder, input limit or annotation-derived candidate pool.

The independent controls are separate MiniLM cross-encoder copies, not 421M Laya
replicas. This initial matrix screens head capacity and shared versus independent
adaptation on one pinned Encoder. It does not establish the best Encoder or a
resource ratio against thousands of 421M models.

## Representation and differentiation

The dense retriever is the existing pinned `all-MiniLM-L6-v2`; the paired Encoder
is the existing pinned `ms-marco-MiniLM-L6-v2`; the Reader is the existing pinned
`SmolLM2-135M-Instruct`. Reuse the revision and tensor/inventory pins from
`pretrained.py`, `relevance_ranker.py` and `stem_cell_trial.py`; do not substitute a
same-dimension checkpoint. Model loading disables remote code and the actual
trial runs with the Hugging Face/Transformers offline flags enabled.

The head consumes final joint query/evidence CLS features plus the native
relevance logit. At dimension 384 and rank 16, a gated head contains 13,826
trainable scalars (55,304 FP32 weight bytes); the linear head has 770 scalars.
The prototype has 770 FP32 buffer scalars and no gradient-trained parameters.
These counts exclude gradients, lineage, snapshots, caches, models and indexes.
They are not measured deployment RSS or end-to-end cost savings.

Pair encoding depends on both query and candidate; documents cannot be encoded
once for every possible query. Identical admitted query/pool/model requests can
be reused across heads. Encoder-internal LoRA creates a different representation
identity, so each adapted backend pays its own encoding cost.

The shared feature cache is a bounded LRU. Its key binds model identity, complete
observable query including scope/time, family and exact candidate-pool seal.
Hits revalidate current evidence and Encoder training-source withdrawals. Cached
tensors are cloned, not returned as writable shared aliases. Size accounting
includes tensors and serialized metadata estimates, not unmeasured Python
allocator overhead. No cache is an authorization owner.

LoRA is inserted inside attention query/value projections, rank 4, alpha 8,
dropout zero. This is actual encoder differentiation, not a renamed head MLP.
Only the initial 16-example development cut may initialize it: shared lineage
gets at most 24 updates/16,384 pair tokens; each independent Cell gets at most
12 updates/8,192 pair tokens. The combined declared ceilings are matched; actual
consumption is recorded and can differ. Unannotated negatives are weak
supervision, not independent contradictory-evidence verdicts.

The Adapter then freezes for every subsequent head checkpoint. Base-weight
integrity, actual LoRA tensor delta and stable representation identity are
checked. Fresh model instances reload only the Adapter and reproduce a probe's
exact feature seal. This is same-process artifact reload, not cross-host recovery.

## Persistent curriculum and evaluation census

Select 24 observable `general` and 24 observable `temporal` training questions
from the existing LoCoMo training partition, ordered by a fixed identity digest
and interleaved. Routing uses question text only. The 16/32/48 checkpoints refer
to attempted development examples; missing native positive support remains an
explicit training disposition, never a substituted example or fabricated null.
Each actual Cell can therefore receive fewer admitted labels than the prefix size.

Heads keep weights and cumulative counters between checkpoints. Gradient heads
use 128 requested SGD updates per Cell per checkpoint, learning rate 0.03, no
momentum; a cumulative one-million-pair ceiling survives reload. Prototype heads
count each admitted example once; replay without new examples is an explicit
zero-update result. Failed or no-op training is not reported as tensor learning.
The state has explicit bounds on remembered training identities and source roots.

Save and reload each Cell after every checkpoint. Updating one healthy Cell must
not change its peers' serialized states. Already recorded quarantined peers must
not poison other Cells' bookkeeping. The old checkpoint is reloaded for a timed
artifact rollback check; no deployed service is switched.

There are four eight-question evaluation cuts: selection diagnostic, old-task
retention, held-out LoCoMo task questions, and LongMemEval transfer questions.
All three checkpoints evaluate the same 32 questions. The complete declared
matrix is **576 logical policy attempts**: 3 checkpoints x 32 questions x 6 arms.
This is not all 1,986 LoCoMo or all 500 LongMemEval questions, not 576 independent
samples, and not necessarily 576 Reader executions. Exact canonical Reader
requests may be reused; actual successful and failed calls, reuse links, timings
and bounded cache storage are recorded separately.

These public corpora have already been exposed during development. The retained
source-family split guards this run's training/evaluation overlap; it does not
make the public data a new untouched acceptance set. Repeated retrospective
checkpoints do not satisfy actual future calendar windows or authenticate source
independence. Unseen LongMemEval sources are a transfer diagnostic, not proof of
general cross-organ composition or newly learned multimodal ability.

## Separate outcome layers

Policy selections and unchanged Reader answers are durably written before
held-out answer annotations are inspected. No answer annotation enters routing,
window construction, pretrained features or Reader policy prompts. Training
annotations enter only the registered train cut. No final-label hyperparameter
search or later tuning to the checkpoint results is performed by this runner.

1. Source selection is scored against native supporting document references.
   This is weaker than precise window entailment. A Reader failure does not
   erase an already observed selector choice.
2. Answer quality uses the existing diagnostic token F1, not the official
   semantic QA judge. Failed executions remain failures in the full census.
3. Citation structure checks emitted labels against actually delivered evidence.
   No emitted citation means precision is null. Structural validity never
   becomes a semantic entailment score; semantic citation precision stays null.

Unknown scores remain in all-planned lower/upper bounds. Paired differences are
clustered by registered source family, not by question rows or execution shards.
Intervals are simultaneous conditional bounds across the registered comparisons;
the code cannot authenticate family independence. `superiority_claim` and
`production_accepted` remain false even if a diagnostic point estimate increases.

## Reader reference-span diagnostic is not a gold-evidence oracle

After every policy output and learning checkpoint is sealed, a separate diagnostic
may find a literal reference-answer span in an originally annotated supporting
source and pass the unchanged original excerpt to the same Reader. This is
explicitly answer-dependent, privileged and not a policy comparator. Missing
spans remain unavailable; answer annotations are never inserted into source text.
UTF-8 byte offsets bind the delivered excerpt to original content.

A source containing an answer string need not entail the answer. Therefore this
path does **not** satisfy independently verified correct-evidence oracle coverage.
That remaining experiment needs independently admitted gold evidence, including
multi-evidence and unanswerable cases, under a separately registered protocol.
Do not call its availability count an entailment pass rate or mix it into the
ordinary retrieval-arm score.

## Resource receipts and remaining acceptance work

Record model cold load, index construction and bytes, actual encoding misses and
hits, active head training, gradients and optimizer state, artifact bytes, reload
and rollback duration, raw generation receipts, head-only p95 and complete
attempt duration. Keep failures charged. Whole-process peak RSS includes all
comparison backends and is explicitly not per-arm deployment TCO. Dense-retriever
input truncation is reported separately from strict no-truncation pair/Reader
budgets. Equal update counts are not claimed to be equal FLOPs, energy or latency.

The next qualification work remains: stronger budget-matched retrieval tuning,
multiple Encoder candidates, independent held-out task families and seeds, truly
observed longitudinal windows, gold-evidence Reader diagnostics, official QA and
independent citation entailment, per-arm serving/energy cost, multi-host fault
recovery, and separately measured visual/audio differentiation. No production
acceptance or best-Encoder recommendation is generated by this matrix.

## Reproduction

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/stem_cell_trial.py \
  /path/pinned-memory-inputs /path/pinned-pair-encoder /path/new-output
```

`.github/workflows/hepta-memory-stem-matrix.yml` stages the exact historical
artifact and pinned pair model on ordinary GitHub-hosted CPU, then runs the full
Python regression suite and all declared policy attempts. It uses read-only
repository/actions permissions, no dedicated Hepta host and no production state.
All failures are uploaded with source/tree and environment receipts. Formatting
diffs are retained as diagnostics and are not mislabeled as a formatting pass.

## Byte-pinned retrospective audit and failure-classification receipt

The original terminal matrix at source `e9c8f9c9cfc8df8887290db707598897cbc26ede`
produced **503 passing tests but an unsuccessful native experiment**. The
job log reports 576 logical policy attempts, 396 successes and 180 failures;
Reader-policy successes include 22 actual calls plus 374 reused outputs.
Those counts are not grounds for task-quality or cost-efficiency claims.
An earlier contradictory conversational and PR summary was withdrawn.

The separate read-only `stem_audit.py` audit requires the original external
ZIP SHA-256, inner per-file SHA256SUMS census, generating commit and tree. It
compares original raw predictions with later scored rows, all six arms and
three checkpoints, exact canonical Reader request keys and direct reuse links,
failure-inclusive denominators, and original reported aggregate scores. It
does not rerun any model, edit answers, create a gold-label oracle, or assert
independent semantic correctness. Unjournalled failed Reader calls cannot
receive per-call verification.

`stem_audit_diagnosis.py` additionally reports admitted versus merely
attempted training questions (including reasons for skipped native support),
full six-arm common failures versus modality/adapter-arm-specific failures,
actual Adapter attempt status, each Head checkpoint's tensor-update evidence,
exact per-answer Head snapshot digests and matched-arm changes in selected
candidate and answer bytes. All these are retrospective diagnostics of the
immutable original artifact; they cannot prove Head superiority, independent
future-window benefit or production capacity.

The dedicated hosted audit workflow is
`.github/workflows/hepta-memory-stem-audit.yml`. It uses no dedicated
Hepta host, deployer credentials, independent human signatures, or extra
generating Reader. Check its **terminal** result against its own exact
source commit: a queued run or a successful unit test is not a successful
original-artifact audit.

### No fabricated end-to-end cost ratios

The read-only `stem_audit_cost.py` pass reconciles every successful logged
encoder cache hit/miss with its own backend counter, executed query–candidate
pairs and tokens, measured encoding seconds, local Head training wall time and
reported parameter/gradient bytes, persisted Head artifacts, Reader actual
calls and reuse, index creation, cold loads and whole-process RSS. Missing
or failed Encoder calls remain as unmatched misses, rather than zero-cost
executions. Per-arm serving latency, energy, power, hardware amortization and
dollar cost are **unmeasured**. These outputs cannot justify savings relative
to independent 421M models, nor a production throughput/latency SLA.

## Reader chronology: confirmed historical shared rejection site

The original byte-pinned run `38100601911` has now passed read-only
accounting audit `38102369705`: SHA256SUMS file census, original commit/tree,
576 policy attempts and direct canonical Reader reuse all reconcile. The
original matrix remains **failed**: 396 successful policies, 180 failed
policies, 33 actual successful Reader calls including privileged diagnostics,
and 374 policy cache hits. All 180 policy failures had
`ValueError: unavailable Reader or inadmissible cached evidence`. Historical
Reader policy scores are unchanged; no independent semantic judgment occurred.

The previous `ExactReaderCache` compared raw `observed_at` strings with
`>`, which does not order the LoCoMo timestamp grammar
`1:56 pm on 8 May, 2023` chronologically. This is a common pipeline failure,
not evidence that Head or LoRA failed. The read-only fix in
`stem_cell_time.py` parses explicitly registered year/date, ISO and
LoCoMo minute timestamps and compares normalized values. Unknown or mixed
precision/timezone values fail closed; actual future evidence is still denied.
Scope, source withdrawal and candidate bindings remain enforced on cache hits.
No historical answers are silently rescored or reconstructed.

`stem_cell_time_preflight.py` examines actual pinned native session and
query timestamp pairs before model evaluation, reports future/incomparable
observations separately, and never promotes malformed data to admissible
evidence. The new source revision must demonstrate on its own terminal run
whether this restores all 576 policies. A passed chronology fixture or
preflight is not proof of task learning; no independent future windows are
fabricated. The format's notion of equal timestamps is benchmark-coeval,
not proof of within-session causal ordering or production chronology authority.

## Structural opportunity for learning

A Head cannot improve forced top-1 selection on a single-candidate evidence
pool. Read-only `stem_audit_candidate.py` recomputes per-phase candidate count
histograms from the **original frozen Encoder's committed extraction receipts**.
This keeps no-candidate, one-candidate and two-or-more-candidate tasks separate,
while verifying identities, full question coverage, and duplicate consistency.
A multi-candidate pool only offers an opportunity to improve ranking: it does
not establish true support, entailment, correct answers, or actual Head gain.

## Label-free ranking geometry at every persistent checkpoint

`stem_cell_geometry.py` records each unchanged six-arm forced-top1 policy
decision's frozen native relevance-logit gap, Head-adjusted gap, absolute
learned residual magnitude, candidate count, rank flip and a pinned score
digest **before** invoking the Reader. The policy's own deterministic
selection function remains unchanged. A Reader admission/generation failure
must not erase already observed feature/decision telemetry.

This distinguishes an unrankable single-window pool from frozen logits whose
margin dwarfs the Head's update. It can detect rank flips, but it cannot
judge whether any flipped decision cites the right document or entails the
answer. Statistics are labelled `label_free`; no gold answer, temporal oracle,
selection threshold search, or task metric enters the online decision. Score
margins are raw logits, never calibrated probabilities.

The per-checkpoint `selection_geometry` summary is diagnostic only.
Do not promote parameter deltas, larger Head scores, cache reuse or candidate
count into claims of generalizable learning or production readiness.

## Track training adaptation separately from held-out task effects

The additional `stem_cell_training_probe.py` evaluates the **same registered
multi-positive training objective** before/after the saved Head checkpoint for
each admitted training example. It observes how source-support loss and
source-versus-null margin change, including native unanswerable cases. Every
training example is bound to its registered `TrainingCut`, its Head snapshot
and its explicit route. Every attempted probe, including failures, is retained
in `weak-training-probes.jsonl`; failures cannot disappear from the
denominator. The baseline has no learning and uses original native scores.

This is **weak native document support**, not human-verified window-level
entailment. Decreasing the admitted training loss is never a successful answer,
a new-task transfer score or reliable citation. Only the separate held-out
source/Reader/citation evaluation can establish downstream benefit, and even
that requires independent family/semantic review before production admission.

## Weak-label loss audit requires fit-strategy discrimination

The `stem_cell_training_probe.py` receipt now distinguishes real
multi-positive **SGD Head fit** (and only when at least one candidate was
available), **prototype sufficient-statistics accumulation**, and the
**frozen, nonlearning control**. The same post-hoc cross-entropy diagnostic may
be calculated for every arm, but it is **not** the actual optimization
objective of the prototype or frozen control.

At checkpoint 16/32/48, the diagnostic is a cross-sectional comparison of
saved Head logits with original frozen logits on *admitted training rows*,
not an observed pre/post optimization curve for the same evolving Head.
The separate held-out task/citation/retention census remains the sole place
to look for task benefit. A lower diagnostic training loss does not establish
representation transfer, supported citations, prospective evaluation, or
independent production admission. Failure rows remain in the denominator.

## Three-way source-loss attribution (development-only)

At each persistent checkpoint, `stem_cell_training_probe.py` now separates
**original frozen Encoder**, **frozen-after-adaptation Encoder without Head**,
and **the checkpoint Head applied to that Encoder**. Every value is bound to
the same registered TRAIN question, candidate identities, pool seal, family and
Head snapshot. The two conditional deltas distinguish Encoder adaptation from
Head readout. This corrects the previous misleading use of adapted Encoder
logits as a supposed original-frozen baseline.

The native train-source labels are weak document-level support, not
independently verified entailment. Frozen and prototype controls do not perform
the SGD fitting objective. Lower diagnostic training loss does not establish
within-Head progress, generalization to unseen families, correct downstream
Reader answers, or semantic citation quality. If source/feature identity
drifts, the probe fails and the attempted row remains in the audit.

## Three-way, label-free source ranking analysis

The persisted native experiment now records three matched rankings for each
planned answer before the Reader runs: (1) original frozen pair Encoder,
(2) LoRA-adapted pair Encoder without its Head, and (3) the learned Head
applied to that adapted representation. Candidate identities, source-family
and pool digest must match the original frozen feature batch. The report
separately counts Encoder-only flips, Head-only flips, joint flips, and the
case where a Head cancels an Encoder flip. Frozen-model and same-pool controls
must have exactly equal original and Encoder-only scores.

This is **label-free analysis only**: a rank flip is not evidence of correct
source choice, transferable memory, independent semantic citation support or
a positive task-level Reader outcome. The fixed forced-top1 policy, Reader,
prompt, training/evaluation cuts and candidate pools remain unchanged.

## Native LongMemEval weekday-time compatibility

The source-only chronology preflight of the original pinned data at
`683c02f5` reported **0 comparable and 23,867 unknown LongMemEval
source/question timestamp pairs**, while its LoCoMo pairs were comparable.
The native LongMemEval grammar is `YYYY/MM/DD (Ddd) HH:MM`, e.g.
`2023/04/10 (Mon) 23:07`. The time parser now explicitly validates
calendar date, 24-hour time and the supplied weekday. Inconsistent weekday,
invalid calendar, unknown format, mixed precision and real future sources
still fail closed. This compatibility repair does not retroactively change
the original 576-record experiment; the new run must produce its own result.

## Strict as-of admission before retrieval and all Encoder work

A Reader-only future-source check is too late: a future document can already
affect index ranking, features and training. The research matrix now uses the
same bounded, strict timestamp parser to select the source history **before**
building the full-text/vector retrieval index. Each index is keyed by its
original source-file pin, scope and exact question observation timestamp, and
a distinct as-of index cut binds source identities and measured resources.
Future documents are excluded from every arm's candidate pool, not merely
rejected after Head selection. Unknown timestamps, missing eligible sources,
source withdrawal and cross-scope history fail closed.

The code retains `source-admission.json` receipts reporting admitted vs
excluded-future *source occurrences*, alongside every failure in the original
planned question census. This is a new preregistered input policy; results
cannot be compared with older all-history outputs as if only the Head changed.
A future support annotation does not justify recovering the unseen source.
This benchmark filtering does **not** replace the authenticated production
source-authorization owner, real future-window observation, or semantic
entailment admission.

## No-evidence Reader capacity diagnostic (separate from all six Heads)

The native trial now runs a second, isolated copy of the **identical pinned
frozen Reader weights and generation prompt** after completing the planned
six-arm answers and privileged source-literal diagnostics. For each of the
32 preregistered held-out questions it supplies **no evidence**. The control
cannot consult the train, selection or answer targets when generating and it
cannot alter a previous policy answer or poison the main Reader's cache/state.
The separate instance's cold load, real generation attempts, success/failure
census and cache accounting are charged to this *diagnostic*, not to a
learned Head.

The post-generation review then matches each zero-evidence question with the
same question's **final-checkpoint frozen-rerank + original Reader** answer.
Source family, requested Reader profile, original candidate and delivered
evidence receipts remain explicit. Answer diagnostic token-F1 deltas are
computed only when both original answers exist and are scorable. Missing,
failed and unanswerable labels are retained in conservative all-planned
delta bounds. Any evidence marker emitted with no evidence is structurally
unsupported; semantic citation precision is **null**, not 100% or 99%.

These controls separate some Reader-capacity failures from source-selection
failures, but they do **not** manufacture independently reviewed sufficient
evidence. The previously registered privileged literal-answer Oracle is
neither human-certified entailment nor a production gold source. A stronger
reference Reader, real ablation review, authenticated prospective sources and
blinded semantic citation judgment remain separate follow-up requirements.

## Reader evidence exposure is not the same as merely answering twice

The blinded zero-evidence control is now accounted in two distinct cohorts.
Every one of the 32 preregistered frozen-policy/empty-Reader pairs remains
in the full denominator, including baseline failures and unscorable answers.
Within that census, a separately marked **observed source-exposed cohort**
contains only successful baseline answers whose original Reader receipt
confirms that one actual evidence window was delivered. Baseline empty-prompt
answers and failed baselines with unknown exposure are not silently counted
as evidence-derived gains.

Separate conditional delta means and worst-case bounds are reported for
the observed exposed cohort; the unselected and failed cases remain visible
under the original 32-question all-planned bounds. The exposed cohort is a
post-hoc *diagnostic* subset, not a newly preregistered independent test. Both
Reader receipts must identify exactly the same pinned model and prompt,
even when the two executions used separate model instances. No source
entailment, semantic citation precision or production gate is inferred.

## Completed-but-unqualified earlier six-arm run: independent baseline reconstruction

The research staging run `38099411279` at source commit
`306c2c8dc745b22f4dc137fdfec5e83158189964`, Git tree
`4e84e9443c68fa12cff3e4235d4dd18b0611ee77`, emitted a
historically complete 576/576 native development matrix. Artifact
`11687561401` has independently observed external ZIP SHA-256
`2f15aa0a6c4900b2cf19cc03051f2727c58c9c04c1d993eda6486e019d0d0014`.
That earlier runner called its Reader directly without the later
ExactReaderCache's as-of time guard, and is **not** a successful execution
of the current research/production admission implementation.

The failing later original `e9c8f9c9...` artifact `11688435110`
(`3e09533c535f6b847f9ec58d4f56055d3a2c6adb2eee68705873584a72aca909`)
matched the earlier run's cohort, frozen model inventory, prompt, and
registered 16/32/48 six-arm matrix. Its **396 successfully executed answers
are byte-identical to the earlier run's corresponding raw answer strings**,
with the same original delivered excerpts and actual input/output token hashes.
The other 180 attempts originally failed the Reader gate. Across the two
versions, one previously failed row has a different recorded Head selection,
so never claim all 576 choices are cross-run identical.

Within the completed earlier staging run, the five learned Head/Adapter
arms each have **96 matched successful comparisons** against the frozen
ranker; all five have **0 changed source selections and 0 changed original
answer bytes**. A complete execution census is not an observed learning
advantage. The full 80-question original Encoder candidate census found:
48 training tasks with 8–10 windows, eight select tasks with 8–9,
eight retention and eight test tasks each with 8, and eight transfer tasks
each with 32. No registered task had only one candidate, disproving that
single-candidate forced-top1 alone explains the absence of learning.

`stem_archive_contrast.py` and the separate
`hepta-memory-stem-historical-contrast.yml` audit validate **both external ZIP
SHA-256 pins and complete internal SHA256SUMS manifests**, source commit/tree,
cohort/Reader registration, 576 exact policy identities and unchanged
successful answers. They record the old execution's unsafe gate boundary
explicitly and never issue a current-source quality or production certificate.

Separate local source-only checks of the pinned LongMemEval raw dataset
(SHA-256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`)
found 1,475 truly future session timestamps out of 23,867 across all 500
native questions. The eight preregistered transfer questions had no
future-dated session in their histories. These are source-level chronology
counts, not 500 prospective independent answers or adjudicated support.

## Adapter warm-start: optimizer steps are not independent supervision

The byte-pinned original `e9c8f9c9...` audit now reconciles every LoRA
prepared, pair-ineligible and actually consumed training question with the
48-question predeclared train cut and its source-family/Cell route. The
historical result is:

| Registered quantity | Actually recorded |
| --- | ---: |
| Planned train questions | 48 |
| Admitted Head weak-source questions | 40 |
| Adapter warm-start prefix | 16 |
| Admitted warm-start Head questions | 14 |
| Actual positive/negative pair-trainable lineage questions | **10** |
| Lineage optimization steps | 24 (14 repeated-question steps) |
| Independent General LoRA unique questions / steps | **4 / 12** |
| Independent Temporal LoRA unique questions / steps | **6 / 12** |
| Independent training source families in lineage warm start | **5** |

The 3 frozen Adapters finished with real nonzero tensor changes and exact
artifact-only reload parity, but the **Encoder Adapters were frozen after
the first 16 train questions**. They did not adapt to the additional
questions admitted by the 32/48-Head checkpoints. The native corpus marks
unannotated negatives only as **weak distractors**, not independently
verified contradictions or entailment. Thus 24 LoRA SGD steps are **not**
24 independent supervision examples. This distinction is crucial before
claiming Cell transfer, sample efficiency or per-Cell cost savings.

`stem_audit_adapter_warmstart.py` enforces the all-example partition,
duplicate/admission checks, per-route isolation, complete Head journal,
base-unchanged proof and actual adapter-only reload receipts. It joins
the independent original-artifact audit but **does not change** historical
answers, re-run an Encoder, authenticate source families for production
or issue qualification. `production_accepted=false`.

## Predeclared 16/32/48 pair eligibility — without extra model calls

`stem_cell_adapter_opportunity.py` now reads only admitted TRAIN rows that
were already produced before Adapter differentiation. At each original
16/32/48 checkpoint it reports the total weak-source-admitted questions,
the subset containing **both a positive source window and an available
negative window**, the unadmitted/missing-support count, and per-Cell
independent source-family counts. It binds the **16-question prefix** to
the actual lineage and independent LoRA prepared-question receipts,
rather than treating an AdamW/SGD step counter as a new training example.

This is a necessary training-signal *opportunity* audit: it does **not**
execute additional Adapter updates, expose held-out annotations, select
new hyperparameters, improve answer accuracy, or authenticate negative
entailment. The experimental Adapter remains frozen after its original
warm-start; any larger checkpoint pair eligibility is a separately
reported **unused opportunity**, not retrospective evidence that the
Adapter learned it. Failed Adapter receipts remain explicitly unavailable.

## Fixed-pool retrieval ceiling versus Head misranking (post-policy labels only)

`stem_cell_source_ceiling.py` is a **strictly post-answer diagnostic**:
after all six-arm and no-evidence Reader answers have been committed, it
joins 32 preregistered held-out questions with published native
document-level support labels and the exact fixed candidate windows.
It never sends the answer target to retrieval, an Encoder, a Head, a
Reader prompt or tuning. Candidate-pool digest, source family, question
identity and forced top-1 decision are bound to the frozen control receipt.

The final-checkpoint report records three causally different cases,
with separate 8-question phase denominators:

* **Support never retrieved:** no labelled native supporting source
  appears in the eligible candidate pool. No Head constrained to this
  fixed pool can recover the absent source.
* **Support present but frozen ranker missed it:** at least one labelled
  native support window was in the candidates and the frozen top-1 chose
  another. This is a *weak-source ranking opportunity*, NOT a proven
  improvement from any trained Head.
* **Native support selected:** compare the actual Reader answer (and
  separately the no-evidence answer) to diagnose generation capacity.

Published `unanswerable`, missing pool, unresolved labels, failures
before selection and Reader execution failures have their own counters;
no failure is dropped from the all-planned denominator. This is only
native **document-level** weak support, not a reviewed window-level
entailment or sufficient-evidence oracle. The analysis cannot certify
semantic citations, prospective time/withdrawal authority, production
benefit or an Encoder/Head winner.

## Actual within-Head training fit before versus after each persistent checkpoint

A parameter tensor delta alone does not show that the Head optimized the
intended weak-source objective. The native runner now observes each unchanged
**admitted TRAIN Supervision row's logits immediately before and after** the
real 16/32/48 Head update, using precisely the same frozen Encoder features
and exact same positive/null supervision. It retains all per-row weak-label
loss changes, actual candidate top-1 flips, the Head snapshot SHA-256 pair,
route, family and explicit train-only cut identity. No new Encoder/Reader
execution or held-out target scoring is added by this diagnostic.

For linear/gated Heads this is the same multi-positive/abstention log-sum-exp
objective used by actual SGD. For the prototype Head it remains diagnostic
cross-entropy, not a claim that its sufficient-statistics algorithm optimizes
cross-entropy. This is **within-training-cut observation** and may reveal
overfitting: any lower train loss must be contrasted with independent
held-out source choices, fixed Reader answers and actual citations. Neither
a train-set rank flip nor a loss decrease establishes unseen-family transfer.
The report is `comparison/within-head-train-fit.json`, retained in the
complete trial artifact and explicitly marked `production_accepted=false`.

## Separate null-confidence fitting from weak-source rank improvement

The revised `stem_head_fit_dynamics.py` receipt now measures the **same
admitted TRAIN sample** three ways before and after each persistent Head fit:
the original multi-positive-vs-null training loss; the maximum labelled
native-support logit relative to the best unlabelled candidate; and the
null-vs-best-candidate logit difference. Each retains its own denominator.

A lower cross-entropy from suppressing the null logit can leave forced-top1
evidence ranking **completely unchanged**. The audit therefore reports
weakly-supported top-1 gains/losses and positive-versus-negative margin changes
separately from lower training loss, and explicitly distinguishes
native-document weak supervision from independent semantic entailment.
Unanswerable/all-positive pools are not miscounted as meaningful
positive-negative contrastive evidence. Nonfinite margins or deltas
fail closed. Prototype Head remains a diagnostic, not SGD optimization.

These measurements are in-sample, require only the *existing* saved Head and
frozen Encoder feature rows, and cannot establish held-out answer or citation
benefit without an independent fixed-Reader evaluation. No training
hyperparameter or model-selection policy is changed by this instrumentation.

## Direct TRAIN-fit versus held-out frozen-source comparison

`stem_train_heldout_bridge.py` is applied only **after all 576 original
policy answers have been recorded and native post-policy scoring is closed**.
For each 16/32/48 checkpoint and every learned Head/Adapter Cell route, it
joins the measured **actual prior/updated Head SHA-256** and TRAIN-only weak
loss delta to the *same question, Cell, source family, and exact candidate
pool* under the frozen ranker and learned arm.

It reports separate **test** and **transfer** weak native-source support
gains/regressions, changed top-1 choices, matched actual Reader successes,
scored paired token-F1, and conservative original-planned uncertainty bounds.
Reader failures do not erase already observed selector decisions; missing
selections or native unresolved labels are **not** counted as successful
comparisons. Previously exposed selection and old-task revisit retention
remain distinct, not relabelled as unseen test evidence.

A lower training loss without a positive observed held-out source net change
is an informative mismatch, not independent proof of overfitting. A LoRA
arm is **Encoder adaptation plus Head**, so the frozen-to-LoRA comparison
cannot attribute gain to its Head alone; the separately pinned three-way
score geometry is required for that attribution. No gold source enters any
actual training or policy decision, and native document-level source
support is not independently verified window entailment, citation
precision, or a production acceptance gate.

## Separate native no-answer success from retrieved-source evidence gain

The post-policy TRAIN-to-test/transfer bridge now accepts the **exact 32
registered evaluation targets only after all 576 policy attempts have been
saved and scored**. It classifies each native target as one of:
answerable with document-level support; benchmark-unanswerable; or
unresolved/missing document-level support. Source-selection improvements
are counted **only for answerable, resolved native source-support cases**.
Unanswerable cases can contribute to a separately named abstention metric,
but never to a retrieved-source gain. The reported null/refusal choice must
match the original observed selected index; forged abstention correctness
fails closed.

Each originally registered phase retains its 8-question denominator
(including failed Reader calls and unresolved support). Reader F1 deltas
remain a separate diagnostic, not implied source sufficiency. The new v3
report rejects targets outside the registered evaluation cut, duplicate
questions and invalid metadata and explicitly marks absent true semantic
entailment judgment and no production acceptance.

## No-tuned, label-free native null-vs-forced-top1 counterfactual

The original six-arm protocol is **strict forced-top1** whenever any
candidate exists. A byte-pinned native input plus original ZIP audit
confirmed that of the 32 registered evaluation questions, **25 are
answerable and 7 are benchmark-unanswerable** (2 select, 2 retention,
2 test, 1 transfer). All seven unanswerable questions still contain
native *source-reference metadata*: these are not positive answer
evidence labels. At original checkpoint 48, all seven selected a
non-null source. Original frozen correct native-document source
selections on answerable questions were **13/25**, and original Reader
executions succeeded on 22/32; these numbers are historical source-level
diagnostics, not current-source performance or citation entailment.

The new `stem_native_null_ablation.py` records, on every arm/phase/stage,
the original *unmodified* Head null-vs-best-candidate logit and what the
**same native zero-offset null decision** would do. No answer label is
used to choose the threshold, no selective policy is deployed, no
original forced-top1 decision is modified, and no Reader is rerun.
Only **after all original six-arm answers have been saved** does the
read-only `review_null_counterfactual` compare the zero-offset source
choices against native answerability. The result separately counts
correctly recovered benchmark abstentions versus harmful abstentions
on answerable cases, preserving all 576 policy rows and original
8-question phase denominators, including failed and unscorable rows.

The hypothetical null choice is **not** a real counterfactual Reader
answer, independently verified sufficiency evidence, semantic citation
precision or independent model-selection gate. It is exploratory and
cannot be promoted to a production winner without a separate,
predeclared model/Reader evaluation.

## Held-out effective N: three checkpoints are repeated questions, not new subjects

The `stem_effective_n.py` post-policy audit binds the complete matched
frozen-vs-learned panel to **the same 16 registered test/transfer question
identities** at the 16, 32 and 48 training checkpoints. There are 48
repeated observations *per learned arm*, but only **16 unique held-out
questions**, with **8 test and 8 transfer questions**; each routed Cell
sees only 8 held-out questions. The **stage-48 comparison** is the
declared descriptive primary cut. Earlier checkpoints are reported as
a within-question exploratory trajectory, not additional independent
samples or a best-checkpoint sweep.

At the final cut, the audit separately counts labelled native
document-support gains/regressions, genuine native unanswerable/abstention
cases, unresolved native support, source-choice observations, actual
fixed-Reader paired answers, and all-planned worst-case bounds for
missing/failed questions. Counts of **distinct original source families**
are descriptive only; no independent-family sampling or prospective
source-time authority is assumed, and no formal significance,
independently reviewed entailment, or production superiority is issued.

The bridge retains all 240 matched test/transfer rows across the five
learning arms and three checkpoints. Any missing/duplicate/forged
question, Cell, family, native answerability, Reader status or row
invalidates the unit-of-analysis census. Repeated observations are
never combined as 240 independent trials. These are post-policy
development diagnostics only: `production_accepted=false`.

### Repeated-measure provenance checks

The effective-N panel requires the **same original sealed candidate-pool
digest** for every observed frozen-matched selection of a registered question
across all three training checkpoints and learned arms. It separately
requires the **same pinned frozen Reader identity, prompt profile and
observable question digest** across checkpoints whenever both Readers
actually succeeded. Unknown pool exposure or failed Reader calls retain a
separate missing-verification state; they cannot fabricate positive
provenance or independent observations. Drift rejects the audit rather than
quietly counting the task as an unseen new sample.

The aggregate report is explicitly versioned
`hepta.stem-effective-heldout-repeated-panel.v2`; none of these
cryptographic consistency checks establish independent source-family
sampling, held-out answer benefit or semantic citation entailment.

### Pinned-source native family diversity is smaller still

A direct SHA-256-verified read of the **original immutable**
`e9c8f9c9...` experiment ZIP shows 16 distinct test/transfer question
identities but only **three distinct native source-family identifiers**:
Test has 8 questions from **two LoCoMo conversations**; Transfer has
8 questions from **one LongMemEval family**. The two Test families
also appear in the existing Retention cohort; **zero** Test source
families are new relative to Retention. This is a source-family
overlap observation, **not** evidence that evaluation answer labels
entered any optimizer. Training and selection family identities
remain separately accounted.

The `effective_heldout_subjects` receipt now includes a
`original_native_source_family_structure` block computed from the
**registered source-family map**, alongside the 16 unique question
denominator and 48 repeated observations per learned arm. It refuses
to infer statistical significance or independent-family generalization
from three observed family IDs; the three may themselves be dependent.
A future production-relevant result needs multiple genuinely independent
and prospective source families with separately judged support and
answer/citation correctness.
