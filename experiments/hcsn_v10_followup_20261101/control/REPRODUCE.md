# Multi-READ planning reference

From the repository root, use Python with NumPy/SciPy/Torch versions recorded in
`results/development001/PLAN.json`. The frozen ordinary checkpoints and the V9
analytic/service fits are inherited inputs; their hashes are checked before run.
Use new output and receipt destinations for every execution.

```bash
python -m experiments.hcsn_v10_followup_20261101.control.campaign prepare --output /tmp/new-v10-control
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-v10-cost --timeout 1800 --sample-interval 0.5 -- python -m experiments.hcsn_v10_followup_20261101.control.campaign run --output /tmp/new-v10-control
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/new-v10-common-cost --timeout 300 --sample-interval 0.5 -- python -m experiments.hcsn_v10_followup_20261101.control.common_actions --output /tmp/new-v10-control
```

Each real decision gets only the last successful observation, current tick,
remaining READ budget, common estimated physics and frozen service forecasts.
The planner samples 64 independent conditional model paths from that observation;
it never accepts the actual world or its unread state. Failed service is independent
of the latent path in this declared task, so a failure leaves the state posterior
unchanged. Service-parameter uncertainty is not propagated: the fitted success
probabilities are a common frozen point estimate for every controller.

The planner exhausts all future READ-arrival schedules with at most the remaining
budget (up to 1,351 schedules). For each deadline, it mixes the prior prediction
and each possible most recent successful READ by exact independent Bernoulli
service probabilities. The input table scores predicted classes against model-
sampled future contents, then charges every planned request 0.04. Scores use the
original four-output reward denominator. Simulated paths are shared across every
candidate schedule. The real process replans after WAIT or READ delivery, so
actual execution adapts to successful observations. The candidate schedules inside
one planning call are open loop: this is not full belief-state dynamic programming
or an optimal contingent feedback tree.

The task profile permits one in-flight request delivered before the next tick's
output and decision. READ consumes budget and incurs its fee at request; success
or failure is resolved before that next decision. The comparison does not qualify
arbitrary-delay or suspended in-flight recovery.

Raw records retain every schedule score, conditional MC summary, chosen action,
READ failure/success, observation and output. These support independent arithmetic
reconstruction of the exact service mixture and candidate selection. Recomputing
MC summaries themselves additionally requires rerunning the frozen sampler and
models; auditing saved summary tables alone is not complete model-forward replay.
Each MPC run also executes the same model under fixed selected actions without
planning and requires exact output/observation/reward agreement. A separate
source/inputs freeze then runs every ordinary GRU/SSM on the analytic MPC D
actions in all worlds; observation and action successors must match across cores.
These cross-core predictions may differ and remain in the evidence.

The common physical-law sampler is a declared model prior shared across controllers.
It is not an ordinary GRU/SSM forecast and must not be relabeled a neural baseline
or an actual-world oracle. Ordinary recurrent state still resets for each count
query. All five historical fits and both GRU/SSM families are retained. The primary
ordinary family per fit remains its old validation-NLL choice, never a new-world
winner. No training information/capacity matching or real-AV admission is claimed.

The whole fresh campaign worker is charged once, including conditional paths,
all candidate schedules, imports, model loading, fixed-action checks and evidence
serialization. Inner timers are nested. The first small engineering smoke and
source-development work have unmeasured CPU; historical preparation/pretraining,
complete process-family peak memory and attributable energy remain unknown.
