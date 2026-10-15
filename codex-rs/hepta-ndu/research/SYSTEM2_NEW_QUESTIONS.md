# System2: new questions, fixed local supports, then real Reader outcomes

Parent: `dd3c46a45696e8485ca69da0c8624b060260b7fe`, existing PR #1546.
No existing fit, eight-arm policy, NDU/FBSDE API or production default changes.

## Parent hosted evidence is now complete

Run **38161009333**, source `dd3c46a...`, completed. Artifact **11710206914** is
1,852,317 bytes, SHA256
`889ed64fe5d09404961c4940721c7b7a892a7773973f29cd1b468aa074f92b2d`.
All **819 manifest entries / 820 files** verified. Full regression discovery:
**1,044 passed, two skipped, 1,046 total**. All 1,169 support-study predictions,
query/support identities, selected candidates and aggregate results match the
prior local study; maximum score drift is 2.384185791015625e-7.
The two-support query-macro source-hit mean remains .395 versus .30 frozen,
but six support-episode losses remain. This replication does not change the
`stop_no_controlled_support_robust_gain` disposition or add independent evidence.

## Fixed new-question cohort, not a new label for the old twenty queries

`system2_frozen_cohort.plan_cohort` selects from the original six LoCoMo TRAIN
families only, excludes ALL 80 identities in the inherited experimental plan,
and excludes case/whitespace-normalized question-text duplicates. It takes only
question metadata and text, never labels. Hash order is fixed by
`sha256(("new-question-cohort-v1", question_id))`. No quality-dependent resampling.

Each family contributes exactly two fixed support questions and eight OTHER
evaluation questions. The actual pinned native metadata yields **12 support
questions, 48 evaluation questions, 60 new question IDs total**. The questions
were not in this lineage's prior 80-question plan; that does NOT establish that
they were untouched by other repository experiments or pretraining.

All six families are previously known public-data sources. The local support
and evaluation roots intentionally overlap. The original forbidden roots remain
forbidden. No independent-source, unexposed-benchmark or prospective claim is
made. The original native question timestamps are identical within each family;
there is NO native support-before-query timestamp ordering to certify.
`natural_chronology_verified=false` is retained, not replaced with invented times.

## Freeze once per Cell; evaluate only afterward

The saved 20-question general-Cell features still provide shared priors. For each
new target family, its prior fit excludes that family and its source root. The
conv-30 target, absent from the saved general-Cell fit, uses the full other-family
prior. Local fitting sees only the two preregistered new support questions.
Missing usable source contrast gives an explicit no-op; a support encoding or
admission failure is a failure, not an invented unanswerability label.

Reuse existing `StemHead`, hinge solver, delta fitting, neighbor bank, prediction,
strict as-of indexing, candidate windows, shared feature cache and frozen Reader.
No architecture, regularization, score gate or support-budget search is added.
Every successful family/method state is saved and exactly reloaded. All family
states are sealed BEFORE ANY evaluation question is encoded or sent to a Reader.
Snapshots are not updated as evaluation answers/labels arrive. This is a physical
experimental phase boundary, not proof of natural historical online learning.

Methods: frozen, shared prior, local-only, differentiated, erased local update,
support-neighbor memory, no evidence, and ordinary ranked top-three evidence.
The six fitting/ranking methods keep the same fixed stop convention; ranked3 is
a declared multi-evidence comparator, not a claim to be the strongest RAG.
The fixed primary comparisons include ranked3, so beating only the weakest
single-source control cannot qualify the candidate.

There are **384 planned actual Reader calls** (48 questions x 8 methods), not
384 successful or independent outcomes. One immutable feature extraction per
question is reused. All arms use the SAME pinned FrozenBundleReader and 4096-token
input cap. Model-call tokens/receipts, actual elapsed time and failure attempts
are retained; different evidence lengths are NOT called equal compute.
No-evidence Reader controls can still run when query feature extraction fails.
The single local delta remains 384 FP32 weights, not a copied Encoder.

## Labels and evidence boundaries

Existing native ingress parses benchmark annotations, but the model-facing
Benchmark is copied with an empty target mapping. Only the fixed support-key
mapping is supplied to train_rows. Evaluation target access for scoring occurs
after ALL attempted raw answers have been durably written and their journal
sealed. Tests instrument that access boundary. Selected original evidence spans
and raw Reader inputs/outputs are retained without answer rewriting.

Source hits and diagnostic token-F1 remain distinct. Unknown scores and failed
answers stay in full planned denominators/bounds. Raw answers cannot be changed
by scoring. No human sufficient-evidence review or critical-premise verdict is
fabricated; Reader adequacy and independent semantic correctness stay unverified.
Even a positive new-question result requires independent adjudication, genuinely
new source/time-ordered confirmation, retention and cost-quality validation.
Source-ranking scores are still NOT calibrated NDU continuation values.

## Validation and execution

Local **157/157 System2 tests passed**, including 14 new checks. Twelve exercise
cohort selection and the coordinator; two execute the unchanged native run entry
with isolated ingress/Encoder/Reader fixtures, including 128 fixture Reader calls
and rejection of an incompatible Encoder before fitting. These are NOT actual
native Reader executions. The real metadata cohort was computed locally from the
pinned 2,805,274-byte LoCoMo input without using answer/evidence values for choice.

Local context is torch 2.10.0+cpu plus the prior published source overlay and
verbatim Features/StemHead ports, not a full repository checkout. Syntax checks
passed. Ruff/just and pretrained inference dependencies are absent locally;
no local full-repository or new native efficacy result is claimed.

A separately scoped push workflow keeps full MemoryCell regressions/static checks,
stages the immutable original data/model archive and exact paired Encoder revision,
and executes this real Reader trial. The OLD replay workflow remains unchanged,
including its no-model-staging contract. Each workflow binds its own source SHA;
workflow creation or a queued run is not a completed experiment.
Original model/data transfer (~376 MB), Encoder work, fitting, reloads and Reader
calls are recorded costs, not free because earlier studies used cached tensors.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_new_questions.py \
  /path/to/memory-inputs /path/to/pinned-ranker \
  /path/to/system2-content-38147248105.zip /new/output
```

`production_accepted=false`, `reader_adequacy_established=false`,
`independent_confirmation=false`, `reasoning_superiority=false`.
