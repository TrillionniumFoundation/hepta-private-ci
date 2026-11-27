# Memory budget and task evidence tools

These tools measure real work under frozen resource ceilings and preserve raw
observations, including failed admission and uncompleted requests. They do not
qualify a general memory system or provide a complete strong repair agent.
The 2026-10-24 experiment and its explicit limitations are documented in
[the evidence report](../../qa/memory-budget-20261024/README.md).

## Components

| Module | Responsibility |
|---|---|
| `budget_ledger.py` | SQLite reservations, measured settlements, shared allocations, and uncertain work |
| `artifact_inventory.py` | Declared retained/private file inventories and provenance |
| `cohort_contract.py` | Frozen inputs, code pins, source-only fits, and final exposure contract |
| `budget_process.py` / `budget_child.py` | Bounded subprocesses, receipts, and Linux parent-death handling |
| `retrieval_index.py` | Actual SQLite BM25/code-token and path-overlap retrieval |
| `workflow_records.py` | Automatic workflow command extraction and source-only partitions |
| `prepare_budget_study.py` | Registered recipe, capacities, common caps, and source seal |
| `baseline_study.py` / `retrieval_scale.py` | Actual index, lossless codecs, load, and small-corpus scale measurements |
| `model_budget.py` / `budget_model_worker.py` | Disposable pretrained work with actual tokens/steps and checkpoint lineage |
| `run_budget_models.py` / `model_load.py` | Shared parent, four fixed arms, persisted routes, controls, and bounded load |
| `task_execution.py` | Narrow registered actions and original command/test postconditions |

`BudgetLedger.reserve` precedes side effects. A completed receipt is settled as
measured work; lost measurements retain conservative charged reservations in
`uncertain_work_charged`. That uncertainty is not measured optimizer execution.
Shared work is physically counted once and separately allocated to standalone
arm views. Common ceilings do not establish equal actual consumption.

Inventories include only declared components and are snapshots at a recorded
cutoff. They do not measure complete OS dependencies, all memory-mapped I/O,
continuous file byte-time, or a monetary provider bill. A zero unmeasured field
must not be interpreted as zero cost. Host-meter admission is not an adversarial
operating-system sandbox.

## Standard-library mechanism checks

The suite requires Python 3.12 on Linux for the parent-death behavior. From the
repository root, run:

```sh
python -B -m unittest discover -s scripts/memory_cell_budget -p 'test_*.py' -v
```

The published suite contains 29 tests, including synthetic failure receipts;
it neither downloads a base model nor executes pretrained model training.
The dedicated shadow workflow checks the exact source SHA, requires all 29 tests
to be discovered, and retains the actual log. Local pre-publication tests ran
before final formatting; hosted checks are separate evidence when completed.

## Reproducing a model study

Preparation requires explicit historical input records, task fixtures, exact
source identity, and a fixed model/runtime; see each script's CLI. Models use
the adjacent `scripts/memory_cell`, `memory_cell_domain`, and
`memory_cell_network` implementations inherited from baseline commit
`429894ac8e0818102cfdea4ad47a56e4583b2902`. The executable reader retains its
192-token input and 16-token output contracts. There is no silent truncation or
replacement of raw generated text with a source answer.

The archived A and B source seals contain the original absolute paths. The
archive includes a path mapping and exact bytes for audit, but replay elsewhere
requires a new preparation and provenance record rather than editing old seals.
The formatted publication copy was not the source used for the preserved model
run. Its equivalence receipt explicitly records raw docstring whitespace changes.

The model CLI requires `--model-lane-authorized` and a new output directory.
An interrupted or failed run is retained; automatic replay, changed budgets,
and post-evaluation recipe selection are not part of the recorded experiment.
Natural-task success additionally requires an admitted action and execution of
the unchanged original gate. A remembered command or gold action label alone
is never a successful task.
