# Optimized risk backend: separate CPU cost supplement

This independent18-job cohort measures the optimized backward-Poisson risk
vector in the complete encoder. It preserves the original72 cost jobs and
the original matrix-risk18 without changing their code, results or queues.
The original immutable cost worker is called in an isolated child with only
its model factory rebound to the sealed memory-profile classifier.

The2 tasks,3 scales (16/1,32/1,64/2),3 paired seeds9301–9303, LR.001,
20 training-CPU-second budget, validation opportunities15/20, loss, selection,
quality targets and timing repetitions are inherited byte-for-byte. The
nominal360 training CPU seconds exclude imports, validation, heldout,
measurement and analysis; all full worker costs are recorded with wait4.

Before registration, six matrix/vector task-scale pairs each perform two
Adam updates on the same real training minibatches, batch4, seed9301. All
initial tensors and batch indices must match exactly; all named gradients,
post-update parameters, optimizer tensors, logits and losses must satisfy
the fixed numerical limits. This small-batch check is not certification of
the large-batch peak memory or long training trajectories. These preflight
children are sequential, wait until risk001 has drained, and use their own
1.3GiB budget plus2GiB shared reserve and the fixed128 future-capacity guard.

The new queue runs one worker and waits until the existing matrix18 has
drained to a terminal state. A2.5GiB per-worker budget and2GiB shared reserve
cover the larger width64/depth2 worker; the width32 fixed128 profile's
1.25GiB budget is never reused for this queue. Before each dispatch, the
queue also reserves the remaining capacity of live fixed128 memory-profile
workers and its currently requested vacant slots. That fixed128 queue has
priority. Namespace PID credit uses its frozen, tested host PPid/NSpid
mapping. Cgroup measurements are sequential estimates, not hard guarantees;
root must account for an active large cost worker before increasing other
queues' ceilings. Failures and peak-budget violations stop further launches
and preserve all costs, without retries.

The combined analysis audits all108 jobs: original72, matrix18 and vector18.
Both risk profiles are always reported; there is no post-outcome backend
selection. The shared original72 costs are counted only once. Matrix/vector
speed ratios require the original target and2 percentage-point test-quality
conditions for all three paired seeds. These gates are descriptive; they do
not establish statistical equivalence, GPU performance, energy savings or
foundation-model scalability.
