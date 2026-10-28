# MemoryCell research qualification

This package implements and measures six stages of a parameter-memory research
prototype. It performs real numerical training, saves trained tensors, reloads
them, and tests bounded memory operations. Execution of all six stages does not
establish that their scientific acceptance criteria have passed. The frozen
criteria and explicit non-claims are in [PROTOCOL.json](PROTOCOL.json).

The first frozen run is complete. See [RESULTS.md](RESULTS.md) for measured
outcomes and limitations, and [QUALIFICATION.json](QUALIFICATION.json) for the
machine-readable stage assessment. Single-cell recall, supplied-graph composition,
and bounded maintenance met their registered criteria. Multi-cell advantage and
net growth benefit did not; broad general memory remains unestablished.

The backend is a small NumPy classifier, `tanh(X @ A) @ B`, with a shared,
data-independent hash encoder. It is not a pretrained language model, a language
model fine-tuning experiment, or production Hepta wiring. The classification
values are bounded integers. Model artifacts contain tensors and identity
metadata; they do not contain a key-to-answer lookup table.

## Run and verify

Use Python 3.11 or later with the pinned dependency. Run the following from the
repository root; each command is a separate command and works with ordinary
Python environments on Windows, macOS, and Linux.

```text
python -m pip install -r qualification/memory-cell-research/requirements.txt
cd qualification/memory-cell-research
python -m unittest discover -s tests -p "test_*.py" -v
cd ../..
python qualification/memory-cell-research/run_study.py --smoke --output qualification/memory-cell-research/.scratch/smoke-check
```

For reproducible CPU measurements, set `OPENBLAS_NUM_THREADS` and
`OMP_NUM_THREADS` to `1` in the environment before starting Python, using the
environment configuration appropriate to your shell or IDE. The run records
these values, Python and NumPy versions, platform, and CPU count. The prototype
does not use a GPU. Thread counts and host differences can affect timing.

The smoke run uses a separate seed profile and reduced training. It verifies
plumbing, not efficacy. Every output directory must be new; retain previous and
failed runs instead of overwriting their evidence.

Before a formal run, review and commit the research sources and frozen protocol.
The formal runner rejects a dirty research package and checks that executable
source bytes do not change during execution. From the repository root:

```text
python qualification/memory-cell-research/run_study.py --output qualification/memory-cell-research/results/20261025-six-stage
python qualification/memory-cell-research/verify_evidence.py qualification/memory-cell-research/results/20261025-six-stage --repo .
```

The designated formal evidence directory is
[results/20261025-six-stage](results/20261025-six-stage). Its existence alone is
not evidence of completion: inspect `execution_status.json` and verify the
manifest. Choose a different new directory for a rerun. `--stage core`,
`--stage composition`, `--stage evolution`, and `--stage transfer` support scoped
runs; only the default `--stage all` requests the complete experiment suite.

`verify_evidence.py` checks the complete file inventory, byte lengths, SHA-256
hashes, recorded source identity, current source-file hashes, and completed
execution status. To verify an older run after changing code, use the matching
source checkout. Verification establishes evidence consistency; it does not
independently establish the correctness of the experimental interpretation,
statistical efficacy, production readiness, or a general memory system.

## What each stage implements

| Stage | Implemented experiment | Question the evidence must answer |
| --- | --- | --- |
| 1. Single-cell parameter memory | Genuine optimizer updates; immutable tensor artifacts; isolated-process loading and parameter readout; frozen capacity sweep | How much written information is recovered, with what error and storage/read/write cost? |
| 2. Fixed multiple cells | Shared encoder, fixed local partitions, typed and literal-domain routing, trained text router, same-parameter-budget single-cell comparison | Does actual routing preserve a multi-cell gain, and how far is it from oracle routing? |
| 3. Typed meta network | Supplied episodic-to-semantic-to-procedural chains, compositional reads, no-edge and valid shuffled-edge ablations, exact chained retrieval | Does the specified connection structure help this task, and does any benefit survive strong retrieval comparison? |
| 4. Continued learning and maintenance | Appends, corrections, replay, revision lineage, revocation checks, and clean retraining after removal | Do updates improve current answers while preserving retained answers and preventing stale versions from serving? |
| 5. Split, merge, and consolidation | Trained child/merged models, routing migration, a selection-only structural decision, fixed-structure comparison, and candidate-search costs | Does the selected structure improve hidden reads after paying for its training, metadata, and maintenance? |
| 6. Bounded transfer diagnostics | Frozen settings on independent seeds and domain names, plus facts derived from a pinned repository registry | Does the same writer/reader procedure work in these additional conditions? Broader task and domain transfer remains open. |

The stage criteria are evaluated separately. Negative comparisons, failed
thresholds, and uneconomic structural changes are valid results and must remain
in the report. Neither unit tests nor a successful CLI exit turn these outcomes
into successful scientific qualification.

## Readout, data, and leakage boundaries

**The main parameter-readout task is recovery of previously written canonical
keys.** Training writes key-to-value associations. Readout passes `query.key` to
the encoder; different natural-language question templates therefore do not
constitute different effective model inputs. This demonstrates storage and
recovery of associations after a process boundary, not unseen-key prediction or
free-form question answering. The independent random target assignment cannot
be inferred from an unwritten key.

Natural-text routing is evaluated separately. `LearnedRouter` trains on writing
templates and training domain labels, and routes hidden text without reading its
target or oracle domain. `LiteralRouter` matches literal domain names in text;
it is a deliberately strong simple comparator. `TypedRouter` uses the supplied
domain and is the explicit typed/oracle route. Learned-router softmax scores are
raw scores, not calibrated confidence, and its zero default threshold does not
provide open-domain rejection.

Writing, selection, and test templates are distinct. All facts in a memory
recovery test may have been written. For structural decisions, selection and
test must additionally have disjoint effective read keys: the growth experiment
partitions sorted keys within each domain into separate selection and test sets.
It makes the structural decision before reading test outcomes. A different
sentence around the same key is insufficient protection against selection bias.

`read_parameters.py` is launched in a fresh `python -I` process with a strict
request containing artifact identity and keys, without events, targets, replay,
or an inherited in-memory model. After imports and request parsing, its Python
audit hook permits only the expected artifact file opens and records them. This
is a controlled reader-path check, not OS security isolation or proof against
hostile native code. It must not be described as a general security sandbox.

Corrections resolve to the current revision; deleted facts are excluded from
clean retraining. Serving guards can reject revoked keys or artifacts while raw
weights still produce a class. Such a guard is not weight unlearning, and clean
retraining without the removed records is not a proof of zero statistical
influence under arbitrary extraction attacks.

## Comparators, budgets, and uncertainty

The suite includes an untrained classifier, exact source lookup, lexical source
retrieval, single-cell parameter memory, and fixed multi-cell comparators where
applicable. Exact lookup is allowed to read authoritative events and can achieve
perfect recovery on the synthetic association task. That is an expected strong
baseline. The experiment does not establish an advantage over retrieval by
hiding keys or weakening the source store. Source payload, minimal lookup
storage, and parameter artifacts are separate quantities.

The exact and lexical batch timings include index construction. Exact lookup
also has separately measured index-build and prebuilt hot-read timings. Do not
compare the build-plus-read timing to a hot model read as if both were hot reads.

The matched constraint is the numerical tensor budget, including learned-router
tensors for the routed comparison; integer rank rounding is reported. Full
deployed-system budgets are **not equal**: manifests, routing/domain metadata,
source or replay payloads, lineage, and revocation state add bytes and work.
Interpret actual stored bytes and measured training/read/maintenance costs
alongside tensor counts. A tensor-only accuracy gain is not by itself a system
compression or economic gain. FLOP figures are operation estimates rather than
measured energy use, and local wall-clock timing is not a production latency SLA.

Report all capacity loads and independent seeds, paired differences against
single-cell and retrieval comparators, actual-versus-oracle routing gaps, and
structural candidate costs. Statistical intervals cluster by independent seed
or root episode. Repeated paraphrases of one written fact are not independent
replications. The small-seed intervals are exploratory; this run supplies no
independent future-calendar qualification.

The typed graph is supplied by the experiment. Edge ablation can demonstrate
use of that graph, but cannot establish learned topology, spontaneous cell-type
emergence, or spontaneous formation of a general memory system. Procedural
contracts and slot vocabularies are supplied scaffolding. Renaming synthetic
domains while using the same generator tests bounded reuse, not broad semantic
generalization. Repository category recall adds a real source but remains a
small classification diagnostic.

## Source identity and evidence layout

The inspected repository `main` baseline is
[`f8c9419df6ddeb36ff8b522a50219981fb8d9345`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f8c9419df6ddeb36ff8b522a50219981fb8d9345),
tree `15c9d6ea07bf3832de82825a6cc1e8c958dd3d45`. This identifies the architecture
and registry source, not the later commit executing this research package.

The real-source diagnostic derives mappings from
[`docs/modules/MODULES.json`](../../docs/modules/MODULES.json) at that baseline,
Git blob `e4a5965a06b0af917130bd929158e714684a91bc`, SHA-256
`be10ee569a0a12c94631e0d5f25e5ee627b337369e8bccf5b75f236c98d444a5`.
Each fact retains source path, record lineage, and content identity. Human label
names require the recorded external label catalog; those bytes are part of the
diagnostic, not knowledge silently contained in the class-index output.

Each run records its own executed commit and source-file hashes in
`source_identity.json`, its effective `protocol.json`, `environment.json`,
per-stage predictions/training/artifact evidence, `results.json`, and
`execution_status.json`. A completed run seals these files in `MANIFEST.json`.
Keep the original baseline, executed-source commit, and trained-artifact digests
distinct when citing results.

See [INTEGRATION.md](INTEGRATION.md) for how a future implementation can reuse
existing Hepta owners and contracts without changing their authority boundaries.
