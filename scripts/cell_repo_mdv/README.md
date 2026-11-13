# Repository memory development comparison

`runner.py` executes an explicit, bounded repository recipe and can release one
private lexical-memory update after its mandatory checks succeed. Its default
selection remains the learned association reranker. `compare.py` extends the
development path with four complete execution arms:

| Arm | Frozen selector/state |
| --- | --- |
| `candidate` | Immediate successor private-memory checkpoint |
| `no_update` | Exact parent checkpoint |
| `bm25` | Exact substring plus BM25 on the identical document corpus |
| `fixed_expert` | One document/recipe explicitly chosen before execution |

Each arm receives the same task, corpus, source commit/tree, recipes and execution
budget. It starts from a separate local Git clone. The arm order is written to
`plan.json` before any clone or recipe runs. No evaluation arm performs training.
The candidate must be the immediate child of the no-update state, carry its
original successful development result, and be consumed by a different task ID.

```sh
PYTHONPATH=scripts python -m cell_repo_mdv.compare \
  --task successor-task.json --corpus corpus.json \
  --parent parent-state.json --candidate candidate-state.json \
  --candidate-receipt training-result.json \
  --fixed-document selected-development-recipe \
  --arm-order no_update bm25 fixed_expert candidate \
  --output /absolute/new/comparison-directory
```

An already-updated parent additionally requires `--parent-receipt`. The initial
parent must be the canonical zero-update state. The successor task must set
`learn_on_success=false`, use `split=development`, and identify a clean local
source checkout. Outputs must be outside that source. Recipes should address
their cloned working directory; direct references to the original source path
are rejected.

Preparation commands retain intent, raw logs, process-cleanup results and measured
wall/CPU costs. Each arm retains the original runner result and a terminal receipt.
Failed checkers stay in the comparison; unresolved execution prevents the complete
terminal-comparison flag. The outer measured window contains preparation and arm
windows, so these times must not be summed again. Input-file loading, interpreter
startup, external preparation and final report serialization are outside that
window. Peak memory, energy and monetary cost remain unknown.

Clones isolate tracked source files, not external side effects, global caches or
device resources. Their object storage references the original local repository.
These constraints must be considered when selecting development recipes; the
runner does not provide an OS sandbox or authenticate the supplied receipts.

The fixed-document arm is a declared control, not evidence of a well-tuned expert.
The lexical encoder is not a language model. This runner does not establish
independent data custody, statistical benefit, complete cost, native daemon
adoption or production recovery. Confirmation inputs remain rejected by the
original contract. All scientific and production admission flags remain false.

Run the behavior controls with:

```sh
PYTHONPATH=scripts python -m unittest cell_repo_mdv.test_compare \
  cell_repo_mdv.test_runner cell_repo_mdv.test_memory -v
```

The test fixtures exercise actual subprocesses and source isolation. They are
engineering controls and do not add independent research tasks or training seeds.
