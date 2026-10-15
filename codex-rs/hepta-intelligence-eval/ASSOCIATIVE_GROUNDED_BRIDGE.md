# Associative MemoryCell: observed-source / pretrained Encoder shadow

**Status: isolated research worker, not a production MemoryCell, source owner, semantic
reader, NDU evaluation or model-selection proposal.** Stacked on the existing
MemoryCell research PR. It does not replace `cognitive.store`, `cognitive.read`,
`memory.retrieval`, `learning.artifacts` or `neuron.runtime`.

## What this adds

The preceding synthetic `associative_cell_trial.py` shows a low-rank cue→value
optimizer and type split on generated numeric vectors only. This continuation
adds a deliberately narrower **grounded source / actual pretrained Encoder
bridge**, preserving that experiment and its existing test/CI surface.

1. `event_experience.py collect` executes the existing fixed subprocess program,
   emitting source events, public questions, hidden labels, worker observations
   and a checksummed input manifest. These are **authored controlled program
   observations**, not independent humans, longitudinal windows or external
   domain transfer.
2. The read-only source projection accepts only schema-valid events with source
   roots, scopes, explicit observed time and logical revision. Direct active
   **single-root** facts become trainable cue/value text. All corrected heads
   involving `supersedes` are excluded because V1 `Experience` has only one
   root. Conflicting heads are excluded. Every inspected root (including
   conflicts, retired events and later logical revisions) is conservatively
   bound to the proposed artifact for fail-closed withdrawal.
3. A single pinned pretrained text Encoder (`prepare.PINS["encoder"]`) runs in
   `eval` mode with no weight updates. A deterministic random JL projection
   yields small, normalized vectors. Exact model inventory, projection seed,
   width and matrix checksum are embedded in the Cell `encoder_identity`.
   Inputs that exceed the actual tokenizer's 256-token limit are rejected
   **before** encoder execution rather than silently truncated.
4. A separate `AssociativeCell` candidate per original source scope learns
   source-only cue→value associations with bounded SGD; raw cue/value examples
   are not exported as weights. Query-time memory access receives only the
   frozen encoded question, type, revision-time gate, scope and current root
   revocations. The candidate is saved and reloaded from its artifact before
   producing any prediction.
5. An existing, fully materialized `PersistentIndex` FTS5+cached dense view is
   built over the **same original source scope**. A fixed policy
   (`top_k=8`, `channel_k=32`, `lexical_weight=0.5`, `rrf_constant=60`)
   selects sources; existing `event_revision_closure.select_current` may
   answer only if it finds a complete, current, nonconflicting evidence chain.
   An explicitly privileged all-source closure is recorded as a ceiling.
6. Generation reads **only** `collection.json`, `sources.json` and
   `questions.json`; the original `labels.json` is deliberately absent from
   its input directory. The sealed journal includes every result and full
   source-derived candidate catalogue but no selected answer annotation.
   `review` then opens pinned original labels and scores the sealed predictions.

## Run

On a host with the existing pinned MemoryCell environment and *pre-staged*
Encoder weights, first collect the actual controlled observation set, then
stage the exact encoder through the existing `event_memory_trial.py encoder`
command (network staging is separate). Offline:

```bash
export PYTHONPATH=scripts/memory_cell
python -m unittest discover -s scripts/memory_cell -p 'test_associative_text_bridge.py' -v
python scripts/memory_cell/event_experience.py collect /tmp/observations
python scripts/memory_cell/event_memory_trial.py encoder /tmp/encoder-stage
mkdir /tmp/public-observations
cp /tmp/observations/{collection,sources,questions}.json /tmp/public-observations/
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python \
  scripts/memory_cell/associative_event_bridge.py run \
  /tmp/public-observations /tmp/encoder-stage/encoder /tmp/associative-results \
  --commit "$(git rev-parse HEAD)" --steps 192 --rank 4 --dimension 64
python scripts/memory_cell/associative_event_bridge.py review \
  /tmp/observations /tmp/associative-results /tmp/associative-review.json
```

Use a **new** result directory. The owned outputs from `run` are `cells/`,
`indices/`, `journal.json`, `manifest.json`; the reviewer writes only its new
`review.json`. Neither generates nor uploads source-modifying commits.

GitHub workflow:
`.github/workflows/hepta-associative-grounded-bridge.yml` runs a pinned
CPU-only model environment, executes isolated mechanics tests, creates real
subprocess observations, performs network model staging, executes the pretrained
shadow worker offline, and publishes exact SHA256 receipts. It does **not**
promote or serve any trained artifact. A hosted test receipt exists only when
that exact-head job has completed; workflow existence does not prove execution.

## Evaluation meaning and limits

A matched frozen candidate with the exact training parent's architecture,
seed, encoder, source scope and current revocation lineage is read with the
identical query. The job rejects parent-identity drift and separately reports
paired latent-MSE and catalogue top-1 gains over this **non-learning** control.
Learning-only benefit is not inferred from an untrained baseline alone; source
catalogue decode remains an external aid.

The parameter Cell returns a **latent vector only**. The reviewer computes
cosine/MSE against source-derived answer embeddings after original labels are
opened. A separate *candidate-catalogue* top-1 decoder ranks all source-only
values; this **uses an external value vocabulary** and is *not* parameter-only
natural-language answer generation. Corrected answers excluded from the Cell
have an explicit `target_in_source_catalogue=false` coverage failure rather
than fabricated embeddings or magically resolved ancestry.

The indexed hybrid returns source-backed exact identifiers and original source
IDs only after revision/multihop closure. Its historical correctness is compared
with controlled observations, not independent entailment annotations. The
privileged full-source comparator is an upper-bound diagnostic, not an eligible
retrieval policy. It may use more source work than the bounded index.

There are only 16 authored controlled tasks, eight calibration and eight test,
from a single test-program family. Training intentionally learns from the
**same past source scopes subsequently queried**: this tests parameter retention
of admitted source facts, not independent source-family generalization.
Do not label the set as 16 independent human or future observations.

All outcomes must be reported even when the parametric Cell fails. In particular:
`pretrained_reader_executed=false`, `strong_tuned_rag_executed=false`,
`independent_semantic_adjudication=false`, `superiority_claim=false`, and
`production_accepted=false` are non-negotiable for this experiment.

Actual storage accounting includes model and index artifacts, source text,
shared pretrained weight files and approximate projected cache; observed CPU
resources are reported by the hosted job. That accounting is not a complete
network-scale total-cost-of-ownership measure, and a dense/FTS ranker without
a real Reader is not yet a qualified strong RAG benchmark.

## Next research gate

A genuine general Memory system claim still requires the matched Reader gate
(adequate evidence/insufficient evidence/removed premise), independent semantic
checking, source-family and chronology holds, corrected/multihop memory contract,
artifact-only clean-process **language** readout, independently tuned cached
hybrid+graph+temporal RAG, prospective future windows, full lifecycle cost,
negative-transfer and revocation/rebuild testing, and graph edge/split lesions
under equal total parameters and compute.

The higher-rank type-split mechanics remain in the preceding synthetic probe;
**this bridge does not claim learned Cell-type or Meta Network specialization**.
