# Independent-pool feedback rollout with light fallback

From the repository root, use Python/NumPy/SciPy/Torch recorded in the frozen
PLAN.json. All source/input hashes are verified before formal world generation.
Output and receipt destinations must be new.

```bash
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/v12-prepare-cost --timeout 120 --sample-interval 0.5 -- python -m experiments.hcsn_v12_followup_20261101.control.campaign prepare --output /tmp/v12-new-control
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/v12-campaign-cost --timeout 3600 --sample-interval 0.5 -- python -m experiments.hcsn_v12_followup_20261101.control.campaign run --output /tmp/v12-new-control
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost --out /tmp/v12-common-cost --timeout 300 --sample-interval 0.5 -- python -m experiments.hcsn_v12_followup_20261101.control.common_actions --output /tmp/v12-new-control
```

The planner accepts the last successful observation, current tick, remaining
budget, common estimated physics and frozen empirical service-success q. It
never accepts the actual unread task path. Each model pool samples latent futures
conditional on that observation, with independent per-arrival service uniforms.
All root actions share each pool's future and uniforms. Service success in model
futures uses frozen fitted q; actual execution retains the original true declared
service law. Their discrepancy is model error, not removed by confidence bounds.

The first pool has exactly 512 trajectories. It compares STOP, WAIT and READ at
the current decision, then executes the frozen light policy separately in every
branch, updating actual simulated observations, pending delivery and remaining
budget. Further READs are permitted. READ is charged at request; next-tick
arrival is handled before output and decision. Failure retains the last successful
observation, and STOP continues all mandatory outputs. A branch never receives
another branch's successful observation. No open-loop future schedule substitutes
for this adaptive feedback tail.

Selection ties prefer the current light action, then STOP/WAIT/READ. If selection
keeps light, there is no validation pool. Otherwise one fresh independent pool of
exactly 512 trajectories evaluates only that fixed candidate against the fixed
light root action, both followed by light feedback. It cannot reselect actions,
change thresholds, add samples or stop sampling early. Integer reward units are
`25*correct_count - 4*READ_count`, with 100 units equal to one net-reward unit.

For r remaining mandatory outputs and b remaining requests, each paired future
reward difference is in [-K,K], where K=r/4+.04*b. The single-sided Hoeffding
lower bound is mean_difference-K*sqrt(2*log(1/alpha)/512). Only a strictly positive
bound permits deviation from light. The campaign declares at most 12*11*20=2640
validation tests, alpha=.05/2640. This bound addresses Monte Carlo error for the
fixed two actions and light tail under the declared common fitted model. It does
not guarantee true-world policy noninferiority, unknown-parameter correctness,
model generalization or positive overall economics. All first-pool candidates,
second-pool tests, integer paired differences, bounds and fallback reasons remain.

The physical-law generator is a shared model prior, not an ordinary learned
controller or a true-path oracle. Historical GRU/SSM fits and the analytic physical
calibration remain unequal in training information and structure. This experiment
is a finite model-policy improvement reference, not a trained open-domain network.

Complete worker CPU includes both pools, every adaptive light tail, model imports,
loading, fixed-action replay and serialization. Per-arm timers are nested within
that worker. Development/source-writing and original historical preparation costs
are not fully metered. Complete family peak memory and attributable joules remain
unknown. Gzip evidence retains every attempted formal run and failure; engineering
smokes are separately labelled and do not choose the declared 512+512 budget.

The first vector head failed 21 of 45 scalar comparison cases solely through
floating-point uniform-class ties. Its exact source and raw failures remain in
review/source001 and SCALAR_AUDIT_001.json. The final implementation calls the
original scalar head for unique uniform public states, preserving its concrete
argmax. It does not replace approximate uniform probabilities by mathematical
uniform values. Final scalar checks reproduce all 1080 branch rewards, READs,
correct counts and feedback-state traces exactly.

Actual validation counts may be reported as realized alpha spending. They do not
replace the predeclared global model-only delta=.05 guarantee with a tighter
posthoc familywise guarantee. Cross-core/common-world pool reuse is declared
common random numbers; each candidate remains independent of its own validation
pool, and a model never uses another model's validation outputs for selection.
