# Short publisher compositions and conditional policy learning

This opt-in experiment uses existing byte-bound EvidenceBundle, FrozenBundleReader,
run_reader, and FrozenMemorySession components. It does not modify HNMF authority,
production selection, current source owners or the existing reviewed_bundle schema.

## Original evidence, not a fabricated reviewer

QASC (Khot, Clark, Guerquin, Jansen and Sabharwal, AAAI 2020) supplies original
fact1/fact2/combinedfact and answer annotations. Its CC-BY release is retained with
attribution. The downloaded tar MUST be 1,616,514 bytes with SHA-256
`a7b3f2244f768974c609fd621346c931a72715609f171cb5544fc1da2a2ad55c`, as independently
recorded in historical huggingface/datasets 1.18.4 metadata. Archive locations
are interchangeable only when those exact bytes match. No tar extraction writes
outside the destination. Original train/dev census and raw files are preserved.

Before any model runs, deterministic selection freezes 64 training questions,
eight reader-capability questions, eight transfer questions and eight retention
probes. Exact/case/whitespace-shared fact or question roots across these cuts are
excluded and recorded. This does not establish semantic independence. Noise is
shared within each phase; individual question IDs are NOT independent samples.
These are public science QA examples, not new observed personal histories.

Each input uses the original question stem WITHOUT answer options. Answers and
combinedfact are in a separate post-generation scoring file. This is free-answer
diagnostic token F1, not official QASC multiple-choice accuracy. Both facts, each
single-fact omission, reversed order, two noise orders, no evidence, and two fixed
lexical retrieval controls form nine matched conditions. An omitted fact does not
relabel the world question unanswerable. Noise can contain other useful facts and
is not certified irrelevant. Source timestamps reflect actual local download,
not fact valid time, temporal supervision or independently attested observation.

Publisher composition labels are stronger than whole-session IDs but are NOT an
independently verified minimal sufficient set. The strict reviewed_bundle.py
interface remains for externally reviewed requirements; this importer deliberately
does not fabricate reviewer IDs, review times, necessity claims or signatures.
No >=99% semantic citation claim can be issued by this experiment.

## Frozen reader precondition

All three pinned SmolLM2 tiers (135M, 360M, 1.7B) use the existing bundle reader:
2,048 actual prompt tokens, 64 generation tokens, identical template and no LoRA.
Complete context overflow stays unavailable, never a silently shortened context.
Every original answer and actually delivered source is persisted before scoring.

The predeclared DEVELOPMENT screen requires a complete eight-question census,
mean full-pair F1 >=0.6, reversed-pair F1 >=0.6, and full-pair minus empty-context
F1 >=0.1. It is deliberately distinct from production qualification or statistical
significance. Failed readers are reported; their policy optimizer and final task
reads are NOT executed. Do not lower the screen after seeing results.

Only a passing reader permits the eight-scalar sequential selection policy to
train. It optimizes publisher support membership using query overlap, uncovered
query terms, bridge overlap, redundancy and length. This is not a semantic
non-entailment classifier. All conditional selection passes and training roots are
counted; no answer text or combinedfact is consumed by the optimizer. The exact
JSON numeric artifact is saved and reloaded before any final task exposure.

## Frozen consumption and interpretation

Transfer reuses FrozenMemorySession. A baseline and learned policy share the same
fixed sentence corpus and frozen reader. Policy/source bytes commit before the
query payload is exposed to either session; query-time training is zero. Actual
wall-clock order is recorded but is NOT a true prospective calendar window: all
questions and facts existed in the public source before this experiment.

The fixed baseline is lexical set selection over this controlled corpus, not the
17M-sentence official corpus or an independently tuned strong hybrid RAG. The
retention group is a disjoint held-out task probe, not proof of old deployed-agent
ability preservation. Current-source revocation and reopened result replay are
exercised without regenerating answers. These checks do not deploy a production
node, create independent snapshots or authorize a serving switch.

Run the read-only hepta-memory-composition-evidence workflow. The collector checks
complete raw/scored identity, model/data pins and the conditional learning screen.
A failed research hypothesis is retained even when code execution succeeds.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_composition_*.py' -v
python3 scripts/memory_cell/composition_evidence.py DATA --source-commit COMMIT_SHA
HEPTA_MEMORY_TESTED_COMMIT=COMMIT_SHA HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/composition_trial.py DATA MODEL_DIRECTORY NEW_OUTPUT
```
