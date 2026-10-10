# MemoryCell experimental evidence lab

This executable belongs to `learning.eval` and follows the existing DecisionCell,
HNMF and CNS design. It does not create a Memory OS, production memory writer,
model installer, registered wire format, approval workflow or acceptance issuer.
The default signed production evaluator ingress is unchanged.

Baseline: main commit `78fdb0cf8537e3a84fc6e0a849707559c80881e8`, tree
`2691c833b15a837571c880b822cbcd2bd5aa63d7`. Reviewable commits separate static
cells, controls/topology, clean transfer/metrics and process-fault mechanics.

## Run

From the repository root, with the normal Rust/just/nextest prerequisites:

```sh
just test -p codex-hepta-intelligence-eval --test memory_cell_lab --test memory_cell_controls --test memory_cell_transfer --test memory_cell_faults --test memory_cell_transport
cd codex-rs
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- smoke /tmp/mcell-smoke
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- run /path/approved-corpus.tsv /tmp/mcell-run
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- build-smoke "$(git rev-parse HEAD)" /tmp/mcell-builds
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- infer-transfer /tmp/mcell-smoke/transfer-input /tmp/predictions.tsv /path/current-revocations.txt
```

The process-fault target requires Linux `flock`. Its ignored worker entry point
and the clean-process worker are explicitly invoked by their parent tests; they
are not untested coverage. No tests mutate process-global environment. Output
directories and prediction files must not already exist. Corpus and transport
reads have explicit byte limits.

The workflow uses repository formatting, strict scoped Clippy and `just test`.
A separate job compiles the exact dependency-free sources with `rustc` and retains
experiment outputs. Neither path replaces the existing required CI/Architecture
gates. The retained workflow has read-only repository permissions, pinned action
commits, and no source-writing or automatic model-selection job. Temporary
source-preparation workflows used during implementation are removed.

## What actually runs

The backend is a frozen 32-feature hashed-word encoder and tiny two-readout
nonlinear cells trained with real SGD. It is not Laya, a fine-tuned language model,
a Transformer LoRA implementation or an installed `neuron.runtime` backend.
Semantic and procedure heads produce separate distributions. Inference accepts
a `Query` without target-label fields. Joint diagnosis/repair scoring does not
establish a learned inter-cell communication or cross-organ execution protocol.

Shared rank 8, static 2x4 and dynamic models have exactly the same number of
trainable scalars. Shared rank 16 and static 2x8 are a second matched pair, not a
free capacity increase. Every trained arm uses the same 8,000,000 declared
training-operation-estimate ceiling and maximum 256 epochs. Actual consumed
budgets can differ and are reported. Rejected dynamic candidates remain charged
to the same meter as their parent and successors. A merge candidate retrains on
permitted examples, never blindly averages weights. No structural change is a
valid outcome. The current router is a fixed observable two-domain partition,
not a discovered general topology or online distributed training algorithm.

The nonparametric controls combine BM25 and cosine similarity from the same
frozen encoder with reciprocal-rank fusion. Scan ceilings 64 and 256 expose a
retrieval-budget curve. This small transparent control is not state-of-the-art
RAG. Its per-query index rebuild is included in observed latency and estimates.
A production comparison must also use an independently tuned cached/indexed
retrieval baseline. All arms have the same eligible corpus and observable query.
Future and retention target labels are absent from training and selection.
Retrieval returns source references, not fact or effect authority.

## Inputs and source cuts

`data::HEADER` defines an exact twelve-column TSV schema:

```
episode root split time scope commit environment evidence domain semantic procedure text
```

`time` is a UTC Unix second. Splits are `train`, `select`, `future-a`, `future-b`,
`retention`. Training, selection and future collection ranges must be strictly
chronological. Source roots cannot cross splits. Duplicate episode IDs, exact
cross-split queries and scope mixing reject. Labels/domains are bounded to this
explicit 4-class/2-domain pilot. Conditional information needed by a model must
be in its query; metadata bindings are not privileged hidden model features.

The importer validates shape, size and partition invariants, not authenticity,
consent, training authorization or independence of caller-supplied source roots.
Near-duplicates and template families require stronger source-group admission in
real experiments; unique IDs or changed literals do not prove independence.

`smoke` is a synthetic mechanics fixture. `build-smoke` generates 80 controlled
Rust programs and invokes the actual compiler 400 times: original plus four
repair candidates per case. Exactly one repair must compile. Source, stderr,
exit status, compiler identity and generator commit are retained. The commit
field identifies the generator source, not a production-project commit. These
are observed results on generated programs, not production build history or two
future calendar windows. `run` accepts an externally admitted corpus but cannot
independently certify its lineage or observation dates.

## Reports and interpretation

`protocol.txt` precedes training. `report.json` contains all seven arms over two
held-out windows and old-task retention: separate head and joint accuracy,
source-root mean accuracy, simultaneous 95% Hoeffding intervals with 21-way
Bonferroni correction, NLL, Brier, ECE, observed query p50/p95/p99, training/query
operation estimates, training time, amortization, parameter/artifact bytes,
scans and evidence-reference counts. Repeated rows with one root count as one
cluster; independence of roots still needs external verification.

`storage.txt` measures all retained regular files, including the original corpus,
all model controls, transport copies and any compiler observations. Original
data is not omitted to manufacture a compression ratio. Operation estimates are
not FLOPs, GPU accounting or proof of equal total lifecycle cost. CI also retains
aggregate process CPU/RSS/wall-time observations and SHA-256 manifests, with
branch head, actual tested merge/tree and integration base recorded separately.

The numeric dynamic-vs-static screen is separate from qualification. HNMF still
requires three independently admitted snapshots, two real future calendar
windows, sufficient independent samples, old-task retention, citation precision,
revocation correctness and independently governed qualification. Source-reference
existence is not proposition entailment: unmeasured citation precision is null,
not 1.0. This unsigned lab keeps `production_qualified` and `superiority_claim`
false even when a numeric screen passes.

The initial corrected-fixture run at source `b1edf291aa2f76d7f3b9252e04c96e5a051a9ecd`
(Actions run `37785256105`) found no dynamic-over-static or cell-over-retrieval
advantage: static cells, dynamic cells and both retrieval arms scored 100% on the
synthetic future/retention windows; shared rank 8 scored 96.875%, 95.3125%, 98.4375%
respectively. All arms scored 100% on the controlled compiler microbenchmark.
This is a ceiling/insufficient-discrimination result, not a superiority finding.
No model or topology was tuned against those final held-out scores in this change.

## Clean transfer and fault exercises

Model artifacts contain tensors and training-root lineage, not replay examples,
task labels, raw observations, KV caches or predecessor working state. Evaluation
reloads artifacts before use. A child-process test verifies artifact-only transfer.
Two additional fresh GitHub runners receive only a model and unlabeled queries;
a separate verifier receives expected outputs afterward and checks parity.
A newer revocation view is then published, and two fresh restore runners must
reject the old model copy without producing a prediction file. This tests real
cross-runner artifact transport and ordered revocation, not an Agentd deployment
or multi-host consensus algorithm. Revocation authority is supplied by the test
harness, not authenticated by an installed production owner.

The filesystem fault model runs real child processes under an OS lock, including
exit before/after synced atomic snapshot publication. It covers duplicate delivery,
payload conflicts, checkpoint CAS, split prepare/commit crashes, lost acknowledgement,
migration fencing, interrupted handoff, update-time revocation, transitive lineage
and stale backup restore. Current fence/revocation state is separate from the cell
backup and rechecked. Blocking a model is not selective erasure of its learned
weights. The writer-fault exercises are one-host filesystem tests, not network
partition, Byzantine, physical power-loss or production-owner migration evidence.

## Remaining production and research work

Reuse cognitive.store/read for evidence, inference.control for serving,
learning.operator for actual model training, neuron.runtime for state,
learning.artifacts for tensor lineage and existing CNS/Circuit owners for graph
lifecycle. This change does not connect those production paths or provide a real
Laya/LoRA artifact adapter. Do not inflate the existing 4096-scalar proposal format
or reclassify these lab snapshots as authoritative owner state.

LongMemEval and LoCoMo still need native task adapters and real model runs; this
four-label pilot reports no scores for them. Stronger retrieval baselines,
predeclared non-saturated tasks, learned composition and lesion tests, source-family
holdouts, true longitudinal collection, distributed owner fault tests and independent
acceptance remain necessary before claiming a general adaptive memory system.
