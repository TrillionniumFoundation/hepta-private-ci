# Closing timestamp correction v3

This corrects a reachable mock-clock defect in `4e63669fc7a4`, not an observed
real-training overrun. Both normal and oracle-negative seed closings now call
one helper. It completes policy progress, retains the final cost row, then
checks build450 and policy150 using that row's identical `end_cpu_ns`. A cap
violation raises a failure with the overrun row preserved. A successful return
uses that exact end as the next phase start, assigning subsequent transition
CPU to the following phase.

Only two new mock-clock tests were run:

- Normal: policy starts300.20s, pre-close449.99s, progress flush adds0.03s.
  The row450.02s fails build450 while policy149.82s remains within150.
- Oracle-negative: policy starts299.97s, pre-close449.96s, flush adds0.03s.
  The row449.99s fits build450 but policy150.02s fails its150 cap.

Both assert exit1, failed terminal status, the exact retained overrun row, and
seeds23/47 unrun. Intake, model and actor calls are mocked. No old graph suite,
real dataset, training, official TEST, formal evaluation or D probe was run.
The two tests passed with unchanged tolerances; logs and invocation details are
in `verification-closing-v3`. Development CPU was not separately bracketed and
is not represented as zero or credited to a method budget.

The original and v2 freezes and review evidence remain unchanged. The active
source is bound by `FROZEN-recovery-v3.json`, whose previous-freeze hash points
to v2. No protocol, model, loss, data rule, gate or cap changes. Real D remains
pending lawful local TRAIN files; prior403 targets were not retried or bypassed.
