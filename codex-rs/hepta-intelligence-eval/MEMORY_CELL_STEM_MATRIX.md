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
