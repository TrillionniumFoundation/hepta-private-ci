# Immutable original-artifact admission

The parent CPU workflow used Python `assert` for its pre-model pointer gate.
The exact retained parent snippet rejects three changed pointers normally but
accepts each under `python -O`: MISSING with a commit, wrong archive hash, and
a duplicate status key resolving to MISSING. Each accepted fixture emitted a
GitHub checkout commit. This read-only counterexample ran in an isolated local
git fixture with zero model calls; the retained real MISSING pointer has no
commit and did not execute a model in the parent Actions run.

The workflow now invokes `artifact_pointer.py`. It uses explicit exceptions
and the existing strict JSON reader, requires FROZEN, exact repository,
manifest path, original archive size/hash, and a full lowercase commit SHA.
Duplicate keys, nonfinite numbers, unexpected fields and typed identity
mismatches refuse before any source-identity or checkout output is published.
Archive/part/member/source validation remains in the separate CPU adapter.
A syntactically valid pointer alone does not establish that the commit or
original archive is available; actual checkout and full byte guards still run.

The retained local executions are 18 archive/relocation tests, five pointer
tests normally and the same five with Python optimization: 28 test executions,
zero skips or model calls. The tests also start normal/optimized subprocesses
for the original three counterexamples and a positive frozen fixture. Tested
Python snapshots, stdout/stderr, initial and final attempts, and normalized-AST
format mapping are in `evidence/pointer-gate-20261112-c06d/`. Ruff and scoped
`just fmt` completed; no local tests were rerun after formatting. New exact-head
Actions is a separate source receipt and must be observed independently.

This stacks on CPU-profile evidence head
`546f03f56b115045972b0d36c34882148adab39e`. It changes no original checkpoint,
source, selection or replay worker. CPU-ARTIFACT remains MISSING here. The
original six-fit full-training replay count remains 0/6 and native attempts'
lifetime optimizer total remains UNKNOWN. No scientific or production GO.
