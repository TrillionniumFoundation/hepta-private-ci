# MemoryCell isolated source-only two-hop experiment (pre-registration)

Experimental generating source is the new commit on branch `codex/memory-source-twohop-isolated-20261011`, descended from exact research source `ac79f80daa6bf8d823739d35ad6af40bfb472db8`.
This is an isolated **research** branch, not a main change, PR merge, production deployment, or independently authorized evaluation.

## Causal question
The earlier single-hop *full-vocabulary-loss* pretrained writer (generating source `2c6dae45782b1ba07ba9af237f01bdecc0c5640b`, run `38097606061`) completed 128 actual updates, but added **0/8** parameter-only successes and **zero additional** same-evidence successes. Is source-only two-hop supervision more effective under the same writer ceilings, reader, prompt, source corpus, and output protocol?

Only the source-only curriculum changes to `source_two_hop`: it adds 24 two-hop examples to 88 direct examples. The optimizer-step ceiling remains **128**, input-token ceiling **65,536**, learning rate **0.0002**, LoRA rank **4** (query/value), base Qwen2.5-3B publisher revision, source bytes and evaluation tasks unchanged. Actual completion lengths, tokens and measured full-phase costs may differ and must be reported, not assumed matched. The full-vocabulary default objective `full` is selected to match the original run; using the sparse-projection optimization would add a separate causal change. No evaluation question, answer or task labels may influence source-writing or selection.

## Precommitted outcome contrasts
The actual seven-arm experimental output is evaluated with `source_write_effects.py` using exact raw-answer records: deterministic organizer against hybrid; learned policy against its initialization and deterministic organizer; source-knowledge adapter ON versus OFF with identical original evidence and prompt; and parameter-only ON versus empty-context OFF. The controlling outcomes are strict per-task success, actual procedure worker execution, and per-kind paired wins, losses and missing-outcome bounds. The precommitted eight authored tasks are already publicly exposed; no statistical significance or representative generalization is claimed.

The source-only write process commits its READY snapshot before a separate read process accepts the task plan. Zero or failed updates, read failures, unsupported citation markers, original output contamination, changed model/inventory/source hashes and partial results cannot become a successful effect. Full raw outputs, original source snapshots, actual resource measurements, program replays and file SHA256SUMS must be retained. Research weights are not redistributed.

## Why isolate the workflow
The heavily edited PR research branch creates many unrelated CI runs; some model jobs have been cancelled by subsequent pushes. This workflow triggers only when its **own file** is pushed on this isolated branch. `cancel-in-progress: false` and an isolated concurrency group prevent unrelated research-branch updates from superseding its scheduled long run. Do not mistake a queued or running job for a result. If the run fails, retain the actual failure rather than shrinking the objective, budget or task set after inspecting labels.

## Remaining limits
An increase in authored-task correctness is exploratory only. Independent human sufficiency/entailment review, source-family independence (N_eff >= 200), independently tuned strong RAG, old-task retention, prospective future windows, full lifecycle cost, real cross-host recovery and production authorization remain absent. Semantic citation precision is `null`, and `production_accepted=false`.
