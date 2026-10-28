# First-passage cell: mathematical, event, training and value contract

This research package implements the five work packages authorized on 2026-10-28.
It is a new package beside the analytic terminal-event studies. Existing rounds,
native sparse dynamics, production protocols and their evidence are not relabelled.
Repository base: ed6f8c6645c927249cec0d3395f6bae21f278739.

## 1. State, units and filtration

The physical cell state Y has a fixed observed unit. Its physical lower boundary
is B. Distance x = Y - B is positive between events. Each segment has constant
mu = mu0 + w1*u1 + w2*u2, positive diffusion standard deviation sigma, and a fixed
boundary. A fitted reset is a positive distance above B, not an arbitrary change
of measurement units. This initial-state anchor separates B from reset distance.

Physical time is measured in registered task seconds. Event count, communication
sequence and optimizer iteration are separate clocks. The process is stopped
during its explicit refractory duration. Input changes begin a new constant
coefficient segment. Input-induced boundary crossings are immediate events,
not a Gaussian terminal observation.

The model receives observed initial state, inputs, elapsed/remaining time,
public maintenance price and permitted prior observations. It does not receive
future random draws, hidden law changes, confirmation labels or the true simulator
parameters. Synthetic laws are scoped controlled tasks, not natural-language or
biological efficacy evidence.

## 2. Typed events

| Event | Meaning |
| --- | --- |
| first_passage | First crossing of the physical boundary in an active segment |
| survived | Observed opportunity with confirmation that no crossing occurred |
| right_censored | Observation ends before the next event; survival likelihood applies |
| interval_event | Event observed in a bounded time interval; use interval probability |
| missing | Observation unavailable; no survival evidence may be fabricated |
| communication | Transport of a state/event message, not a physical crossing |
| maintenance | Voluntary task action that resets state and charges its public price |
| stop | Terminal task action; no subsequent operating reward or exposure |
| terminal_observation | State observed at a deadline; not interchangeable with first passage |

A zero communication count is neither a survival observation nor a terminal
neutral class. An unavailable observation and a confirmed zero event count have
different observation masks.

## 3. Analytic segment

For dX = mu*dt + sigma*dW on x > 0 with absorption at zero, the implementation
provides first-passage CDF F, survival S, density f, discounted first-passage Hq,
and the killed transition kernel Kt. The source references are:

- He and Xiong (2012), Rollover Risk and Credit Risk, equations (8)-(12), A7:
  https://www.princeton.edu/~wxiong/papers/rollover.pdf
- Qi (2026), Deep Q-Learning on Holder Spaces, full version:
  https://arxiv.org/html/2606.16846v1
- Paninski, Haith and Szirtes (2008), first-passage likelihood derivatives:
  https://sites.stat.columbia.edu/liam/research/abstracts/haith-jcns-abs.html

Task probabilities use the declared data-generating law, not an unidentified
risk-neutral pricing measure. Hq is a discounted event weight and is not a
probability for q > 0. A value output is never used as runtime confidence.

Finite inputs, sigma > 0, nonnegative horizon and discount, and domain endpoints
are validated. At time zero or an already reached boundary, the atom and density
semantics are explicit. Derivatives refer to interior parameter values; boundary
atoms do not acquire invented ordinary density derivatives.

Independent quadrature/high-accuracy references check mass, hitting density,
discounted hitting, killed-kernel positivity and composition, gradients, tails
and multiple parameter signs. A finite test grid is a numerical verification
domain, not a universal floating-point error theorem.

## 4. Survival beliefs and reset

Known states propagate with the killed kernel conditional on no event. Hidden
state beliefs propagate by positive integration against that same kernel and
normalization by survival mass, followed by an available sensor likelihood.
A missing observation does not add a survival condition. Normalized filtering
has additional conditioning error when survival mass is small.

After a first passage, the cell records its event time, applies reset, spends
the refractory duration, and continues for the remaining physical time. The
refractory duration is positive and bounds event count on a finite horizon.
Sampling at most one event per window is not permitted under this profile.

Runtime state includes physical state, logical time, remaining refractory time,
random-generator state/counter, event count, parameter digest and schema version.
Checkpoints bind model and runtime identities. Resume must reproduce events,
terminal state and reward exactly for the same future request sequence. An old
or incompatible model/checkpoint pair is rejected, not silently reinterpreted.

## 5. Trainable cell

The six active common parameters are input weights w1/w2, drift intercept,
diffusion, physical boundary and reset distance. They are jointly fitted from
complete renewal event histories plus final censoring. Initial states vary in
known physical units; reset intervals identify reset distance. The fit reports
parameter changes and group gradient norms, starting and final objectives,
optimization calls, actual costs, and censored/event counts.

The source and derivative checks precede confirmation. Training, development,
policy calibration and confirmation use disjoint identity streams. Candidate
selection never reads confirmation outcomes. Repeated within-trajectory events
are not independent training-seed replicates.

## 6. Boundary mechanisms and fairness

All action policies receive the same public state, inputs, price, horizon and
fitted cell. Physical failure and voluntary maintenance are different boundaries.

The main mechanism pair has the same six common physical parameters and one
policy-gap calibration parameter selected from the same frozen grid using the
same development episodes. The ordinary comparator is cost/horizon-aware and
uses a first-event continuation approximation. The endogenous-value comparator
accounts for all renewal events, resets and refractory periods. The comparison
tests this particular continuation mechanism, not superiority over all SNNs.

A fixed-boundary six-parameter arm is a structural reference. A seven-parameter
fixed-boundary arm fits an additional u1*u2 drift coefficient; this is an active
predictive parameter, not unused padding. It matches the total parameter budget
but changes predictive allocation and is not a pure boundary-only ablation.
Always-wait, always-repair and stop policies are additional strong fixed controls.
A numerical implementation of the same renewal law checks functional equivalence.

The calibration bias modifies action selection only. It does not change actual
task costs, the external reward, or the registered NDU utility profile.

## 7. Task execution and NDU value semantics

The controlled maintenance task rewards actual active operating time, charges
each actually incurred failure and voluntary maintenance, and deducts time
spent refractory. Stop terminates the episode. Policy output is executed before
the subsequent outcome is scored. Each realized action, event time, cost,
active duration and terminal result is retained for independent recomputation.

The existing Hepta signed-Q32 additive finite-horizon recursive evaluator and
V2 candidate-policy selector are called through a source-bound native bridge.
For this profile U[k] = clip(instant[k] + discount[k]*U[k+1]) with the exact
registered rounding, bounds and objective. This is not an entropic/exponential
profile or a generic FBSDE solver. Unknown or mismatched profiles are rejected.

Model-planned continuation and deployed replanning are explicitly named.
If candidate values assume WAIT_AFTER_CURRENT, deployment that replans every
half second is MPC_REPLAN_EACH_HALF; those values are not relabelled as the exact
Bellman values of the deployed adaptive policy. Planned values and realized
returns are both recorded. Future reset-event rewards are included at their
correct remaining times.

Native expected-path evaluation proves the invoked recursion and transport;
prediction calibration, policy utility and a whole-system implementation remain
separate evidence. Q32 conversion error, model/plan error and numerical
integration error are reported separately.

## 8. Evidence and lifecycle

The protocol is committed before confirmation. Source, parameter and native
binary/source identities are frozen before any confirmation environment is run.
All registered seeds and arms are retained, including failed fits and negative
outcomes. Failure handling cannot silently resample favorable trajectories.

Confidence intervals resample independent model seeds and paired whole episodes.
The finite number of seeds makes bootstrap intervals empirical, not finite-sample
coverage guarantees. Realized costs and uncertainty are reported even when an
efficacy threshold fails. Implementation completion and empirical advantage have
separate dispositions.

The package uses research-owned checkpoints and versioned outputs. It does not
replace the current Agentd state backend or grant execution authority. No model
gain is claimed from numeric conformance, test counts or deterministic replay.
