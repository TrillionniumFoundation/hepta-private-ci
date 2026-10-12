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

## Stage-48 fixed null policy with already generated real Reader responses

A separate research-only `stem_null_reader_splice.py` diagnostic joins the
original complete **576** six-arm policy rows, all **32** preregistered
no-evidence questions generated by an independently reloaded, byte-identical
fixed Reader, and the recorded **zero-offset null-vs-evidence logit choice**.
Only the predeclared final checkpoint 48 is used, for 192 matched
question-arm observations. For a recorded would-abstain choice it reuses that
question's **actual raw zero-evidence Reader output**; otherwise it uses the
original answer delivered by the already executed policy. No model, prompt,
train split, index, threshold, or Reader is run or tuned by this join.

The evaluator checks original and empty-Reader identity/profile, original
observable query, exact canonical zero-evidence request hash, source-count
receipts, untouched policy top-1, original null logit-vector SHA-256, and
the complete question/arm census. Original Reader failures, failed empty
controls, unobserved null choices and unscorable QA references retain their
own planned counts and conservative paired answer-delta bounds. A separate
**actual-evidence-removed count** distinguishes a baseline Reader with one
delivered evidence window from a Reader that was already source-free or
failed before receipt. Source-answered, native-unanswerable and native
support-unresolved cohorts remain separate; raw text-F1 is not interpreted
as independent answer sufficiency or citation entailment.

The 32 empty-evidence Reader calls have *already been charged* by the
separate frozen-reader control. This post-policy splice makes zero extra
model calls, but that does **not** mean the underlying diagnostic generation
had zero cost. Combining observed responses from two matched but isolated
model instances is **not** an actually deployed seventh serving policy or a
prospective causal experiment. Its threshold was not a preregistered
generation policy and can never authorize production `Cell` routing.

## Read-only strict native retrieval-index lexical ceiling

A new source-only, exact-byte-pinned historical audit uses the **completed
strict-as-of six-arm matrix** (`38113482210`, artifact `11693742153`,
ZIP SHA-256 `3bc5f45670b9cbb5fc22d1cbff5b96866443400ea42781072b9fd66ad5ea19c8`)
and the original LoCoMo input SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
The auditor verifies all original ZIP members, generating source/tree, all
18 as-of SQLite index snapshots and the 18 source-answerable LoCoMo
questions from selection/retention/test. No source text is exported.

**All eight native-support candidate-pool misses nevertheless have their
labelled original source present in the corresponding time-admissible source
index**. This isolates the missing-recall problem *after* ingestion and
chronology admission: the source was available but did not survive source
retrieval and/or candidate-window projection.

Using SQLite FTS5 with the **original frozen OR-token BM25 ordering**, a
posthoc source-only probe over the eight misses recovers support at
lexical K=8/16/32/64 in **0/0/0/1** questions. Simply increasing lexical
channel K is not an evidence-backed solution. One native supporting source
only first appears at lexical rank 54; the others are absent at K64. Both
the original source selectors and their actual answers are unchanged.

`stem_lexical_audit.py`, `test_stem_lexical_audit.py` and isolated
`hepta-memory-stem-lexical-ceiling.yml` pin the exact old artifact, input,
original SQLite FTS5 ranking and all eight historical missing questions,
and recheck the census without running an Encoder or Reader. The GitHub
workflow must pass on its **own exact auditing commit** before declaring it
a hosted re-verification. This is explicitly *post-policy, already-exposed
labels*: it cannot select a new retrieval hyperparameter on test labels,
certify an independent benchmark gain, transform weak native-document
support into independent window entailment or authorize production.

## Train-only residual-scale shadow stress test (nonqualifying)

The strict native matrix now retains an **entirely separate** Shadow
ablation to test whether the learned Head's source-ranking *direction*
contains a transferable signal despite unchanged official forced top-1.

For each 16/32/48 checkpoint, five learned arms and two Cells, it
calibrates **only on previously admitted TRAIN weak document-source
labels**. Candidate scores are anchored to the original frozen pair
Encoder, then the learned Encoder+Head residual is multiplied by a
**preregistered fixed grid** `{0,1,2,4,8,16,32,64}`. Scale choice
maximizes TRAIN-only equal-source-family macro weak-source accuracy;
ties deterministically prefer the smallest scale, including zero.
Native test, transfer, selection or retention annotations do **not**
enter the scale selection. Unanswerable/no-positive and all-positive
training rows are visible in the receipt but cannot score as a
positive-negative ranking opportunity.

This is a separate *source-only*, **non-Reader** experiment. It runs
after each stage's official six-arm Reader answers without changing
original retrieval, candidate pool, weights, optimizer, learning rate,
prompts, answer bytes, or primary source choices. All 480 planned
shadow source decisions (5 learned arms × 3 stages × 32 questions)
are retained, including any failures; test/transfer weak source
labels are read only after all original policy and shadow choices
are sealed. It produces `shadow-train-calibration.jsonl`,
`shadow-source-decisions.jsonl` and
`shadow-source-ceiling.json` separate from all original six-arm
metrics.

A useful TRAIN-only residual direction may be too small to affect
the official top-1. A Shadow flip after rescaling is **not an
achieved Head gain at original scale**, is not a new Reader answer,
and does not authenticate window entailment, citation quality or
independent source-family generalization. Even a weak-source label
gain is diagnostic only. `production_accepted=false`.

### Shadow prediction provenance checked before answer labels

`verify_shadow_source_receipts` validates the **30** stage/arm/Cell
TRAIN-only scale receipts and **480** planned held-out Shadow choices
before native test annotations are consulted. For every successful
decision it rebinds the recorded Head artifact SHA, TRAIN-chosen grid
scale, exact original candidate-pool seal, ordered window-identity
digest, chosen source indexes and source IDs. Duplicate/missing
calibration, failed calibration reused as a success, fabricated source
identity, or mismatched frozen-vs-Shadow top-1 fails closed.
Failed decisions stay in the full denominator. Independent test source
entailment and actual Reader answer improvements are not asserted.

## Exact completed strict-run residual-scale feasibility (no answer tuning)

The earlier fully executed strict-as-of native run
[38116809759](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38116809759)
has generating source `48118e891a54c0296b182dc4b88d721b5ab4cf5a`,
tree `4891f100ce520a997e4356c00545bc670d6cbc2b`, and immutable ZIP
SHA-256 `d2147964d4b916a01bfa0051dec3a3e9aaedb5b2864625c5f2a25db0c44f20e0`.
All 136 internal manifest members were re-verified in the offline audit.

A new label-free, source-pinned `stem_strict_residual_opportunity.py`
reconciles all **576** original policy rows, matched frozen candidate pools,
selected indices and Head score-geometry receipts. Its **60**
checkpoint/phase/learned-arm cohorts report original attempted denominators,
median minimum residual scale required to overturn frozen top-1, and distinct
`limit < scale` versus `limit <= scale` counts to avoid misinterpreting an
equality/tie infimum as a guaranteed flip. It opens **no target labels or
generated answer content**. The read-only GitHub Action downloads the pinned
ZIP, verifies its external SHA, all internal hashes and tested commit/tree,
executes five adversarial/edge-case regressions, and retains a checksummed JSON.

At the original checkpoint **48**, gated Head's overall median flip infimum
is approximately **15**, while under the fixed grid of 0–64 the direction
could mathematically change some candidate on **28/32** evaluation
questions. This **does not** establish correct source support: the winning
challenger may be a distractor, and the scale was not chosen on the
training cut in this audit. The separate TRAIN-only shadow experiment
must select its scale before reading any held-out support label, and no
shadow Reader call is allowed. It cannot certify independent generalization,
semantic citation entailment, per-Cell TCO or production admission.

## Frozen Retriever TRAIN-only source-recall grid (new read-only experiment)

A strict, independent, source-pinned RetrievalPolicy experiment now replays
the **original strict 576/576 as-of source archive** at its externally pinned
ZIP SHA256, original Encoder file inventory, registered 80 native questions,
fixed `WindowBudget`, actual immutable as-of SQLite index cuts and original
top-8 candidate pool identities. The **original** `channel_k=64,
lexical_weight=0.5` policy must reconstruct the original `pool.seal()` for
**all 80 questions**; otherwise the experiment fails before any learning
claims are made.

Exactly ten fixed candidate policies are evaluated on those identical inputs:
`channel_k∈{64,128}`, `lexical_weight∈{0,.25,.5,.75,1}`, with
`top_k=8` and original RRF constant 60. Every query/policy/index/window
source identity is emitted **before labels are opened**. Only the original
48 TRAIN native-document labels select one fixed grid point using
equal-source-family-macro candidate-window recall; test, transfer, retention
and select labels are consulted **only after the selection is persisted**.
Reported held-out values distinguish original retrieved document recall
from actual source-window coverage and from changes in frozen Reader QA.

This is a bounded **frozen Retriever** alternative, not Head or LoRA
learning. It does not run a Reader, modify the native six arms, change
the source chronology, or use held-out answer labels for selection.
It may show that the original candidate ceiling is addressable by a
fixed retrieval policy; a support-document hit still does **not** certify
passage entailment, semantic citation accuracy or prospective benefit.
A successful protocol test alone is not evidence of a successful model
replay. The work is not eligible for production without independent
source-family/time windows, Reader outcomes, p95/TCO, and review.

## Effective question units versus repeated 16/32/48 policy observations

The Head-vs-frozen test/transfer bridge now independently reports the
**16 distinct registered test+transfer questions per learned arm** at
checkpoint 48. The same questions were evaluated at 16, 32, and 48
training examples, so 48 repeated measurements are not 48 independent
statistical subjects. The descriptive final-stage report preserves missing
weak-native-support labels and Reader failures in conservative all-16 bounds.
It does not claim a confidence interval, independent source-family sampling,
blinded entailment review, or production acceptance. Raw 576-policy attempt
accounting and all stage-specific receipts remain unchanged.

## Independently reconcile the latest completed strict 576/576 run

GitHub run `38136751661` completed **success** at source commit
`cb9e98365b5f46e00fb2693f548a7215b1ed1145`, original tree
`022c9aa8abc095c91ef744644329aaed12564859`. It passed
**903 Python regressions**, all original **576/576** native policy
executions, with **33 actual successful frozen Reader calls by the
final six-arm checkpoint**, followed by further post-policy diagnostic
Oracle requests. The **entire primary Reader session ended with 48
actual successful calls** (33 by the last policy checkpoint + 15 new
Oracle diagnostic requests) and **543 canonical request cache hits**.
The separately instantiated 32-question no-evidence Reader is
accounted on its own, never added to those primary-session counts. The immutable archived ZIP
`11702192907` has external SHA-256
`be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776`.
This is full strict-as-of research execution, not a learned-task or
production acceptance certificate.

The concurrently completed pinned frozen-retrieval grid
`38136751668` also executed against source-pinned native data:
TRAIN-only policy choice stayed at original `channel_k=64,
lexical_weight=.50`, with **zero test/transfer retrieval rescues**.
Only **17 of the 25 answerable evaluation questions** had published
native supporting documents in the frozen candidate windows; eight
had no weak supporting document in the fixed candidate pool.
The other seven questions were **native unanswerable**, not
missing-citation failures or source-ranking successes. These document
labels are not independently adjudicated passage entailment.

The separate read-only `stem_current_strict_readout_audit.py` and
`hepta-memory-stem-current-source-gate.yml` independently re-open
this exact completed strict ZIP. They validate the immutable transport
and every internal SHA256SUMS, generating commit/tree, all 80
registered questions, all 576 original policy and scored rows,
unchanged original answers/receipts, Reader execution accounting,
exact 32-question no-evidence diagnostic and 30 saved Head training
sessions. They recompute the frozen-versus-each-learned-arm
checkpoint/phase source selection, raw answer-byte differences and
native weak-support gains/losses directly, with benchmark abstentions
kept out of support gain metrics. The primary descriptive
test/transfer cut has only **16 distinct questions, from three
original source-family identifiers**, irrespective of repeated
checkpoints and five learning arms.

**No new Reader, model fitting or hyperparameter search** is done
by this audit. It reports whether positive native document-support
net gains appear separately in both test and transfer, but that is
still not independent statistical proof, semantic citation precision,
actual future-window validity or production acceptance. Final
`production_accepted=false` is hard-coded. The new hosted run must
finish successfully on its own audited source before treating its
report as a verified independent receipt.

## Condition the *already executed* frozen Reader on source-coverage cause

The current strict-run artifact contains 32 stage-48 original frozen
Reader requests plus 32 questions posed **without any delivered
evidence** to an independently reloaded copy of the same pinned model,
prompt and generation settings. The new read-only
`stem_native_reader_stratification.py` joins these existing exact
receipts, the post-policy 32-question native document-coverage census,
and the frozen-vs-empty matched F1 report.

The report partitions the **same 32 original questions** into:
native-support document retrieved and chosen; retrieved but not chosen;
not retrieved; native-unanswerable; and native-support-unresolved.
For each stratum, it retains every planned question, failed or
unscorable empty-Reader control, observed paired token-F1 delta and
conservative all-planned bounds. Exact Reader model/prompt/question
identity and the original one-evidence versus empty-evidence request
are independently rechecked, not merely trusted from the previous
reported mean.

This distinguishes a *retrieval ceiling*, a frozen-selector missed
document-level support opportunity, and a post-hoc Reader performance
difference **without running a new model**. Native document evidence
is not a blinded, independently reviewed sufficient answer passage,
so lower Reader F1 after receiving a labelled source does not by
itself prove a Reader capacity limit. Unanswerable tasks and absent
supports are not misrepresented as bad semantic citations. All
groups remain marked `production_accepted=false` and
`semantic_citation_precision=null`; no training or policy
configuration changes are authorized.

## Actual Reader with privileged answer-literal source — diagnostic, not gold

The successful STRICT stem matrix at `cb9e98365b5f46e00fb2693f548a7215b1ed1145`
also contains 32 post-policy reference attempts, each labelled as either
a literal substring taken from a native supporting source, native-annotated
unanswerable, unavailable reference, or failed model execution. The
`stem_native_oracle_reader_capacity.py` audit now matches those **already
emitted** answers with the 32 original frozen-top1 Reader and independent
no-evidence Reader controls. It reports separately by the actual native
source-coverage bucket: weakly supported source chosen; support retrieved
but not chosen; support absent from candidates; native-unanswerable; or
native support unresolved. All source/answer counts use the original planned
question denominator; failed/unavailable reference calls widen the
frozen-vs-reference answer-F1 interval instead of being discarded.

The reference span is selected **using the known gold answer** and therefore
is explicitly *privileged*. A reference constructed in this way is NOT an
independent human adjudication of context sufficiency, a fair retrieval
competitor, or a deployable teacher. Every successful reference Reader
receipt is required to match the unchanged model weights, prompt and
observable question, with source byte-offset evidence where applicable.
The analysis adds **zero model calls**, cannot alter any 576 original
policy answers, and never certifies citation entailment, a trained Cell,
prospective learning, or production acceptance.

## New frozen Reader capacity test: published source ID, but no answer-literal span

A separate research workflow `hepta-memory-stem-source-only-reader.yml`
uses the **byte-pinned strict native 576/576 run** at `675970bb...` and
its original 32 held-out questions. Source selection reads **only the
published native supporting document IDs**, not the benchmark answer string:
it selects a source admitted by the unchanged as-of chronology, then chooses
one query-overlap window with the identical original `WindowBudget`.
The Reader's tokeniser, frozen weights, system prompt, input/output token
ceilings and deterministic generation settings are exactly the same as
those of the original native run. A separate Reader instance and resource
journal are used; none of the original six Head/Reader decisions is replayed
or modified.

The 25 answerable registered questions have published support source IDs
present in their original raw inputs; the seven native-unanswerable cases
are retained as explicit **unavailable/no-extra-model-call** controls.
Published source ID selection is itself privileged and is not a valid
independent retrieval policy. A document's query-related 384-byte window
may still lack the answer. Do not confuse this diagnostic with the older
*answer-literal* reference Oracle, independently reviewed sufficient
evidence, or a gold citation. True future/unknown source dates, scope
withdrawal, missing source IDs, mismatched Reader identities, and failed
generation fail closed with unchanged planned denominators.

All extra source-only model outputs are persisted **before** any answer
token-F1 scoring; the report compares those new answers with the original
frozen source and zero-source Reader answers. The original 32 are stratified
by native source already chosen, retrieved but not chosen, absent from
the frozen candidate pool, unanswerable, or unresolved, each with its
own original-planned conservative score bounds. Additional compute/load
cost is charged separately. All outcomes are classified development
diagnostics with `production_accepted=false`,
`semantic_citation_precision=null`, and no independence claim.


## Immutable TRAIN-only frozen retrieval grid: revalidate the winner

The next frozen-RAG candidate experiment sweeps only the previously
preregistered **10 RRF policies** (channel-k 64/128, lexical weights
0/0.25/0.5/0.75/1), retaining the original MiniLM Encoder, exact
strict-as-of source index and unchanged `WindowBudget`. It generates all
80×10 label-blind candidate receipts before any native-document support
labels are opened. The retriever setting is selected using the **48 TRAIN
questions only**, by source-family macro recall; evaluation labels cannot
choose a policy.

The registered TRAIN winner's **complete 10-policy scorecard, question-set
digest, macro objective, source-family/scored denominators and tie-break
rule** are now revalidated *before* the 32 held-out native support labels
are scored. Arbitrary or nonfinite values, reordered or missing policies,
swapped winning RRF settings, forged chronology/index hashes, and nonboolean
original candidate-replay attestations reject. The evaluation exports
the number of distinct native source families in each phase and across
all 32 questions separately from repeated question counts. These development
families are **not** authenticated independent future populations.

A retrieval rescue means only that an original publisher-labelled
native document appears among the fixed candidate windows. It does not
show passage entailment, a correct Reader answer, improved citations,
retention, or a production p95/cost gain. An all-grid *post-hoc* upper
bound is explicitly distinguished from the single TRAIN-selected policy,
and none of its evaluation-label-derived winners may be promoted.

## Strict 576/576 complete does not imply transferable learning (12 Oct 2026)

Read-only evidence pins:

- Hosted exact-source run `38192122547`, commit
  `565f41fcd1ab6c036c6ddecc3e64b7f9033e1cbf`, tree
  `e748067a7ecf0f7fb91df6ef7dde915bd44b5882`, archived ZIP
  `11722775596` SHA-256
  `b4cf1918d9f00baa357eb386397c36f52aac54b333a0c1a629fa3389e7ae7135`.
  All **151 internal manifest members** verified. Workflow **success**,
  **1,076 full Python regression tests pass**, and 576/576 original policy
  attempts complete with zero Reader failures.
- Independent *execution replay* `38191864069`, source
  `06f081daa780dafa4bed0ff20def0999702b299f`, ZIP
  `11722640804` SHA-256
  `0a1e21d6d7b5161dddde743f182b9c2820750b09f5f3384ed38a840ab704f228`,
  also has **151 internally verified members**, 576/576 completed
  policy attempts. Across both runs, all 576 original policy records
  have identical source top-1, original answer bytes, Reader input and
  generated output token hashes. This repeats *the same* public questions,
  not an independent population or fresh future window.

The byte-pinned exact question+checkpoint comparison makes the following
critical distinctions. The five learned arms contribute
**5 × 96 = 480** frozen-paired policy observations, with **only one
top-1 change**: checkpoint 48, retention question
`locomo:conv-43/q217`, lineage-LoRA gated arm. Its original Reader
answer was unchanged and the native document-source support score
did not improve. All **test/transfer** top-1 and original answers
remain frozen-identical. No model-generated citations appear, so
semantic citation precision is **null**, never 100%.

The real 30 Head update checkpoints show **23 reductions** of mean
within-TRAIN weak-source loss, but **zero changed TRAIN top-1 decisions**
and zero improvements in TRAIN native-support top-1. The adapter warm-start
provided only 10 unique positive+negative training questions, and
28/40 final Head-admitted questions contain a positive/negative candidate
pair. The final post-policy native-source ceiling observed **8 unsupported
retrieval misses** across select/retention/test/transfer (3/3/2/0),
so merely modifying an existing-candidate Head cannot fix those misses.

The primary registered **test+transfer** panel contains 16 unique
questions *per arm*, not 48 independent cases from three checkpoints;
source-family sampling independence is **not authenticated**. A more
capable Reader, as-of retrieval and reviewed sufficient evidence must
be diagnosed separately. No independent prospective effect, reviewed
citation entailment, qualified energy/dollar TCO or production admission
was obtained. The read-only
`stem_native_nonpromotion.py` gate reconstructs the full policy
and Head receipt keys, prevents cancelling gains/regressions in
aggregates, verifies strict same-query Reader/request provenance,
and explicitly returns `scale_out_permitted=false`.

## Actual held-out weak-source ceiling before any Head scale-out (12 Oct 2026)

On the two successful strict-protocol 576-policy runs, the **16 unique
test+transfer** questions (not 48 independent repeated checkpoint
observations) have these published *document-level weak-source* counts:

| Original phase | Unique questions | Answerable with native source label | Labelled source absent from fixed candidates | Labelled source present but frozen top-1 missed | Frozen top-1 picked labelled source | Native unanswerable under forced top-1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Test | 8 | 6 | 2 | 1 | 3 | 2 |
| Transfer | 8 | 7 | 0 | 1 | 6 | 1 |
| **Total** | **16** | **13** | **2** | **2** | **9** | **3** |

With the same frozen retrieval candidates and a policy that is *forced
top-1 without null*, even an ideal source ranker could rescue at most
**2 additional native-weak-source matches out of the 16 registered
questions** (12.5 percentage points), moving the weakly supported
selection count from 9 to at most 11. The other **2 missing native
sources require retrieval changes**; **3 annotated unanswerable
questions require a calibrated no-answer action** rather than more
positive-source Head capacity. None of these bounds guarantees Reader
answer correctness or independently reviewed evidence entailment.

The complete current experiment observed **0 test/transfer ranking
rescues**, and just 1 additional retention selection change with no
original answer or support-score gain. These bounds are a
post-policy diagnostic on already-exposed public evaluation tasks, not
a preregistered new intervention, fresh independent family sample,
significance test, or promotion criterion. The paired read-only
`stem_native_nonpromotion.py` gate independently rejects any
manifest/census corruption and records separate retrieval/margin/
abstention bottlenecks without dropping the full planned denominator.

## 2026-10-12 complete strict-as-of matrix: operational success, learning rejection

A new complete source- and artifact-pinned native run at GitHub Actions
`38202116864` (`d0f69d7b94f65730fa1e093dee6989916f01898e`;
source tree `87e3b17a0601c17712b9512fc01eadc123060391`) **succeeded
in all 576 of 576 preregistered policy attempts**, with zero policy failures
under the actual strict as-of source and Reader admission. The archive is
`11726530850` and its externally validated transport SHA256 is
`07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f`.
Its fixed Reader produced 48 actual successful calls, 543 exact cache hits,
and no policy-generated structural citation markers. The exact-source fast
protocol run `38202116910` also completed successfully (146 tests).

At the last 48-question checkpoint, frozen and learned gated source
accuracies both remain **3/8 on test and 6/8 on transfer**; diagnostic
answer F1 and the actual original answer bytes are unchanged in the
paired observed groups. Operational success, a decrease of supervised
train loss, and more optimizer steps must not be promoted to independent
Reader task superiority, correctly supported citations, or Cell scale-out.

`stem_oct12_strict_nonpromotion.py` supplies an **independent, immutable
read-only rejection receipt** using the complete external/internal artifact
hash manifests and existing exact frozen-vs-learned pair,
16-unique-question effective-N, and source/answer nonpromotion audits.
It requires all 576 recorded decisions, 30 Head fit receipts, exact source
and model/source lineage, nonpromotion, and the explicit zero citation
denominator. It never executes new training, chooses hyperparameters,
consults a reviewer, or changes any production configuration.

The independent label-free raw-score replay and external ZIP check additionally
identified **exactly one real top-1 candidate change** across all learned
checkpoint comparisons: `48/retention/locomo:conv-43/q217/lineage_lora_gated`,
from frozen candidate index `1` to learned index `7`. Both selected
windows **fail** the native weak-source support annotation (`0 → 0`),
the actual Reader answer bytes do not change, and the pinned Reader
identity/prompt/candidate pool all match. This is a genuine decision
difference, but **not an observed correctness, new-family, or answer
gain**. Every test/transfer frozen-matched source choice remains unchanged.

An independent blinded sufficiency/semantic citation review, genuinely
prospective source families, and verified per-arm p95/energy/dollar TCO
are still missing. `semantic_citation_precision=null`,
`production_accepted=false` and `scale_out_permitted=false` remain the
scientifically supported gate values. Historic earlier staging executions
with different Reader admission are not interchangeable with this run.

## October 12 evidence reconciliation: complete native execution is not a Cell gain

This addendum pins two distinct observations; it is an audit note, **not**
a change in Head weights or a production go/no-go waiver.

1. **Exact real native matrix succeeded**: GitHub Actions
   [38212686661](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38212686661),
   source `aaa499074...`, completed its full Python regression, static
   check, original pinned-model/data staging, native source chronology,
   six-arm original Reader evaluation, independent pre-Reader rank replay
   and immutable artifact upload. The read-only rank replay reconciled
   **576 pre-Reader source decisions**. Model execution and CI success
   count as *operational repeatability*, not independently measured
   memory transfer or citation entailment. The nonpromotion verdict
   remains `production_accepted=false`.

2. **Different, later source failed before the real model run**:
   [38214317557](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38214317557)
   on `69b541e62...` completed **1,184 Python tests**, with **one
   synthetic fixture failure** in
   `test_locomo_frozen_retrieval.FrozenLoCoMoTests.test_all_eighty_questions_and_six_frozen_conditions`
   (`AssertionError: 9 != 6`). This reflected the nine-arm
   LoCoMo source-only control (lexical/recent/fusion at k=2/4/8)
   changing faster than its old test expectation. Current
   `test_locomo_frozen_retrieval.py` asserts **nine** and the complete
   `80 × 9 = 720` decision census. The historical run must remain
   **failure**; it does not disprove the older successful six-arm
   Stem runtime, and the corrected current test still needs its
   own exact-SHA CI result.

3. Current fast protocol and several independent read-only runs have
   succeeded, including the strict-run Reader evidence triage
   [38214530103](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38214530103).
   This isolates evidence-admission and execution defects, but is
   **not** blinded adjudication of semantic support.

The original registered six-arm decision program remains distinct
from the **nine retrieval-only LoCoMo controls**. Never conflate
their denominators (`576` six-arm Stem attempts vs `720`
source-only LoCoMo retrieval decisions), infer learned-vs-frozen
task gain from execution count, or interpret `semantic_citation_precision=null`
as measured precision. The next useful resource allocation must be based
on *native correct-support improvements on independent families* and
Reader answer/citation review, not increased Head/Adapter step count.

## Immutable cross-cohort negative admission gate (Oct 12)

`stem_cross_cohort_gate.py` reads **only three previously committed historical
JSON receipts**, each verified against its exact Git blob SHA-1 before parsing:

- LoCoMo nine-arm, 2 held-out source-family proxies: selection chose
  `lexical_k8`; on evaluation it covered **9 of 13** eligible native
  supporting sources from **16** registered questions; `lexical_k4`
  covered **8 of 13**. The eighth candidate expanded output by **8,449
  UTF-8 source bytes** for only **one** additional covered question.
  `fusion_k8` covered **3 of 13**. This is *source-ID coverage*, not Reader
  accuracy or semantic entailment. Source bytes are **not** tokens or total cost.
- Two strict-as-of six-arm Stem runs: both **576/576 policy executions**
  passed their original runners, but there are only **16 distinct
  test/transfer questions**, replayed at three checkpoints.
  **Zero learned test/transfer source or answer gains** have been established.
  The original repeated Reader token-F1 and zero citation-marker receipts
  do not certify meaningfully grounded answers or semantic precision.
- Four actual authored-task strong-RAG runs: **448 original model
  generations**, still only **8 repeated authored evaluation questions**.
  Full source path and organized path both achieve **8/8 task answers**
  with only **4/8 complete *declared* source/citation chains**;
  an automatically selected short context yields **5/8** answers and
  **3/8** declared chains. This is *not* an independent human entailment
  judgment, nor a claim that the authored tasks generalize.

These denominators and cohorts are **never pooled**, and four repeated
runs are not mistaken for four independent populations. The gate does not
train a Cell, invoke a Reader, tune policies, grade hidden labels, assert
a 99% semantic-citation rate, or modify production. It explicitly sets
`learned_cell_scale_out_authorized=false` and
`production_accepted=false`, pending independent source-family
evaluations, verified Reader evidence sufficiency, semantic citation
review, and full lifecycle latency/dollar/energy TCO.

`.github/workflows/hepta-memory-cross-cohort-gate.yml` runs
stdlib-only tamper tests and retains the precise tested source/tree, three
input byte receipts, machine-readable gate verdict, logs, and SHA256SUMS
in an all-failure-preserving artifact. A green workflow means only that
the pinned historical evidence was reconciled, **not** that the product
was scientifically or production qualified.

## Frozen Reader user-format experiment — strict, independently metered (Oct 12)

The completed strict-as-of native Stem source commit
`1578121eb24cbb3d50fbe0ae27f2d48f870bb364` (Git tree
`b40ee7f016d7830d59c45261a0dcf642800c2ec0`), run `38228733068`,
produced **576/576 successful policy executions** and **1,233 successful
Python regressions**, but **no demonstrated learned-vs-frozen task or
citation advantage**. Its pinned ZIP `11741082077` has external SHA-256
`65fe5e99c90a10dba916598dc2a83f164ef6275d7cb6c783aa6edbe3722d2563`.
The fixed Reader emitted **no structural [E1] citations** on its original
final-checkpoint frozen answers. Independent review of the raw 32 frozen
answers found **13** outputs resembling the serialized `{"question": ...}`
input rather than a concise response; **8/32** no-evidence outputs also
look serialized. This diagnostic is *not* a model-supported claim that
JSON formatting alone caused the low QA F1.

`stem_reader_format_ablation.py`, its CPU runner, fixtures and the
standalone `hepta-memory-stem-reader-format.yml` workflow now register
one **new**, bounded experiment: take precisely those **32 original final
frozen-rerank questions and byte-identical delivered source windows**,
and compare the original pinned JSON user message to one predetermined
natural-language flat user layout. Only the user text layout changes.
The system instruction, Reader model/tokenizer/inventory, greedy decode
and `max_new_tokens=96` are externally bound to the old execution.
No Head, Encoder, retrieval setting, original six-arm answer, model
parameter or original cached evidence is changed. A new Reader instance
and all 32 new model generations are charged to this format-only
diagnostic, not to the learned arms.

Every input binding, status and failure is retained before benchmark
gold answers are opened. Post-generation review reports matched
diagnostic token-F1, prompt-like JSON echo counts and emitted structural
citation markers **with the original 8-question phase denominators and
worst-case failure bounds**. An answer can echo fewer JSON delimiters
without becoming correct or faithfully supported. The reference model
still needs independent sufficiency and entailment review; no prompt
variant is automatically promoted or selected based on held-out labels.
The experiment is explicitly marked
`format_change_not_a_memory_learning_gain=true`,
`semantic_citation_precision=null`, and
`production_accepted=false`.

## Actual pretrained frozen-Encoder pairwise loss shadow (separate from the six-arm matrix)

A new **source-only** experimental branch inside the native CPU test runs
a distinct pairwise-linear and pairwise-gated Head using the *original frozen*
Encoder Features (no extra Encoder call). Unlike the ordinary
multi-positive/null SGD, the training-only pairwise objective compares the
highest native-labelled positive score against the strongest **weak distractor**
among the registered TRAIN candidates; the null/abstention output is not fit.
Each of the two Head kinds has a separate persistent General and Temporal
state trained at fixed 16/32/48 prefixes, 128 SGD steps per checkpoint,
`lr=0.03` and `margin=1.0`. These budgets are fixed in the
pre-run manifest, **not selected on test or transfer labels**.

All 12 separate pairwise Head fits and 192 label-blind source-only
test/select/retention/transfer selections are sealed before native held-out
support annotations are opened. Each shadow Head is separately persisted
and reloaded with strict original Encoder, source-root and tensor SHA checks.
No new Reader call is made, and the original frozen Reader, six policy
Head tensors, 576 original policy answers and source cut are verified
unchanged. Failures remain in a full planned shadow denominator.

After all choices are fixed, retrospective weak **document-source** support
gains and regressions versus the original frozen top-1 are tallied separately
by stage, phase and Head. A positive shadow source-only result is **not** a
Reader answer gain, independently reviewed window entailment, citation
precision, statistical proof of independent-family generalization, or
production-ready policy. A loss or regression in test/transfer is
preserved, never masked by selected favorable rows. The independent
research module and its tiny real-Torch test have their own hosted CI,
and any changed native run must obtain its own exact-source terminal
status before declaring even shadow outcomes.

## Shadow source-only scoring survives Reader failures

The pairwise Shadow Head is explicitly a *ranking-only* diagnostic. Its
original frozen baseline may have produced a valid, pool-bound **top-1
selection before the unchanged Reader failed**. The earlier score reducer
discarded that real selector decision by conditioning on successful Reader
generation; this biased its source-label denominator toward answered tasks.

The reviewer now keeps a saved valid top-1 when the Reader's generation
status is `failed`; such records can still be compared on original native
**document-level weak source support** if the original candidate-pool digest
and shadow baseline rank are identical. Reader success is never imputed.
Cases that failed **before selection**, have a failed Shadow inference, or
lack resolved source annotations remain separate unscored entries in the
original complete phase/arm/stage denominator.

The extra counters distinguish pre-Reader observed source pairs,
frozen-Reader failures with already saved top-1, genuinely unobserved
selectors and Shadow inference failures. A forged pool digest or out-of-range
selection is rejected rather than laundered into a result. No new model
call, Reader answer, semantic citation authority or production promotion
is created by this retrospective correction.

## Verify original source-window bytes when reviewing Shadow choices

A reader failure with an already saved frozen top-1 is still eligible for
read-only source-rank comparison. The review must additionally verify that
the *actual retained WindowPool* seals to the registered frozen/shadow
candidate-pool digest and that the **ordered original window identity
hashes** match the Shadow Head's saved candidate-IDs digest. Merely
comparing two reported metadata digests is insufficient if the
post-generation pool has changed.

A source-free or failed-before-selection case remains unscored without
inventing a candidate pool. Tampered source-window identity, reordered
evidence or a mismatched seal now fails closed. This has no effect on the
original six-arm Reader answers or training and does not turn a
source-only Shadow improvement into validated entailment or QA gain.

## Bind each Shadow choice to the fitted checkpoint and source-family route

The post-answer Shadow auditor now independently verifies that every
successful source-only decision has the **exact Head SHA-256 of the
persisted/reloaded fit at that stage, arm and Cell**. A forged or stale
model snapshot is a hard error, not a measured source improvement.

The original frozen Reader's question source-family and Cell route must
match the Shadow decision, whether or not the Reader successfully
generated an answer. No evaluation label was allowed into the Shadow
decision and its reported actual Reader-call count must equal zero.
These checks complement the original ordered candidate-window identity
and actual pool-seal checks, preserving the complete frozen-vs-shadow
posthoc denominator. They do not measure answer quality or grant
independent semantic citation/prospective production authority.

## Follow-up: real Reader answers to frozen pairwise-Shadow source choices

The strictly-as-of, byte-pinned original native run at `6235ccfb3ffc...`
(https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38266549880)
completed **576/576 original six-arm requests without Reader failures**,
but every original learned arm retained zero held-out correct-source gain
relative to frozen. Its 192 label-blind pairwise Shadow decisions used a
different positive/weak-negative ranking objective and did change source top-1:
at checkpoint 48, **4/32** Shadow choices flipped per arm, with one additional
published **document-level weak native support** per arm. The original
Shadow's `observed_reader_calls` was zero: this is NOT proven answer benefit.

The new `stem_pairwise_reader_comparison.py` fills precisely that gap, with a
separate, **nonqualifying** Reader-capacity experiment: exactly 32 requests
for the **final checkpoint 48**, both pairwise Shadow arms, and the predeclared
**eight test plus eight transfer questions**. No phase or question is selected
using native answer labels, Shadow source-correctness or prior answer quality.
All **192 shadow choices and 576 original six-arm decisions** must already be
sealed; the original Reader's request/call/cache receipts and Head artifacts
cannot be modified by this diagnostic.

Each Shadow source index is re-materialized only from the query's **same
strict-as-of frozen candidate pool** using the original source identity
and integrity-bound window. A fresh isolated Reader instance has exactly the
same immutable weights, tokenizer prompt and generation budget as the
original. Raw answers, failed/unavailable requests, request digests, delivered
source excerpts and actual/cache-hit Reader calls are saved **before the
new diagnostic reads gold target annotations**. Its CPU model cold-load and
incremental calls are reported separately.

After all 32 raw outcomes are stored, a separate read-only review computes
answer-token-F1 differences versus each question's original frozen-Reader
answer, with both the all-8-per-phase uncertainty bounds and the subset whose
source actually changed. Any citation marker can be counted structurally,
but independent semantic entailment precision remains **null**. This
diagnostic changes neither the original six-arm training nor policy
denominator; even a positive token-F1 difference does NOT certify semantic
citation correctness, prospective family generalization or production
suitability. `production_accepted=false`.

## Pinned pairwise Shadow: deduplicate checkpoint and arm repetitions

The immutable strictly-as-of native experiment at source `6235ccfb...`
contains **192 source-only pairwise Shadow decisions**, two research Heads
across the same 16/32/48 checkpoints and original 32 evaluation questions.
Its **19 changed top-1 observations** involve just **five distinct
questions** across four observed document-family labels. The five
published weak-document support improvement events are **not five
independent solved questions**. Four occurred on the *same one test
question* across two Heads and two checkpoints, and one occurred in
the already exposed select partition. Transfer has zero supported gains.
Exactly **two distinct questions** account for all five gain events,
including just **one** in test and **zero** in transfer.

The `stem_pairwise_unique_questions.py` post-hoc audit uses only the
original 192 label-blind source choices and the historical **aggregate**
eight-question weak-source counters. It computes provable lower/upper
bounds on the number of distinct improved source questions. It does
not fabricate a per-question gain label when an aggregate has two
flipped candidates but only one weak-source improvement. The review
worklist contains original and Shadow top-1 candidate indices, repeated
stage/arm IDs and source-family labels, but no answer, supporting
excerpt, independent reviewer verdict or semantic citation score.

The separate pinned archive audit enforces the historical exact
19/5/2 counts while retaining the verified original 576 policy rows,
HEAD and source-tree hashes, and all actual Head artifacts. This does
not tune a new ranking policy or justify Cell scale-out.

## Immutable identical-Reader-request invariance

A direct SHA-256 recheck of the original `e9c8f9c9...` development ZIP
(95/95 internal members) found 396 succeeded attempts over **66 unique
canonical Reader requests**, or **330 redundant successful repeats**.
Within each identical request, the raw answer, input-token hash,
generated-token hash and post-policy diagnostic F1 were identical.

`stem_train_heldout_bridge.py` now requires *both* Reader receipts to
authenticate their original `canonical_request_digest` from the pinned
Reader identity/profile, original question and exact delivered evidence,
also confirming the original question digest and bounded token hashes.
If two frozen-Reader answers have an identical canonical request but a
different decoded answer, token digest or post-policy score, the comparator
**rejects the purported learning gain** rather than counting an unstable
Reader/cached score as an Encoder/Head effect. Any truly changed evidence
request remains separately eligible for the existing fixed-question
comparison. Reused Reader responses are not treated as independent
model executions or new task subjects.

This is receipt consistency, **not** independently validated source
sufficiency, correct answer semantics, citation entailment, or
prospective family gain. Original successful historical outputs meet this
invariant; current modified source must still pass its own exact-source CI.

## Fixed-Reader Shadow controls: same-input gains are rejected (13 Oct)

The 32-case post-Shadow Reader control is already executed in the native
runner after the six-arm policy outputs are sealed; it is not a second policy
arm and its diagnostic answer scores cannot be pooled with the 576 original
policy attempts. The reviewer now binds BOTH originally generated and
isolated-Shadow Reader receipts to the exact model/profile, observable
question, original delivered evidence and canonical request hash. Recorded
input and emitted-token digests must be genuine 64-character SHA-256 seals.

If both paths feed identical Reader input tokens, they may not produce a
different answer or generated-token seal and claim a learned Head gain.
A changed source-window index with unchanged model-visible input is
explicitly counted as a source flip without a changed Reader input, rather
than as evidence of an improved Reader. An unchanged index cannot change
the delivered evidence. Failed/unscored attempts remain in the original
8-per-phase/arm denominator. This is **consistency validation only**;
there are no new Reader calls, semantic citation verdicts, unseen cohorts,
confidence claims, or production acceptance in this change.

## Independent post-answer policy score and citation arithmetic

The native experiment now preserves all 576 original answer attempts before
scoring and independently verifies the complete post-policy result against
unchanged raw prediction records. The new bounded
`stem_postpolicy_integrity.py` checks the original frozen-source candidate
pool, selected source, native document-level weak support, actual Reader
delivered excerpt, original question and canonical request hash; it rejects
forged correctness flags, answer-F1, citation counts, modified predictions
and any future/cross-scope source entering the candidate pool. Reader
failures stay in the original denominator and cannot acquire invented
answer or citation precision. Ten fixture attacks cover these cases.

This is a **post-policy integrity audit**, not a more powerful trained Head,
a new Reader execution, an independent semantic entailment judge or an
untouched prospective data cohort. No benchmark source label is read before
the original answers are saved, and no training, routing, decoding or
production decision is changed by this report.

The post-policy score integrity audit also requires one unchanged frozen
Reader model and prompt identity across every successful policy arm; exact
question, input-token and generated-token digests; and consistent
`actual_reader_execution`/`reused_from` receipts. If two policy records
have the same SHA-bound canonical Reader request, they must have exactly
the same raw answer and token hashes. This detects answer rewriting or
cache-laundering without making any new Reader call. These checks
still cannot independently judge factual entailment.

## Oct 13: canonical Reader cache reuse lineage is verified

The post-policy integrity audit no longer accepts an arbitrary nonempty
`reused_from` string as proof of a cache hit. It reopens the original
append-order 576-answer journal and requires every claimed cache hit to name
an **earlier successful, actual Reader execution** (not another reused result).
The predecessor must share the exact canonical request, fixed model/prompt,
question, input/output token hashes, delivered evidence and original answer.
The audit counts verified actual-execution receipts and verified reused rows
separately. Reordered, fabricated, transitive, future, cross-question or
changed-answer reuse is rejected. This is retrospective internal provenance,
**not** cryptographic host attestation or independent semantic review. Existing
576 model answers, ranking heads, source labels and production gates are unchanged.
