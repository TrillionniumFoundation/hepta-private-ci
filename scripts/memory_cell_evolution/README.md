# Typed memory evolution research tools

This directory implements source-fenced local population transactions and bounded
memory experiments. It is research code, with no production activation or natural
future-task qualification.

## Dependencies and execution source

The owner/service/decoder imports use the existing `scripts/memory_cell*` modules.
Edge budgeting additionally requires the separately published sibling
`scripts/memory_cell_budget/{budget_ledger,artifact_inventory}.py`; it is not copied
into this directory. The edge CLI accepts that dependency directory explicitly.
The final integrated tree must include both source branches before running the
edge boundary tests or the edge trial.

Frozen experiment drivers deliberately require baseline
`429894ac8e0818102cfdea4ad47a56e4583b2902`. To reproduce the recorded runs, use that
baseline checkout with the exact unformatted source capsule inside the evidence
archive. The readable modules here were mechanically formatted with full AST
equivalence; their file hashes differ from the executed source pins. Do not
silently substitute them under an old source hash.

## APIs and trust boundary

`TopologyStore(root, scope, provider, owners)` accepts a current source provider
and `ActualOwners` backed by real parameter checkpoints. Operations use prepare,
commit and abort, with immutable generations and stable cell identities. A split
requires a complete disjoint support partition. A merge requires a verified
clean replay candidate. Rollback creates a new generation and rechecks the current
source frontier; it cannot revive a revoked parameter ancestor.

The graph executor permits at most two actual reader callbacks. A metadata
resolver supplies the typed key, source roots and prompt, never a source answer.
The first raw decoder output becomes both transition-policy input and literal
context in the second prompt. The next-cell decision is persisted before that
second callback. Source and topology fences are checked around execution.

The source provider is a trusted local research authority. This API is not native
HNMF attestation, cross-host consensus, semantic proof of a generated answer or
physical machine unlearning. Old checkpoints are retained for audit.

## Completed evidence

See `qa/stem-bakeoff/evidence/20261024-memory-longitudinal/` and
`qa/stem-bakeoff/evidence/20261024-memory-edge-lifecycle/` after the evidence stages
are applied. Longitudinal ran all 5,184 optimizer updates and 558 raw rows; all
three seeds failed the combined preregistered continuous quality gate. Retention
means service accuracy after fresh-base replay, not continuous training of one
adapter.

The edge experiment ran a randomly initialized tiny decoder population, 1,024
updates, 400 router updates and 75 actual reads. Learned-next-cell scored 1/6,
direct parameter access 2/6 and exact source lookup 6/6. All final queries concern
the same six stored entities under another wording. The no-edge arm returns the
hint cell's output although the task asks for a color; it is a path ablation,
not the strongest single-cell control.

Split, merge and rollback followed a fixed sequence and fixed source partition.
The split clones an admitted checkpoint, and merge reuses its already joint
replay. There is no pressure-triggered autonomous controller, learned fission or
capacity advantage claim. The final fresh replay after withdrawal admitted a raw
read but answered `warm` for the registered `cool` value; this miss is retained.

## Validation and formatting

Before final formatting, the repository-relative publication copy passed 22
behavior regressions across topology, longitudinal scheduling, live dispatch
boundaries and budgeting. The owner tests validate two-float safetensor fixtures;
they do not load a pretrained model, fit an adapter or generate text.

The first publication fixture used sibling symlinks and was correctly rejected by
the resolved import-path guard. Its failed log is retained. Byte-matched physical
dependency copies fixed the test environment without weakening the guard or
changing production source. All 22 tests then passed. Ruff 0.15.13 formatting
preserved the full AST of all 25 Python modules. No tests were run after that final
format step. Original experiment outputs and frozen source capsules are unchanged.
