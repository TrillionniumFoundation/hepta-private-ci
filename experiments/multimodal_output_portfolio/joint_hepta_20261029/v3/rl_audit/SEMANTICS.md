# Finite RL semantic and gradient audit

This stage extends the exact online reference in #4830 and the cost audit in
#4831. It implements a bounded mathematical reference, with no trained NDU
controller, new-algorithm novelty, deployment or production admission claim.
Historical XOR and conditional-zoom results are unchanged.

## Two objectives must remain separate

Let `d = exp(-rate * duration)` for the realized duration of each branch. Costs
are paid at action admission; a terminal payoff or continuation is received
after that duration. `STOP` is immediate and terminal, including any explicitly
declared delivery cost. It has no continuation value. Failed and expired
branches retain their cost and their declared terminal outcome.

For risk aversion eta >= 0, define

```
CE_eta(X) = -log(E[exp(-eta X)]) / eta
CE_0(X) = E[X]
```

The principal recursive policy objective in `evaluate` is

```
V_eta(s) = CE_eta[-cost(s,a) + d * V_eta(s')]
```

with terminal payoffs replacing `V` on terminal outcomes. Both the sampled
policy action and the environment outcome lie inside the certainty equivalent.
This convention exposes policy randomization to risk. A mixture of action-wise
CE values is another objective and is not substituted here.

The static CE of the complete discounted trajectory return is a different
objective when rate > 0. Its correct recursion has an augmented risk coordinate:

```
W_zeta(s) = CE_zeta[-cost(s,a) + d * W_(zeta*d)(s')]
```

`risk_scaled_value` implements that recursion. `path_value_gradient` separately
enumerates complete terminal paths and their log-policy scores. It is an
independent check of the recursive objective only when eta=0 or rate=0; with
positive risk and discount it instead checks the scaled-risk static objective.
The report deliberately retains the resulting disagreement, not a failed test
that may be removed. Rate=0 is also crosschecked against the previously
committed Hepta `oracle.policy_gradient` and `oracle.solve_risk_dp`.

## What the checks establish

- Binary64 Bellman maximization agrees with independent 50-decimal-digit
  observation-contingent policy-tree enumeration over six risk/rate panels.
  Enumeration uses no Bellman maximization or cache and rejects exhaustion.
- The analytic actor derivative includes downstream tilted continuation
  derivatives and the local `(pi - tilted_action_mass) / eta` term. At eta=0,
  that term becomes the ordinary policy score times expected advantage.
- All actor coordinates are checked against an independent uncached
  60-digit Decimal evaluator with centered differences of step 1e-8. Complete
  path/score derivatives supply a further check where objectives coincide.
- Centered `expm1`/`log1p` arithmetic preserves the eta-to-zero limit without
  subtracting nearly equal tilted masses. This is numerical agreement on the
  declared finite cases, not a proof for all inputs or floating-point formats.
- Fixed-step discount in ordinary GAE can reverse a policy update when actions
  have different durations. Even lambda=1 cannot repair a wrong discount.
  Ordinary expected-return advantages can likewise reverse the update for an
  entropic objective. This is a target mismatch, not a claim that all GAE fails.
- A correlated duration/continuation example rejects replacing `E[d*V]` with
  `E[d]*E[V]`. Another example distinguishes an upfront charge from an
  incorrectly discounted charge and retains a failed branch.

The model is a complete *public-state* Markov DAG: no private world ID or future
outcome is an actor input. It allows at most 64 states, 16 actions/outcomes per
state/action, and eight decisions per path. Laws use positive probabilities
whose decimal representations sum exactly to one; omitted failure mass,
nonfinite values, cycles and ambiguous terminal laws reject. The constructor
copies and freezes state/action maps. These are model assumptions, not evidence
that a learned real-agent representation is sufficient or Markov.

## Reproduce

From the repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.test_semantics -v
python -O -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.test_semantics -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.semantics
```

`audit()` returns all panel values, complete gradient vectors, independent
references, risk-neutral limit errors, counterexamples and CPU/wall durations.
The analytic gradients cover independent state/action logits in this finite
model; they do not validate a nonlinear shared-parameter actor, learned critic,
partially observed environment, empirical risk estimator or rsEAC reproduction.
Mathematical model costs and the separately measured auditor computation are
different units. Independent arithmetic means independent implementation, not
independent institutional ownership or validation data.
