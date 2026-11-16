# Repository contract experiments, second development round

This profile addresses weaknesses found in the first recorded campaign:
different training/inference message formats, a 48-token output cap, domain-label
scores without repository task execution, unmatched active Circuit resources,
and cold recovery that only exercised an unchanged parent model.

It remains a development study. Twelve newly authored maintenance requirements
are not twelve independently authenticated users. Frozen selection, file hashes,
and separate processes provide engineering checks; they do not establish an
independent evaluator, future-task generalization, native CellOwner adoption,
HEPLCP FinalUse, or accepted proof of useful work.

## Task and action contract

The A/B/C panels contain 6/3/3 test-completion tasks derived from pinned Hepta and
Chain Python modules. A separate warmup task is excluded from every sample count.
The original modules, extracted function ranges, fixed dependency adapters,
source revisions, SHA256 hashes, and Git blob identities are retained in
`qualification/cell-experiments-v2-20261116/task-fixtures`.

Each action replaces the `pass` statement in `test_contract.py` with bounded
assertions calling the reviewed `subject`. The executor creates a fresh temporary
directory and process, applies the exact submitted bytes, and runs those tests
against the original function and declared incorrect-output controls. A task
passes only if the original behavior satisfies the assertions and every control
is rejected. Syntactic validity, a zero process exit code, or weak assertions do
not suffice. This covers function contracts, not a full repository build.

Every attempt resets the test template. Within an episode the next request
preserves the previous model output and bounded test feedback. It does not carry
an incrementally mutated repository. Failure feedback contains status and counts,
not a reference patch, expected return values, or verifier internals.

Some authored demonstrations have a valid partial test, actual feedback showing
missing coverage, and a complete test. Others need only one action. The
`informative_action_count` records this distinction; single-action traces do not
provide a separate intermediate-action training signal.

## Message protocol

New manifests opt into `native_chat_v2` and bind the pinned tokenizer's template.
The first request, final-answer SFT, full-trajectory SFT, and feedback retries use
the same tokenizer serialization. Tool observations are labeled user messages.
Observations and unverified student attempts are loss-masked. An exact terminal
duplicate of the last supervised action is removed. Empty student outputs remain
empty in the retained history. Overlong examples fail rather than being truncated.

The actual tokenizer must pass a protocol preflight. Native BPE boundaries can
retokenize text when a target is appended, so the supervised action prefix must
match the separately tokenized inference request, including later feedback turns.
The retained training receipt states how turns and original records are sampled.

Legacy manifests retain `legacy_v1`. Replaying an old frozen campaign requires
its original source commit because its executable source digest is intentional.

The second-round configuration plans rank-4 q/v LoRA, 64 updates, 1,536 padded
training positions per update, the same seed and base, and a 256-token output cap.
The actual source freeze and runtime receipts are authoritative. Both first-attempt
success and success within two actions are recorded. Two-action success is the
E1/E2 episode comparison; E6 separately declares a first-action policy and uses
that same policy for both B selection and C use.

## Experimental controls and limits

| Experiment | Implemented comparison | Remaining qualification boundary |
| --- | --- | --- |
| E1 | Frozen, A-only lexical retrieval, final-answer SFT, trajectory SFT | Curated small cohort; no independent future task evidence |
| E2 | Demonstration checkpoint, shadow predictions, executed student attempts plus A-only authored corrections | Bounded reset-and-retry tests; no external teacher or persistent environment recovery |
| E3 | Two same-base specialists, pooled examples, explicit domain routing, exact mean of LoRA deltas | Same-base specialization is not multi-provider teacher complementarity |
| E4 | Sequential control, fixed path, random path, A-only learned two-Cell path; every Cell/edge ablated | Offline routing of cached executions; native distributed Cell links untested |
| E5 | Fixed total and per-source budgets at 1/4/16/64 declared source groups | Unavailable groups blocked; files and projects reported separately from users |
| E6 | Frozen A training and B decisions, subsequent C use, exact new-process recovery | Research journal only; no production admission or ledger settlement |

E3's integrated adapter concatenates low-rank factors to represent the exact mean
of the two original deltas. It does not average A and B independently, which would
introduce cross terms. The resulting rank is 8; the larger active adapter and its
cost are disclosed, and composition is not labeled as an SGD training run.

The E4 kernels perform identical useful forward/backward/update operations with
the same active parameter count. The learned path uses A-only online loss history;
its score bookkeeping is reported separately. Resident parameters, all parameters
touched during training, wall time, control overhead, encoding, and model execution
costs are not assumed equal. Kernel matching is not complete system cost matching.
There are no actual network messages in this local diagnostic.

E4 business readout joins each frozen route and ablation to an actual model answer
and semantic test receipt. Classification accuracy is never substituted for task
success. All three upstream model evaluations remain charged. Reusing their rows
for many graphs performs no new model call and creates no independent task. Inner
classification selection and outer B business selection are kept explicit.

Source grouping merges aliases sharing tasks, lineage, observations or files.
Missing users, adoption rates, long-term forgetting and full costs remain missing.
The source-count grids are experiment settings, not predicted scaling curves.

## Execution and evidence

Use the pinned local model and a separate new result directory:

```bash
PYTHONPATH=scripts /path/to/ml-python -m cell_experiments.run_study_v2 \
  --root /path/to/new-run \
  --materials /path/to/pinned-base \
  --logs /path/to/new-logs
```

The coordinator builds references in separate processes, freezes code, fixtures,
data and plans, trains at most two models concurrently, retains raw attempts,
evaluates B, writes an immutable selection receipt, then opens C in a later
process using the selection hash returned by the earlier one. Failed stages and
partial outputs are retained without automatic retry. Source or artifact changes
invalidate the bound run. Checkpoint recovery tests are distinct from adoption.

Run integrity tests with the package-aware discovery command in `README.md`.
That CI suite does not run language-model training. Actual weights, optimizer
states, generations, test executions, decisions, recovery records, source hashes
and resource receipts belong to the corresponding campaign evidence.
