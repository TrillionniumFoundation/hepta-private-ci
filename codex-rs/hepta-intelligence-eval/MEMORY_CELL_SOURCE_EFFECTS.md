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
source-written knowledge experiment has since **completed** at its
original generating commit `2c6dae45782b1ba07ba9af237f01bdecc0c5640b`
(artifact `11689893524`). Read-only original-answer replay in
[run 38111836918](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111836918)
**passed** for the independent model-result job; the workflow's separate
repository-format job failed, so the complete workflow was not green. The
original experiment completed eight controlled tasks, seven matched arms,
56 actual model generations, 88 source-only training examples, and 128
optimizer updates. Mean training loss fell from 6.527866 (first eight
updates) to 2.372350 (last eight), but loss reduction is not task gain.

Measured paired outcomes were: bounded hybrid 4/8; deterministic organized
evidence 8/8; learned policy 8/8 with identical choices to organized evidence;
organized-plus-memory 8/8 with **zero wins or losses against identical
evidence with its adapter disabled**; parameter-only 0/8 with zero task gains
versus its empty-context control. Five parameter-only answers emitted citation
labels without any sources delivered. The retrospective **rejects this
parameter candidate**, with independent semantic citation precision `null`.
An already 8/8 deterministic organizer has no remaining strict-task headroom
on these exposed controlled cases. Source-only learning must instead be
evaluated on new, pre-registered independent families with nonzero headroom;
no additional updates on these same evaluation questions can establish it.

A separate pinned BF16 Qwen2.5-3B/PEFT single-update source-loss parity job
[run 38221406283](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38221406283)
**passed** on generating commit `3714b9985900286faa2e27ca7e5b4dd86e733647`
(artifact `11735991721`). On the same original 209 input positions and
three supervised positions, original full projection and optimized projection
reported equal loss, zero maximum gradient difference and zero maximum
updated LoRA parameter difference, with the frozen base unchanged. This
proves one-step equivalence for one real pretrained source example, not
128-step convergence, end-to-end QA gains, statistically reliable speedup,
semantic citation quality, or any production authority.

Its 330-minute CPU allowance remains an execution bound, not permission
to weaken the original budgets, select test cases after seeing scores, or
call queued, cancelled, failed or incomplete follow-up runs successful.

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

## Saturation and citation delivery diagnostics

`source_write_effects.py` now reports the exact baseline headroom remaining in
completed paired tasks. An organizer already successful on all planned tasks has
**zero observable room for more task successes on that cohort**; a tie cannot
establish learned knowledge improvement. Failed pairs are not called saturated.
The same report separately counts original emitted `[E...]` marker occurrences,
markers naming an actually delivered label, markers naming no delivered label,
markers emitted with an entirely empty evidence set, and answers missing a marker
despite delivered sources. It preserves the original answers and scores. Matching
a label is only structural identity, never an independent semantic entailment
verdict. Missing citations and invented labels remain visible, with independent
precision null and `production_accepted=false`.

## Objective-specific optimization admission

The real Qwen sparse-projection parity receipt tests a **single completion-CE**
source example. It is not a two-forward margin objective proof. The opt-in
`supervised_positions` backend therefore fails closed when requested with
`source_margin`, even with an intact completion-CE receipt. The unchanged `full`
margin path remains available for isolated development. A future sparse-margin
research candidate must first supply its own pinned real Qwen/PEFT paired-forward
loss, gradient, optimizer-step, frozen-base and resource parity evidence. This
is a validity fix, not a new model improvement, task execution or production
permission.
