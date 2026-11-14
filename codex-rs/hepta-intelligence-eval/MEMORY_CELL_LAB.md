# MemoryCell experimental evidence lab

This executable belongs to `learning.eval` and follows the existing DecisionCell,
HNMF and CNS design. It does not create a Memory OS, production memory writer,
model installer, registered wire format, approval workflow or acceptance issuer.
The default signed production evaluator ingress is unchanged.

Baseline: main commit `78fdb0cf8537e3a84fc6e0a849707559c80881e8`, tree
`2691c833b15a837571c880b822cbcd2bd5aa63d7`. The implementation is split into
reviewable commits: static cells, controls/topology, clean transfer/metrics,
and process-fault mechanics. Each can be reviewed independently in that order.

## Run

From the repository root, with the normal Rust/just/nextest prerequisites:

```sh
just test -p codex-hepta-intelligence-eval --test memory_cell_lab
just test -p codex-hepta-intelligence-eval --test memory_cell_controls
just test -p codex-hepta-intelligence-eval --test memory_cell_transfer
just test -p codex-hepta-intelligence-eval --test memory_cell_faults
cd codex-rs
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- smoke /tmp/mcell-smoke
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- run /path/approved-corpus.tsv /tmp/mcell-run
cargo run -p codex-hepta-intelligence-eval --example memory_cell_lab -- build-smoke "$(git rev-parse HEAD)" /tmp/mcell-builds
```

The process-fault target requires Linux `flock`. Worker tests marked ignored are
explicitly invoked by their parent tests in new processes; they are not missing
coverage. No tests change the current process environment. Output directories
must not already exist. Corpus reads are capped before allocating unbounded input.

The focused workflow also compiles the exact dependency-free lab/test sources
with `rustc` to provide a small experimental signal independently of workspace
resolution. This does **not** replace `just test`, required CI or Architecture
qualification. It uses read-only repository permissions and pinned action commits.

## What actually runs

The backend is a 32-feature frozen hashed-word encoder and tiny two-readout
nonlinear cells trained with real SGD. It is not Laya, a fine-tuned LLM, a
Transformer LoRA implementation or an installed `neuron.runtime` backend.
Semantic and procedure heads produce separate typed distributions. Inference
accepts a `Query`, which cannot contain target labels. The procedure experiment
composes diagnosis and repair-choice correctness; it does not establish a
learned cross-organ communication protocol.

Shared rank 8, static 2x4 and dynamic models have exactly the same number of
trainable scalars. Shared rank 16 and static 2x8 are a second matched pair, not a
free capacity improvement. Every trained arm uses the same 8,000,000 declared
training-operation-estimate ceiling. Dynamic parent, rejected split candidates,
accepted children and pooled-retraining merge candidates all debit the **same**
meter. Merge retrains permitted source examples; it does not average arbitrary
weights. A valid outcome is no structural change. The present router is a fixed,
observable two-domain partition, not a discovered general topology.

The nonparametric controls combine BM25 and the same frozen feature encoder's
cosine channel using reciprocal rank fusion. Scan ceilings 64 and 256 expose a
retrieval-budget curve. This transparent control is not a claim of state-of-the-art
RAG. Rebuilding its small index on each query is charged in read estimates and
latency, rather than hidden. Production comparisons must include an independently
tuned, cached/indexed strong retrieval system. All arms can use the same training
corpus and observable query; no arm sees future target labels in training or
selection. Retrieval is read-only and returns source references, not authority.

## Input and source cuts

`data::HEADER` is the exact TSV schema. Fields are:

```
episode root split time scope commit environment evidence domain semantic procedure text
```

`time` is an integer UTC Unix second. Splits are `train`, `select`, `future-a`,
`future-b`, `retention`. Training, selection and the two future observation ranges
must be strictly chronological. Correlated source roots cannot cross splits;
repeated IDs and scope mixing reject. Labels and domains are bounded to the
explicit 4-class / 2-domain pilot. All relevant environment/conditional information
must be represented in the query text; metadata fields are evidence bindings,
not hidden privileged model features. The importer validates shape and partition
invariants, **not** authenticity, consent, training authorization or independence
of caller-supplied root names. Real owner admission is still required.

`smoke` is an explicitly synthetic mechanics fixture. `build-smoke` generates
80 controlled Rust programs and invokes the actual compiler 400 times: the
unrepaired program and four repair candidates per case. Exactly one repair must
compile. It retains the source, stderr, exit status, compiler identity and generator
commit. The commit field identifies the generator revision, not a production
project source commit. These are observed compiler outcomes on generated programs,
not production build history or two future calendar windows. `run` accepts an
externally admitted corpus, but cannot independently certify it.

## Reports and interpretation

`protocol.txt` is written before training/selection. `report.json` contains all
seven controls over two held-out windows plus old-task retention: separate head
and joint accuracy, source-root mean accuracy, simultaneous 95% Hoeffding bounds
with 21-way Bonferroni correction, NLL, Brier, ECE, measured query p50/p95/p99,
training/query operation estimates, training time, amortized training cost,
parameter and serialized artifact bytes, scans and evidence-reference counts.
`storage.txt` measures actual retained file bytes, including all model arms,
the original corpus and (when generated) compiler observations. Source data is
not silently erased or omitted to manufacture a compression ratio.

Repeated rows sharing one root count as one cluster. Root independence remains
an assumption requiring independent source admission. Operation estimates are
not FLOPs, wall time, GPU accounting or a proof of equal total lifecycle cost.
The workflow additionally retains observed process CPU/RSS timing when available.

Model artifacts contain tensors and training-root lineage, not replay examples,
raw observations, task labels, KV caches or predecessor working state. Evaluation
reloads them before use, and a separate child process verifies artifact-only
transfer. This is a minimal clean Agent, not an integrated Agentd deployment.

The numeric screen is deliberately conservative and separate from qualification.
It cannot override the HNMF requirements of three independently admitted snapshots,
two real future calendar windows, sufficient independent samples, retained old-task
performance, citation precision, revocation correctness and signed independent
qualification. A reference to a source is not proof of entailment; unmeasured
`citation_entailment_precision` is **null**, never silently 1.0.
`production_qualified` and `superiority_claim` remain false in this unsigned lab.

## Failure exercises and remaining production boundaries

The persistent fault model runs real child processes under an OS lock and injects
exit before or after synced atomic snapshot publication. It exercises duplicate
operations, conflicting payloads, checkpoint CAS, prepare/commit split crashes,
lost acknowledgement, migration fencing, interrupted handoff, update-time
revocation, transitive descendant support and stale backup restore. The current
revocation/fence file is separate from the cell backup and checked before reads
or new publication. Blocking an affected artifact is not proof of selective
weight erasure. These are one-host filesystem protocol tests, not a multi-host
network partition, Byzantine protocol, physical power-loss, production owner
migration or model-unlearning certificate.

Production integration must reuse cognitive.store/read for evidence, existing
inference.control for real serving, learning.operator for training, neuron.runtime
for checkpoints, learning.artifacts for tensor lineage and the existing CNS/Circuit
owners for graph generations. Do not relabel this lab snapshot as an owner store
or its unsigned outputs as signed evaluation records. Do not inflate the existing
4096-scalar ParameterProposalV2 to fit a real adapter. LongMemEval and LoCoMo need
their native task adapters and real model/provider runs; this four-label pilot
must not report fabricated scores for them.
