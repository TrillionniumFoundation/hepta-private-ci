# Durable private-head training owner

This cut adds `SemanticTrainingOwner` around the existing experimental
`SemanticComponent.propose`. The serving head and frozen shared provider remain
unchanged; a trained head is retained as a separate compatibility-bundle successor.
The owner grants no native adoption, signing, Root or production authority.

## Durable operation and recovery

Before the encoder or optimizer runs, one SQLite transaction retains the exact
operation, source bundle/component, objective, budget, input/target bytes,
hyperparameters, candidate identity, evaluation profile and holdout commitment.
Completion exports create-only canonical result bytes, fsyncs the file and parent
directory, then commits the same result. Ordinary exact retries read completion.
Pending operations never invoke training again. Explicit recovery reads the original
export; absent, changed or inconsistent material remains unresolved. Failed attempts
retain measured owner costs and available original training receipts.

The implementation requires POSIX directory fsync and trusted local SQLite/result
custody. It provides no defense against an operator forging that custody. Holdout
commitment hashes do not establish independent data, evaluator identity or label
secrecy. Training uses the original full-batch SGD; this cut adds no replay policy.

## Validation and source attribution

Before Ruff, 27 tests passed: nine training-owner parents, 13 existing semantic
parents and five bundle parents. Real subprocess exit covers both interruption
inside the encoder and interruption after export but before completion. Tests also
cover linear/low-rank material, immutable service parameters, exact recovery,
changed requests, missing exports, original receipt metadata and measured costs.
Two new regression parents fail against the preserved precursor module; their
subcase/assertion failures are not separate independent runs.

Ruff 0.15.13 then formatted both files with equal Python ASTs. No behavior tests ran
after formatting. `semantic-training-v2-provenance.json` records exact tested/final
hashes and log hashes. The earlier 25-test precursor record predates its final
POSIX-only test declaration; it is not attributed to the corrected source.
Any real MLX precursor run remains separately identified and does not qualify this
corrected cut. Ordinary seven-stage owners, independent holdout/evaluator custody,
Root-session restart and useful improvements against strong baselines remain open.
