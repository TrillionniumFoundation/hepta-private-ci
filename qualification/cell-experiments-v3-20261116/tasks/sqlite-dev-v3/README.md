# SQLite development tasks for v3

These three exposed tasks derive from Chain issue [#786](https://github.com/TrillionniumFoundation/Trillionnium-Chain/issues/786), workstream 3, and the retained ACT-2 controlled SQLite environment at Hepta commit `0584b3344f70ed51d9e09224e105bfa4d1a4635f`. They are new development instances in one lineage. They are not three independent user requests, three user sources, new holdouts, or an implementation of the performance optimizations requested by that issue.

## What actually executes

`scripts/cell_experiments/repo_tasks_v3_sqlite.py` loads the exact retained `sqlite_destination.py` bytes after checking their SHA-256. Each `DevelopmentSession` owns a fresh local SQLite database. The same database persists across the actor's `inspect`, `stage`, `apply`, and `stop` decisions. The destination's transactions and its read-only readback connections actually execute.

The destination supplies the goal values internally. The actor chooses only the action sequence; it does not author SQL or payloads. `inspect` reports the next unsatisfied row and whether its prescribed payload is already staged. `stage` and `apply` use the visible row, or row zero while the view is absent. A lost reply can remove the view without undoing the transaction. `stop` claims completion only from the last visible complete readback. This v3 adapter deliberately performs no implicit inspect or repair at stop; its stop semantics differ from the old ACT-2 runner and its results must not be merged into that historical experiment.

The final scorer opens a read-only SQLite connection in the same process and checks actual stored values and duplicate effects. This is a separate database connection, not an independently controlled external evaluator. A successful result requires actual completion, the actor's observed completion claim, and zero duplicate effects. Valid action syntax alone cannot pass.

## API and evidence

```python
session = DevelopmentSession(task_id, output_directory)
observation = session.observation()
step = session.step("inspect")
# The caller chooses the next primitive from actual feedback.
# Repeat until step["result"] is populated, then retain that result.
```

The caller must retain the model's raw generation and parser outcome separately if it supplies model actions. The session itself makes no model call and does not authenticate the actor's identity. Each action receipt contains the before/after visible state and an `execution_summary` with the primitive-call, write-transaction and applied-effect deltas. These are SQLite counters, not repository patch-verifier or subprocess counts. The returned scorer result is for final assessment; a training caller must explicitly define whether and when that feedback is exposed.

`TASK.json`, `ACTIONS.jsonl`, `RESULT.json` and the final `destination.db` are retained in a new output directory. Existing output directories are refused, so a replay cannot overwrite the original attempt. The output ledger is local evidence, not an authenticated or tamper-proof owner journal. No original native Cell, training, selection, CURRENT publication, or cold process recovery is invoked.

Run a supplied development reference from the repository root:

```bash
python3 scripts/cell_experiments/repo_tasks_v3_sqlite.py \
  --task-id dev-sqlite-lost-reply-01 \
  --actions-file qualification/cell-experiments-v3-20261116/tasks/sqlite-dev-v3/lost-reply-actions.json \
  --output /tmp/hepta-sqlite-development-new-attempt
```

The output path must be new. Use a different, explicitly recorded attempt directory for a deliberate replay; that replay adds no independent sample.

## Actual bounded reference check

The retained `development-reference-01/SUMMARY.json` records four actual SQLite executions. These were authored scripted action lists, with zero model calls and zero training jobs.

| Reference execution | Actual task completion | Primitive calls | Applied effects | Duplicate effects |
| --- | --- | ---: | ---: | ---: |
| Lost reply, then repeated apply and readback | True | 5 | 1 | 0 |
| Existing staged first row, then second row | True | 6 | 2 | 0 |
| Partial destination, nonproductive apply, then completion | True | 5 | 1 | 0 |
| Missing-stage failure control | False | 2 | 0 | 0 |

All four expected business outcomes were observed. Three attempts completed and one deliberately incomplete attempt failed. The third reference preserves the already satisfied row at revision zero; it demonstrates recovery after a nonproductive action, not recovery from a model-generated wrong payload. The final database files were reopened and the stored rows and effects checked. This does not constitute a daemon/Root cold restart.

No E1–E6 scientific qualification follows from these checks. In particular, they do not establish student experience, a multi-teacher gain, user growth, a neural circuit benefit, or candidate adoption. All three development scenarios retain `derived:chain-786-workstream-3:act2-sqlite-family`; the fourth execution reuses the first scenario and is not another source. No v3 C has been constructed or inspected by this curator.
