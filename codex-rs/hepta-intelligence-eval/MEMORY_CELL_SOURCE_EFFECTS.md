# Source-written knowledge: actual task effect consumer

This increment starts at `184b92f37f89b20c267246d41ba48275125c9758`.
It reuses the existing reader diagnosis, controlled event organization,
source-only writer, ten-weight policy and lifecycle accounting. It does not
claim those inherited implementations as new, and does not change their model,
source corpus, 128-update / 65,536-token ceilings or seven-arm task plan.

The source writer must commit its immutable adapter before a separate reader
process opens the frozen task plan. The actual task pipeline now invokes
`source_write_effects.py` after original answers and task results exist. The
consumer checks every task across hybrid, organized, knowledge, parameter-only,
empty, initial-policy and learned-policy arms. Missing or failed pairs remain
in the effect bounds; a changed answer is not itself a successful task.

The comparisons are deliberately separate: organization against hybrid,
learned policy against initialization AND against deterministic organization,
knowledge against the SAME evidence and prompt without the adapter, and
parameter-only against the SAME empty context. Reports split new facts,
corrections, composition and procedure tasks. Every knowledge comparison must
preserve selected IDs, actual token-input digest, original evidence bytes and
derived schema expansions. A policy that matches the organizer is not a new
learned gain over that stronger baseline.

The disk consumer reuses native citation capture and the bounded actual
procedural worker. Replaying the worker compares request, stdout, stderr and
exit code, not a newly observed timestamp or elapsed duration. It validates
both clock receipts separately and never rewrites the historical record. Worker
replay is a repeated check, not a fresh model answer, independent observation,
old-task retention result or production recovery test.

The original write/read report retains extraction, index, write (including
training), query and source storage observations. `lifecycle_accounting.py`
remains the shared cost-envelope implementation. Do not double count training
inside write time; do not add model inference again inside inclusive read time.
Unmeasured deployed maintenance, old-task retention and cross-host recovery stay
unknown. No total production cost or amortized savings follows from these
partial measurements. Original documents and snapshot/backup copies stay in
the retained-storage accounting.

The inherited controlled organizer result (source `421feaad`, run 38066590605)
is eight task successes versus four for its bounded hybrid control; the learned
policy matches the organizer with identical selections. Those are authored
controlled-program observations, not independent production histories. The
source-written knowledge experiment must complete before any parameter benefit
can be reported; an earlier writing timeout supplied no task-quality evidence.
Its 330-minute CPU allowance is an execution bound, not permission to weaken
algorithmic budgets, select new test cases, or call a pending run successful.

The independent human source review, semantic citation adjudication, natural
language transfer, newly collected prospective windows, production cutover and
cross-host disaster recovery remain external or uncompleted obligations. All
outputs retain `production_accepted=false` and unset semantic citation precision.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_source_write*.py' -v
python3 scripts/memory_cell/source_write_effects.py \
  PLAN_DIRECTORY ORIGINAL_INPUTS WRITE_READ_OUTPUT \
  --plan-sha ORIGINAL_PLAN_SHA --ready-sha ORIGINAL_READY_SHA \
  --source-commit EXACT_GENERATING_COMMIT
```

The focused regression workflow uses only read permissions, full inherited
regressions and required repository formatting. The temporary formatter produces
only a separate inspected candidate and removes itself; it never updates main
or the PR head. Unit fixtures contain authored answers, not pretrained outputs.
