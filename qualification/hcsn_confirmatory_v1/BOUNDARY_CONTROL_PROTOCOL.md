# H2: known finite-control boundary pilot

Status: source prepared; hard-policy equivalence/gradient gate and all formal
runs await root's source/resource admission. This is a separate finite-control
experiment and new namespace, not a claim about learned task boundaries.

## Shared information and external running rewards

A known six-state generator has five active states and one locked reset phase.
Nearest-neighbour active transitions and natural jumps to the phase are explicit
in boundary_control.process(); the phase releases to active state 2 at rate 2,
so its mean waiting time is 0.5 seconds. Discount is 0.3. Initial mass includes
10% already in the phase. Immediate voluntary reset payoffs and initial
distribution are fixed, identical and known to every method.

The utility-rate law is defined independently of QVI or any controller. Each
paired seed has an external synthetic six-component reward mean. Train/dev/final
contain separate noisy state-probe measurements (32/32/128 full-state vectors),
with separate namespace-derived generators and common latent means. Controllers
receive exactly the same observed train means; dev only selects a candidate
against never-reset. Neither method consumes hidden plant means or any QVI label.

These are synthetic measurements of an external running utility, not physical
device observations. Final evaluates the complete discounted expected return
inferred from new reward measurements. It does not claim to measure sampled
trajectory returns or a real deployed task. Natural-state utility is a net rate;
voluntary intervention pays the separately specified instantaneous payoff.

## Competing controllers and timing

Howard QVI policy iteration uses the existing solve_impulse_control reference,
with tolerance 1e-10 and a 128-iteration cap. It chooses an arbitrary five-state
intervention set; no threshold ordering is assumed. Its policy-evaluation solves,
iterations and residual are recorded. This is iterative finite dynamic
programming, not a closed-form optimum over a neural network.

The ordinary comparator is a full-state lookup gate with five independent
logits and no representation restriction. Let pi_i=sigmoid(logit_i) in active
states and pi=0 in the locked phase. Fix lambda=max_i(-G_ii) from the common G,
T=(lambda I+G)/(rho+lambda), and rbar=r/(rho+lambda). Its full value is obtained
by solving

J = (1-pi) * (rbar + T J) + pi * (payoff + J_reset).

Adam (.1) takes exactly 128 steps to maximize initial_distribution dot J using
only the observed training reward mean. Gradients propagate through the full
linear solve. It does not regress against Howard values, policy labels, a
continuation-only utility or an independently trained critic. No learned reward
or unobserved state information is supplied to either controller.

The fractional gate makes a Bernoulli decision before a uniformized continuation
step, including self-transition epochs. Reset is instantaneous and enters the
locked phase, where no action is allowed. Continuing earns the appropriate
discounted running reward before the next epoch. This clock convention is part
of the model: changing lambda changes the fractional-policy decision frequency.
For hard pi in {0,1}, the equations coincide with the existing continuous-time
impulse-policy evaluator, including time-zero actions and complete phase/reset
continuation. The unit gate checks all 32 hard policies and verifies the
five-logit objective gradient by finite differences. No post-training rounding
or hidden hardening candidate is selected.

Never-reset uses pi=0 exactly. Each proposed Howard/lookup candidate is evaluated
once on dev, and retained only if its full return strictly exceeds that same
incumbent; otherwise the exact zero policy is selected (NoUpdate). Candidate and
selected probabilities, dev scores, failures and actual completed work remain
in the receipt.

## Frozen execution and final metric

Use a new namespace starting hcsn-boundary-confirmatory-v1/ with at least
49 characters. Root allocates three paired seeds for the initial pilot (one to
five is an explicit staging choice). No prior stage or historical holdout is
read. Source closure, runtime versions, CPU/backend/threadpool identity and
budget are frozen before data generation.

```sh
python -m qualification.hcsn_confirmatory_v1.boundary_control freeze --manifest NEW_BOUNDARY_FREEZE.json --namespace ROOT_ALLOCATED_NAMESPACE --seeds ROOT_ALLOCATED_SEEDS
python -m unittest qualification.hcsn_confirmatory_v1.boundary_control_tests -v
python -m qualification.hcsn_confirmatory_v1.boundary_control fit --manifest NEW_BOUNDARY_FREEZE.json --output NEW_ATTEMPT
python -m qualification.hcsn_confirmatory_v1.boundary_control final --manifest NEW_BOUNDARY_FREEZE.json --output NEW_ATTEMPT --selection-sha256 EXACT_SELECTION_SHA256
```

The unit gate uses fixed toy rewards, never formal observations. Fit writes only
train/dev evidence and freezes the chosen policies. Root binds the exact
selection SHA. Final creates the exclusive consumed marker before generating
its independent reward measurements. There is no silent final rerun.

For every new final reward vector and each frozen selected policy, solve the
complete infinite-horizon value and report initial_distribution dot J. All
methods use the same final vectors, giving paired gains relative to never-reset.
The mean is an unbiased linear estimator of the fixed policy's expected return
under the assumed measurement law. Variation across these vectors is reward-
measurement uncertainty, not independent controller-training replicates.

Primary contrast is Howard minus lookup-gate full return per paired seed.
Report all three seed values/ranges, NoUpdate choices and failures; do not claim
significance or bootstrap the 128 measurements as independent trained models.
Retain every reward measurement, return and paired baseline gain.

## Work and scope limits

The ledger records source/runtime admission overhead, reward acquisition,
proposals, solves, 128-step BP work, dev/final and failures. DP and the BP block
each use one write-ahead work reservation; completed BP solves/backward passes
are also counted explicitly. This avoids making 128 extra journal flushes the
reason one algorithm appears slower. In an interrupted block, reservation is
an upper work charge, and unsettled physical cost remains unknown.

Initial fit+final ceiling is 90 wall seconds with frozen work caps. Checks are
operation boundaries, not a hard OS deadline; root supplies process watchdog/RSS
admission. The cost sidecar follows primary receipt serialization/checkpoint;
its own write, stdout and process exit require the external process meter.
The limit is a budget, not a measured speed result.

The algorithms share exact dynamics, payoff, discount, observed reward and
initial distribution. This information-rich finite-control comparison cannot
establish a practical advantage when a neural network must discover G, infer
hidden states or learn multimodal representations. The finite-logit stochastic
policy and deterministic instantaneous policy also have the declared timing
difference above. Outcomes must be interpreted within those constraints.

