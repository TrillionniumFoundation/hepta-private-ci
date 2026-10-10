# Short publisher compositions and conditional policy learning

This opt-in experiment reuses byte-bound EvidenceBundle, FrozenBundleReader,
run_reader and FrozenMemorySession. No HNMF authority, production selection,
source owner, default serving contract or reviewed_bundle schema changes.

## Original evidence is not a fabricated reviewer

QASC (Khot, Clark, Guerquin, Jansen and Sabharwal, AAAI 2020) supplies original
fact1/fact2/combinedfact and answer annotations. Its CC-BY release is retained
with attribution. The archive MUST be 1,616,514 bytes with SHA-256
`a7b3f2244f768974c609fd621346c931a72715609f171cb5544fc1da2a2ad55c`, as recorded in
historical huggingface/datasets 1.18.4 metadata. Mirror locations are accepted
only when those exact bytes match. No tar extraction writes arbitrary files.
Original train/dev census and raw files are preserved.

Before any reader execution, deterministic selection freezes 64 training
questions, eight capability questions, eight transfer questions and eight
retention probes. Shared normalized facts/questions are excluded and recorded.
This does not certify semantic independence: noise is shared within each phase,
and distinct question IDs do not establish independent samples. These are public
science QA examples, not newly observed personal memory or deployment data.

Profile v2 preserves the question stem AND ALL eight original answer options in
original order. It asks for the answer text rather than a bare letter. The answer
key and combinedfact remain separate, read only for post-generation QA scoring
or explicitly admitted TRAIN support membership. The model is never told which
option is correct. Changing the answer key does not change the input. The first
v1 stem-only projection omitted original question context and is retained as a
historical, different diagnostic profile, not silently relabelled as v2. This
input correction was made after inspecting published questions, not after
choosing a winning model from generated test scores. The diagnostic remains
answer-text token F1, not an official multiple-choice leaderboard score.

Both facts, each single-fact omission, reversed order, two noise orders, no
evidence, and two fixed lexical retrieval controls form nine matched conditions.
An omitted fact does not relabel the world question unanswerable. Noise can
contain useful facts and is not certified irrelevant. Source times are actual
local download times, not fact valid times or independent future observations.

Publisher annotations are NOT independent minimal sufficient evidence. Inspection
already found potentially redundant facts and erroneous content (for example,
the original sentence equating heat and temperature). No such row is rewritten
or deleted after observing a model score. The existing reviewed_bundle.py remains
the interface for genuine external necessity/sufficiency reviews. This importer
does not fabricate reviewer identities, timestamps, necessity judgements or
signatures. Unknown semantic citation precision is null, not 99% or 100%.

## Frozen reader precondition

All three pinned SmolLM2 tiers (135M, 360M, 1.7B) use the same bundle reader:
2,048 actual prompt tokens, 64 generation tokens, identical template and no LoRA.
Complete-context overflow stays unavailable; evidence is never silently shortened.
All raw answers and actually delivered sources persist before QA scoring.

The predeclared DEVELOPMENT screen requires the complete eight-question census,
mean full-pair F1 >=0.6, reversed-pair F1 >=0.6, and full-pair minus empty F1 >=0.1.
It is a research precondition, not a semantic reliability or production proof.
Failed readers are reported; their policy optimizer and final task reads are NOT
executed. Do not lower this screen after seeing results. No causal claim that
model size alone caused a difference is made by this matrix.

Only a passing reader permits the eight-scalar sequential policy to train. The
objective is publisher support membership using query coverage, bridge overlap,
redundancy and length, not semantic non-entailment. All training roots and the
conditional selection passes are counted. No reference answer text or combinedfact
enters this optimizer. Exact numeric JSON is saved and reloaded before final tasks.

## Frozen consumption and interpretation

A fixed baseline and learned policy share the same controlled sentence corpus
and frozen reader in FrozenMemorySession. Source/policy bytes commit before each
query payload is exposed; query-time training is zero. Actual execution ordering
is recorded, but it is not an independently observed prospective calendar window.
All questions/facts were public before the experiment.

The baseline is lexical set selection over a controlled corpus, not the official
17M-sentence corpus or independently tuned strong RAG. The retention group is a
held-out task probe, not proof of old deployed-agent skill preservation. Current
revocation and reopened-result replay are exercised without regenerating answers.
No production hosts, independently accepted snapshots or serving switches result.

The read-only hepta-memory-composition-evidence workflow checks the complete
regression suite, repository formatting, exact inputs and actual frozen-reader
execution. The collector rechecks raw/scored identity, evidence delivery and the
conditional learning screen. Failed research outcomes remain valid observations.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_composition_*.py' -v
python3 scripts/memory_cell/composition_evidence.py DATA --source-commit COMMIT_SHA
HEPTA_MEMORY_TESTED_COMMIT=COMMIT_SHA HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/composition_trial.py DATA MODEL_DIRECTORY NEW_OUTPUT
```
