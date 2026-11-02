# Independent design review

The planned service-outcome mixture is sound for a declared open-loop future READ
schedule when service successes are independent of the latent content and physical
path. For a future output deadline, either all READs before it fail, leaving the
last visible observation, or the latest successful arrival determines the visible
state. Mixture weights can be checked independently by enumerating all 2^R
Bernoulli success patterns. Arrivals after an output cancel from that output's
expectation but their fees must still be charged if they remain in the schedule.

The objective must retain the original task's denominator of four mandatory
outputs. Dividing by only the remaining outputs changes the price of READ late in
the episode. READ success at a deadline is processed before that deadline's output.
Previously emitted outputs are a common sunk term and can be omitted from action
comparison without changing their denominator.

A last visible observation and its time, current tick, remaining READ budget,
shared estimated physics, current core identity and frozen service-success
forecasts are sufficient planning inputs under this model. Failed service events
reveal no latent path information because service is independent. Real unobserved
positions, content, service uniforms, future labels or recorded paths must never
be passed into the planner. Simulated conditional paths are legitimate Monte Carlo
model futures and must be distinguished from the actual task path.

Exhaustive schedules with closed-loop replanning are an MPC reference. They do not
form an exact belief-state dynamic program: candidate future READ decisions do not
branch on future observations, and a finite Monte Carlo draw introduces selection
error. A shared known-law future sampler is a privileged model prior, not an
ordinary neural count propagator; giving it to all cores makes the comparison
common-information at execution but does not prove an ordinary-model-only planner.

A uniformly sampled finite future pool can change decisions even when the core is
held fixed. All candidates should share that pool; budgets, namespace, candidate
set and tie policy should be frozen before confirmatory world generation. True
Monte Carlo uncertainty, core mismatch and service calibration errors remain.
