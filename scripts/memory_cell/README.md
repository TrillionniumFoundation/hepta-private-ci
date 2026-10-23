# Parametric memory cell research

This directory implements a source-trained memory cell over a real autoregressive
decoder. A shared frozen base supplies language ability; private LoRA parameters
store source-derived updates. Reads use the decoder's unconstrained greedy
generation. Checkpoints can be saved, verified, reloaded in a fresh interpreter,
and managed by a persistent local owner.

**Research status: `production_accepted=false`.** Local development recalled
16/16 registered facts, versus 0/16 with the adapter disabled and 0/16 with its
tensors shuffled. Confirmation is pending. These results support a narrow
parameter-memory mechanism; they do not establish a compression advantage, a
general memory system, autonomous evolution, or production readiness.

## Model and reproducible commands

Run commands from the repository root. The reference runtime is Python 3.12,
CPU PyTorch 2.5.1, and the versions in [requirements.txt](requirements.txt).
The model is
[`HuggingFaceTB/SmolLM2-135M-Instruct`](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct/tree/12fd25f77366fa6b3b4b768ec3050bf629380bac),
pinned to revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`.

[prepare_parametric.py](prepare_parametric.py) checks all six expected files
against publisher sizes and Git/LFS digests, and records independent SHA-256
digests. The weights are 269,060,552 bytes, SHA-256
`5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
Unexpected files, including an additional chat template, are rejected. The
acquisition receipt is written beside the model directory.

```bash
python3.12 -m venv .venv-parametric
source .venv-parametric/bin/activate
python -m pip install --only-binary=:all: \
  --index-url https://download.pytorch.org/whl/cpu 'torch==2.5.1'
python -m pip install --only-binary=:all: -r scripts/memory_cell/requirements.txt
python -m pip check

python scripts/memory_cell/prepare_parametric.py \
  --output .artifacts/smol135m --download

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s scripts/memory_cell \
  -p 'test_parametric_*.py' -v

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  python scripts/memory_cell/parametric_trial.py \
  --model .artifacts/smol135m --output .artifacts/parametric-development \
  --phase development

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 \
  python scripts/memory_cell/parametric_trial.py \
  --model .artifacts/smol135m --output .artifacts/parametric-confirmation \
  --phase confirmation
```

Each trial requires a new output directory. Freeze the Python source and recipe
before confirmation; the trial records source hashes before and after execution.
Confirmation uses a separate fixed cohort and rejects CLI overrides of steps or
learning rate. Its default recipe is rank 8, model seed 2718, 512 optimizer steps,
and learning rate 0.001. Development uses cohort seed 413; confirmation uses 95873.
A failed confirmation mechanism gate exits nonzero. A successful gate still does
not grant production activation.

The [shadow workflow](../../.github/workflows/hepta-parametric-memory-shadow.yml)
checks out the exact source SHA, installs the pinned runtime, runs regressions,
acquires the model, and executes confirmation. It retains reports and adapter
artifacts without uploading the base model. It does not alter a production gate.

## Write, read, save and reload

[SourceMemoryCell](parametric_model.py) accepts a bounded list of facts. Every fact
has exactly `scope`, `entity`, `relation`, `value`, and `source_digest`; scope must
match, `(entity, relation)` must be unique, and each digest must be 64 lowercase
hexadecimal characters supplied by the external source ledger. Training templates
can interpolate only `{entity}` and `{relation}`. Source values provide completion
targets, with prompt tokens masked from the loss.

```python
# Run with PYTHONPATH=scripts/memory_cell in the pinned environment.
import json
from pathlib import Path

from parametric_model import SourceMemoryCell

facts = json.loads(Path("source-facts.json").read_text(encoding="utf-8"))
scope = facts[0]["scope"]
allowed_roots = {fact["source_digest"] for fact in facts}
cell = SourceMemoryCell(".artifacts/smol135m", rank=8, seed=2718)
cell.reset(scope)
receipt = cell.fit_sources(
    facts, steps=512, learning_rate=0.001,
    templates=["What is {entity}'s {relation}?"],
)
manifest_sha256 = cell.save(".artifacts/example-cell")
del cell

reader = SourceMemoryCell(".artifacts/smol135m", rank=8, seed=2718)
reader.load(
    ".artifacts/example-cell",
    expected_manifest_sha256=manifest_sha256,
    scope=scope, allowed_roots=allowed_roots, revoked=set(),
)
rows = reader.generate(["Which color did we assign to Alice?"])
```

The example assumes Alice is a source entity. In an application, obtain allowed
roots and current revocations from the host's source authority, and retain the
expected manifest digest independently of the candidate directory.

Writes run actual AdamW updates against decoder loss and record visited sources,
token work, optimizer steps, parameter bytes, loss history, and frozen-base
integrity. `completion_ce` is the default objective; `source_margin` is available
as a source-only full-decoder objective. Writes are bounded to 128 facts and 4096
steps; prompts are capped at 192 tokens without truncation. Accepted source values
plus EOS must fit the 16-token generation budget. Failed writes quarantine the
cell. Global optimizer hooks are rejected because they could mutate another cell.

Reads receive question strings, use the same prompt for adapter and base controls,
and return raw text, token IDs, prompt hashes and `evidence=[]`. There is no
candidate-answer vocabulary, classification head, retrieval payload, or answer
cleanup. Inference freezes parameters and verifies that the base and adapter did
not change. Source values are not part of the fresh reader's JSON input.

`save()` binds adapter tensors, configuration, scope, provenance roots and measured
training receipt in `lineage.json`. Its returned manifest digest is checked by
`load()`, along with model compatibility and allowed/revoked roots. Saving flushes
the files and, on POSIX, the snapshot and parent directories with `fsync`;
unsupported directory flushing is explicitly recorded on Windows. This is a
write-flush guarantee, not a power-loss recovery proof. Weight ancestry is recorded
separately from the owner's version-pointer predecessor.

## Evidence and what it measures

The recovered development journal `development-recovery-001/result.json` records:

| Reader control | Raw exact matches | Interpretation |
| --- | ---: | --- |
| Trained adapter | 16/16 | Recall under a query template excluded from source training |
| Same prompt, adapter disabled | 0/16 | Frozen base alone did not recall these assignments |
| Same prompt, shuffled adapter tensors | 0/16 | Destroying the learned tensor arrangement removed recall |

The recovered training manifest is
`00cf0b82fb117a5e01a0d57e7c9d6673883f97db860e53a8e2dea0d7c80ad57a`.
An environment interruption occurred after training; the saved checkpoint was
reused and training was not repeated. This recovery result is development
evidence, not a completed confirmation report. Final confirmation metrics must be
reported from its own `result.json` and exact source identity.

The cohort contains 16 entity/color assignments drawn from eight predefined,
single-token values. The value assignments carry at most 48 bits before accounting
for cohort constraints; entities, relations, scope and provenance require additional
storage. New query wording tests recall of already written facts. It does not test
unseen-fact acquisition, independent natural memories, long values, or arbitrary
semantic generalization. Eight global values are fixed before source sampling and
are never supplied as an inference-time answer lexicon.

[parametric_metrics.py](parametric_metrics.py) adds two post-generation checks:

- **Binding specificity:** full-vocabulary next-token logits under identical
  prompts, with adapter disabled and enabled. Each distinct-source pair measures
  both correct-versus-swapped-value margins. Targets are used only after forward
  computation for measurement; this metric has no training or selection authority.
- **Executed key/value baseline:** real in-memory SQLite writes and SQL reads,
  complete entity/relation word-boundary parsing, unresolved-query records,
  database page bytes and write/read time. Accuracy comes from scoring its raw
  outputs. SQLite page bytes are not process RSS or disk durability cost.

The trial records shared base disk/tensor bytes, private adapter/checkpoint bytes,
optimizer tensors and original source JSON bytes. The full system must also retain
and charge for its source ledger, provenance, owner database, router, inactive
versions, replay data, candidate-search work and runtime memory. Parameter storage
does not make those costs disappear. No compression advantage is claimed over the
executed SQLite baseline.

## Local evolution, ownership and withdrawal

| Component | Implemented role | Boundary |
| --- | --- | --- |
| `parametric_evolution.py` | Source-question clustering; saved continue/split candidates; source-derived selection wording | Two local slots, deterministic policy, no final-test-driven selection |
| `parametric_network_trial.py` | Route queries to saved cells and execute through owner admission | One physical host; no distributed consensus |
| `parametric_owner.py` | SQLite CAS publication, generation checks, persisted observed withdrawal frontier, pre/post-call barriers | Host supplies source authority; the module does not authenticate it |
| `parametric_lifecycle_trial.py` | Real correction, descendant withdrawal, restart checks and clean-base replay | Confirmation must measure recall and rejection behavior |

Continue and split each train two private adapters from the same verified parent
with equal optimizer steps and private parameter budgets. Input tokens and search
costs are measured separately; equal FLOPs are not assumed. Final query wording is
kept out of candidate selection. A split is an experimental option, not a promised
improvement or evidence that a general network emerges spontaneously.

Every child retains all learned ancestor roots. Specializing on a subset does not
erase the parent's training history. Withdrawing an inherited root therefore
blocks every descendant that carries it before inference. A failed request cannot
erase an already observed withdrawal; the persistent owner rejects frontier
rollback and same-epoch forks across restarts.

Deletion recovery resets to the frozen base and replays only the remaining allowed
facts. The receipt must show `initialization="frozen_base"`, no learned parent, no
inherited roots, and the exact replayed roots. This is clean-base reconstruction,
not certified machine unlearning: neither zero statistical influence nor guaranteed
abstention on deleted/unknown questions is established. The trial records raw
unknown-query behavior without promoting it to an erasure claim.

Fresh-process readers use closed JSON transport and reject extra source/gold/
lexicon fields before model construction. A fresh interpreter and separate working
directory are **not an OS sandbox**: the process still runs with the host's ambient
filesystem and network privileges. The local owner is not a distributed consensus
protocol or a production authorization service.

## Historical code reuse

The following 11 dependency files were mechanically carried forward from commit
[`c64e0ade0d2599841554b3ff91200d188d7e7671`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/c64e0ade0d2599841554b3ff91200d188d7e7671).
The carry-forward removes historical `__future__` annotation directives where
needed for this checkout's conventions; formatting may change line layout. It is
not a new implementation or new experimental evidence:

```text
pretrained.py
native.py
sessions.py
tensor_contract.py
source_completion_loss.py
experience_inference.py
grounded_protocol.py
citation_audit.py
source_binding_margin.py
event_projection.py
requirements.txt
```

These modules provide the existing decoder/LoRA reader, checkpoint validation,
source-completion objectives and frozen inference helpers. The `parametric_*`
modules add the bounded source-memory API, measured trials, local ownership and
evolution around that reused foundation.

## Review and landing order

The branch spans several review units. The smallest coherent first stage is the
**111 changed-line QA withdrawal/frontier repair** in
`qa/stem-bakeoff/cell_evolution_snapshot.py` and
`qa/stem-bakeoff/test_cell_evolution.py`: reject revoked query sources and retain
observed withdrawal frontiers even when an operation is rejected. Its regressions
can land independently of the decoder experiment.

Review the remaining work in dependency order:

1. Mechanical restoration of the 11 historical dependencies, checked against their
   source commit.
2. Bounded decoder write/read/save/reload behavior and its real tiny-model tests.
3. Persistent owner CAS/frontier boundaries and process transport controls.
4. Source-only split selection, routed reads, correction and clean replay.
5. Frozen protocol, executed baselines, shadow workflow and retained confirmation
   artifacts with their exact source hashes.

Keep substantive review stages within the repository's change-size guidance where
practical, splitting at real API/dependency boundaries. Retain behavior tests with
the behavior they protect. Do not describe the complete branch as a small change,
or treat passing research gates as permission to activate production memory.
