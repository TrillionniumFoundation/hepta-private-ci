# MemoryCell continuation: candidate consumption and complete native evidence

This extension is based on PR #1452 head
`1d1f8da95a1459b1e5193f9cc7c9b6e49b57dc57`, whose integration baseline remains
main `78fdb0cf8537e3a84fc6e0a849707559c80881e8`. It preserves the existing
source-admitted owner implementations. It does not create a Memory OS, install
selected production weights, replace signed learning.eval ingress, or waive gates.

## Native data and evaluation identity

`native.py` retains original question identities, source timestamps, modality
references, and unresolved annotations. Strict ingress rejects conflicting session
contents by default. The explicitly selected `retain-versioned` benchmark profile
keeps conflicting native IDs as distinct content versions. Exact duplicates at one
date are one item; identical content at different dates remains separate occurrence
items with one support root. Gold answer flags never choose a variant. A native
annotation that cannot identify its version remains unresolved, not a fabricated
citation or a reason to remove that question from the denominator.

A malformed native history is still rejected by strict ingress. The explicit
benchmark `quarantine-question` profile instead records the question and exact
bad-history digest, emits no partial history to any model, and marks every arm
failed for that question. Other valid questions continue. Full coverage can include
failed questions; neither the shard nor the collector returns success when these
failures remain. The report therefore exposes invalid data without dropping it,
coercing null content to text, inventing citations, or crashing before a receipt.

`prepare.py` pins the LongMemEval cleaned dataset revision and exact file digest,
not the mutable repository head. Source families connect shared histories even
across question IDs. LoCoMo full runs use five family-disjoint folds, holding each
native question out once; the next fold supplies selection, all others training.
LongMemEval remains external test-only: its gold answers cannot train or tune a
reranker. These benchmark histories are allowed memory inputs, not answer labels.

`benchmark_collect.py plan` freezes dataset, native question list, fold/shard
assignment, code/model identities and budgets before training. Shards derive the
same plan; the collector checks it against the independent pre-run manifest rather
than deriving a smaller plan from whatever outputs happen to exist. All four arms
(`no_memory`, `rag`, `rag_lora`, `parametric_only`) must account for every assigned
question, including failures. Missing jobs, duplicates, identity drift, NaN scores,
or success without generated text reject. Failure counts remain nonzero, and CLI
collection fails when model work failed even if all failure records were retained.

A report's `complete` means completion of its frozen plan. Only
`all_native_questions_covered` can indicate coverage of every native question.
`native_question_total` and the actual planned count remain visible. Limited pilot
runs cannot become full benchmark claims by aggregating shards. Diagnostic token
F1 and annotated source recall are not official judge scores or citation entailment.
Unresolved source support is unscored and explicitly retained.

## Persistent strong controls and learned composition

The baseline combines persisted SQLite FTS5/BM25 with a cached pretrained dense
encoder, not an index rebuilt for every query. Version 2 binds the complete SQLite
file digest, encoder identity, source cut, lexical rows, vector dimensions and
source scope. Corruption, duplicate documents, bad encoder, or revoked roots block
reads. The parent owner must protect immutable files against concurrent mutation;
a path/hash check is not a replacement for owner fencing.

Selection tunes lexical/dense weights using the same final recall@8 budget and
source-family-weighted objective. Training also weights source families equally,
so copying one source cannot buy more gradient mass. Frozen training/selection
query budgets and actual training/optimizer allocations are recorded, not called
equal actual compute merely because the ceilings match. This is an explicit strong
control family, not a claim of exhaustive state-of-the-art retrieval tuning.

`lesions.py` evaluates an already-trained joint circuit with semantic messages cut,
messages ungated, channels permuted, or direct features removed. These are
post-training interventions: no retraining can learn around the lesion. Tensor
identity before and after must match; clean circuit reload shares neither mutable
optimizer state nor another request's context. Held-out recall is recorded for
these variants. Output sensitivity alone is not evidence of positive causal
utility, global optimality, or emergent general topology.

## Real adapter artifact boundary

The existing real pretrained reader now saves an explicit v2 candidate and reloads
it before adapted answering. `tensor_contract.py` reads bounded safetensors bytes,
not pickle. The consuming reader supplies the expected manifest digest, pinned
base byte identity, exact compatible tensor inventory and configuration, and the
current allowed/revoked source roots. Unknown fields, missing tensors, shape/dtype
mismatch, nonfinite weights, changed config, wrong base/scope, or revoked lineage
reject before mutation. After mutation, loaded tensors and frozen base are checked;
a partial or corrupt adoption quarantines the reader until a fresh instance exists.
Only PEFT's set-valued module selectors and a local base locator normalize; ordered
composition fields retain their exact semantics. Source distribution permission
is not inferred from transformation into a gradient or adapter.

Both the Python owner worker and Rust MemoryTrainerProcess include this new
contract file in the worker code identity. The existing cognitive.store -> admitted
training view -> learning.ledger/operator -> bounded offline worker -> immutable
candidate path is retained. Parameter adoption in this experiment cannot issue
production install authority. The actual selected production LoRA-serving consumer,
signed adoption, shutdown/restart/revocation races and deployment qualification
still require their owning modules' integration evidence.

The native app-server structural test now checks the actual typed
`send_authorized_turn_start` path and EnteredUseToken ordering rather than an
obsolete request spelling. It complements, not replaces, the real final-use
mutation-race test. Existing explicit arg0 helper registration is preserved.

## Reproduce

Use the repository's pinned model-worker environment and standard Rust tooling:

```sh
python -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
just test -p codex-hepta-bellman-operator -p codex-hepta-infer-worker-host
just test -p codex-hepta-agentd --test terminal_cell_owner
just fmt --base 1d1f8da95a1459b1e5193f9cc7c9b6e49b57dc57
```

The existing continuation workflow runs the two native benchmark pilots independently,
so one data failure cannot suppress the other. All tasks remain read-only, and
individual failures still fail the workflow.

The separate `hepta-memory-cell-full-benchmark.yml` is an explicit manual entry
point. It stages pinned public datasets/models, freezes the full plans, runs
bounded shards (at most two concurrently), retains successes and failures, and
independently collects all folds/shards. It has no production credentials, source
writer or automatic acceptance. It is not launched merely by opening a PR.

For an already staged, admitted input directory, equivalent direct commands are:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
export PYTHONPATH=scripts/memory_cell
python scripts/memory_cell/benchmark_collect.py plan STAGED PLAN.json locomo --folds 5 --shards 4
python scripts/memory_cell/run_native.py STAGED OUT locomo --fold 0 --folds 5 --shard 0 --shards 4 --all-questions
# Repeat every declared fold/shard with distinct output directories, then:
python scripts/memory_cell/benchmark_collect.py collect PLAN.json RECEIPTS_ROOT COLLECTED.json
```

Choose sufficient resources for actual complete native inference. A timeout or
unavailable model is a failed/missing shard, never permission to shorten the test.
Reusing test sets for development does not create a fresh final holdout.

## Validation and non-claims for this local patch

Local verification: 35 Python tests passed with PyTorch 2.10.0 CPU; runner tests use
explicitly labeled injected fixture backends and are not pretrained-model scores.
Existing, independently hash-verified CI tensors were replayed without updates:
16 LoRA archives passed finite/layout inspection, and 32 exported native Q24
vectors reproduced with maximum error zero. Archived tensor layout inspection is
not an independent proof of compatibility with a newly loaded base model.

The full pinned transformers/PEFT models, Laya, Rust owner crates, repository
formatters/lints, complete native benchmarks, or new remote CI were NOT rerun by
this local verification. Its patches have not been pushed or merged. Prior remote
model runs cannot certify the modified source.

Existing `longitudinal_time` and signed evaluation/holdout owners remain the source
of truth for three independently admitted snapshots, two actual future calendar
windows, sample independence and frozen-evaluator requirements. Cross-fit folds,
repeated CI, synthetic clocks, a shared source repeated by many Agents, or a
complete-question collector cannot satisfy those gates. Citation precision,
production distributed consistency, selective unlearning and independent acceptance
remain explicit missing evidence, not self-labelled success.
