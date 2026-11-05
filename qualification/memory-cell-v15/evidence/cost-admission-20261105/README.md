# Cost admission and frozen-protocol counterexamples

`probe.py` was executed against the pinned cohort parent
`c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684` and the integrated candidate.
Both executions use the **same probe source**, input cases, artificial resource
vectors and declared common budgets. The probe only adapts the additional protocol
and ledger identity fields required by the new schema. It does not change the
expected outcomes between implementations.

The original returns eight incorrect approvals. The candidate rejects all eight
and retains the positive control. Both records verify that their imported source
files did not change during execution. `red.json` has `failures: 8` and the
deliberate RED command exits 1; `green.json` has `failures: 0` and exits 0.

| Control | Pinned cohort parent | Integrated candidate |
|---|---|---|
| Complete registered synthetic positive control | Approved | Approved |
| Empty economic model and empty resource caps | Approved | Rejected for both missing requirements |
| Equal arbitrary budget names | Approved | Rejected for the actual budget identity |
| Cost receipt from another dataset | Approved | Rejected for data identity |
| Cost receipt from another workload | Approved | Rejected for workload identity |
| Cost receipt from another input-memory cut | Approved | Rejected for memory identity |
| Cost receipt from another cohort registration | Approved | Rejected for cohort identity |
| Different executor wrappers sharing backing state | False gain of 1.0 and approval | Identical-arm difference 0.0; no gain approval |
| Public protocol reassigned from 10,000 planned looks to 1 | Recomputed weaker bound and approval | Frozen bound retained; explicit reassignment refusal |

The last control first evaluates the original, stricter registered protocol. That
original result is retained in `prior_frozen_result`. Reassignment cannot replace
the original protocol settings, worker limits or multiplicity correction.

## Reproduce

With dependencies from the candidate's `requirements.txt` installed, run the same
script against two separate checkouts:

```sh
python qualification/memory-cell-v15/evidence/cost-admission-20261105/probe.py \
  /path/to/cohort-parent/qualification/memory-cell-v15 /tmp/red.json
python qualification/memory-cell-v15/evidence/cost-admission-20261105/probe.py \
  /path/to/integrated-candidate/qualification/memory-cell-v15 /tmp/green.json
```

The source hashes and probe hash in the output identify the executed code. The
second command requires the bounded POSIX process runner. `comparison.json`
checks that all common control inputs and artificial resource vectors match
between the two recorded executions.

## Scope

These are protocol controls using finite functions and artificial cost vectors.
They are not neural training, a measured deployment bill, a future language-task
sample, or evidence of Meta Network utility. The 256 declared synthetic clusters
per control are fixture inputs; they are not 256 newly collected independent
real-world tasks.

In the ordinary controls, each full ledger declares a conservative artificial
allowance of 10 CPU seconds and 128 MiB peak RSS. The common admission caps are
32 CPU seconds and 256 MiB RSS; the separate hard worker limits are recorded in
the budget digest and actual execution receipts. These deliberately stated values
are preserved identically in RED and GREEN. The deliberately costly empty-model
case also preserves its exact artificial vector on both sides.

The candidate's `execution` field contains actual worker receipts. Those measured
CPU/RSS values establish a lower bound on the supplied ledger. They do not measure
whole-device usage, training, retained versions, physical storage, wire traffic,
energy, or economic benefit. An explicit zero economic weight is distinct from a
missing measurement: unknown resource measurements still refuse qualification.

Python state and private working directories are isolated between arms. Shared
external databases, absolute paths and services still require independently
restored snapshots. Cloudpickle is used only for trusted host-owned callbacks,
never for client checkpoints or network requests. This work does not add native
production authority, final-use fencing or whole-authority rollback protection.
