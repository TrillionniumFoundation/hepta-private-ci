# MemoryCell v2: pretrained features, typed tasks and capacity pressure

This executable research package follows the six-stage v1 experiment in
`../memory-cell-research`. It keeps the v1 source and evidence unchanged. The
frozen protocol, actual numerical training, saved tensors, hidden predictions,
fresh-process reads and complete cost ledgers are the acceptance evidence.
Finishing an experiment does not mean its scientific gate passed.

## What is implemented

| Component | Actual behavior | Scope of the claim |
| --- | --- | --- |
| Pretrained base | Pinned official quantized MiniLM ONNX, attention-mask mean pooling, L2 normalization, 384 features | Frozen sentence features; transformer weights are not fine-tuned |
| Memory cell | A real trained `tanh(XA)B` small model, saved and reloaded through a checked artifact format | Written associations or learned classification patterns; no generative language-model claim |
| Typed addressing | Explicit scope and version metadata, learned task/cue routing, separate literal and typed baselines | Known schemas and lexical cues; unseen synonym behavior is measured separately |
| Real typed memory | Module attributes, sampled file history, complete primitive JSON-schema rules | Three task families from one pinned repository source |
| Composition | Parameter-read outputs become inputs to the next typed cell; rule interpreter executes unseen inputs | Supplied task schemas and ports, with removed and permuted edge controls |
| Structural learning | Capacity pressure, bounded split/merge search, actual children and distillation, generation-bound migration | Given domains; selection-only adoption; every attempted candidate is charged |
| Maintenance | Source lineage, revocation guards, stale snapshot rejection, clean consolidation | Full retraining after contaminated inheritance; not certified selective unlearning |
| External patterns | Iris, wine and handwritten digits through one fixed numeric learner | Three independent source datasets; ordinary classification is not general memory |

The complete numerical learner and lineage machinery are imported from v1.
The v2 evidence inventory binds those dependency bytes as well as every v2
executable, fixed source snapshot, model identity, dependency pin and protocol.
The v2 adapter format binds the actual feature encoder. A MiniLM artifact is
never mislabeled as a v1 hash-encoder artifact.

## Runtime and pinned base

Use Python 3.12 with the exact packages in `requirements.txt`. Keep the runtime
environment outside the repository so it cannot enter the source inventory:

```bash
python3 -m venv /tmp/hepta-memory-v2-env
/tmp/hepta-memory-v2-env/bin/python -m pip install -r qualification/memory-cell-v2/requirements.txt
/tmp/hepta-memory-v2-env/bin/python qualification/memory-cell-v2/download_base.py /tmp/hepta-memory-minilm
```

`MODEL_SOURCE.json` binds the official
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)
revision and the six exact files used. The quantized model has SHA-256
`b941bf19f1f1283680f449fa6a7336bb5600bdcd5f84d10ddc5cd72218a0fd21`.
The download helper validates file lengths and hashes. Existing conflicting
files are rejected. The actual tokenizer and ONNX session consume the bytes
that were just verified, rather than reopening unchecked paths.

The research adapters use float64. The base ONNX is quantized. These are separate
precision choices and both physical storage costs are reported. There is no GPU
requirement. The pinned real and external dataset snapshots are included under
`sources/`, with source references and licenses.

Each text is tokenized and executed independently with native batch size one.
The development integration check exposed changed predictions when the original
quantized encoder regrouped otherwise identical queries into different batches.
The corrected encoder binds this independent-input contract in its manifest;
real tests require exact feature equality across batching and input ordering.
The original failed run and its diagnosis remain in the development evidence.

## Execute the frozen study

Commit all executable sources and source data before a formal run. The runner
refuses uncommitted or modified source bytes. Formal seeds are
`211, 223, 227, 229, 233`; development seeds are `8001, 8003`. Formal outcomes
must not be used to choose hyperparameters for that same evaluation.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /tmp/hepta-memory-v2-env/bin/python qualification/memory-cell-v2/run_study.py \
  --base /tmp/hepta-memory-minilm \
  --output qualification/memory-cell-v2/results/my-frozen-run

/tmp/hepta-memory-v2-env/bin/python qualification/memory-cell-v2/verify_evidence.py \
  qualification/memory-cell-v2/results/my-frozen-run
```

`--stage routing|real|growth|external` runs one component. A partial stage run
does not qualify all six stages. `--development` permits uncommitted sources and
uses only development seeds. Every output directory must be new. Failed runs
retain their error, completed components, source identity and file manifest;
`verify_evidence.py --allow-failed` checks their integrity without calling them
successful.

The runner prints stage transitions so long CPU runs can be monitored. The
output includes `protocol.json`, `source_identity.json`, `source_snapshot.zip`, `environment.json`,
`execution_status.json`, raw component outputs, `results.json` and
`MANIFEST.json`. The final manifest seals every output file except itself. It
does not provide a cryptographic proof that a measurement was honest; the
committed manifest digest and reviewable evaluation code provide the audit
boundary.

`source_snapshot.zip` preserves every executed source/data byte, including for
uncommitted development failures. The verifier also checks that snapshot against
the source inventory. Graceful Python failures and interrupts are sealed; a
forced kill, power loss or failed storage write cannot guarantee a final seal.

For the reproducible summary and static figure, install the optional
`requirements-report.txt`, then run:

```bash
MPLCONFIGDIR=/tmp/hepta-memory-mpl \
  /tmp/hepta-memory-v2-env/bin/python qualification/memory-cell-v2/analyze_results.py \
  qualification/memory-cell-v2/results/my-frozen-run \
  --output qualification/memory-cell-v2/analyses/my-frozen-run
```

## Parameter-only read interface

Run `read_parameters.py` in a fresh isolated Python process with a request file:

```json
{
  "schema": "memory-cell-v2.read.v1",
  "artifact": "cells/semantic",
  "base_path": "/tmp/hepta-memory-minilm",
  "texts": ["Memory type semantic. Key module.owner:example. Revision 1."],
  "expected_encoder_digest": "<digest from the saved adapter>"
}
```

```bash
/tmp/hepta-memory-v2-env/bin/python -I qualification/memory-cell-v2/read_parameters.py request.json
```

Relative paths are resolved against the request file's directory. The request
has a closed five-field schema. Targets, history, examples and extra fields are
rejected. Research scope is fixed. The reader returns class IDs, uncalibrated
softmax scores, actual artifact and encoder digests, its PID, timings and the
observed file-open inventory. It loads no source-answer map. Dependencies and
the pinned model identity are loaded before the file-access audit boundary;
this Python audit hook is not an operating-system sandbox.

Label/rule catalogs decode the class IDs in the outer evaluation. The explicit
address index selects a timestamp/revision and stores no answer values. Both
are real parts of the deployed system and count toward storage. The reader
does not claim that temporal selection or rule execution lives in the weights.

## Evaluation rules that prevent misleading success

- Written facts may be training material; hidden queries evaluate later reads,
  new temporal cutoffs or new procedure inputs. This is different from learning
  facts that were never written.
- Selection and hidden effective keys are disjoint. Identical external feature
  rows are grouped into the same split, and normalizers fit training rows only.
- The single-cell comparison receives at least the multi-cell plus learned
  router parameter budget. Strong exact, literal, typed, single and kNN
  baselines remain visible.
- Procedure rule-identity recovery is reported independently from final
  booleans. A wrong rule can accidentally produce the right boolean.
- Every composition task is reported separately. A three-example commit-owner
  chain cannot be hidden inside a much larger schema-validation task.
- Full cold base storage and shared-base incremental storage are separate.
  Source/replay data, address metadata, catalogs, rejected candidates, route
  migration and consolidation are charged explicitly.
- Growth uses the same expected query count per update. Its primary accuracy is
  the equally weighted update mean. The sample-weighted stream metric is also
  reported. Resource prices are explicit utility assumptions, not currency.
- Repeated initialization/split seeds do not turn a single repository or three
  fixed classification datasets into many independent domains.
- Passing an integrity check, a unit test, or a deletion guard does not prove
  model efficacy, weight-level erasure, autonomous topology or general memory.

## Mechanism tests and formatting

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MEMORY_CELL_BASE=/tmp/hepta-memory-minilm \
  /tmp/hepta-memory-v2-env/bin/python -m unittest discover \
  -s qualification/memory-cell-v2/tests -v
```

Without `MEMORY_CELL_BASE`, the real pretrained reader tests are explicitly
skipped; such a run is insufficient to claim the pretrained reader passed.
This work's validation sets that variable and executes the real reader tests.
Follow repository instructions: tests precede final formatting; do not rerun
the test suite after `fmt`. A frozen scientific execution and byte verification
are distinct from rerunning the unit suite.

The production ownership and authority boundaries described in
[`../memory-cell-research/INTEGRATION.md`](../memory-cell-research/INTEGRATION.md)
still apply. This package does not publish a production cell or turn predicted
values into authoritative source events.
