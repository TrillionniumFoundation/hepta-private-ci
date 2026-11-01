# Bounded autonomous policy expectation

This increment uses the exact public task, action order and fitted READ observation
law of `digital_read_before_20261031`. It imposes an additional declared terminal
horizon of one, two or three intervals. At that horizon only STOP, SUBMIT_0 and
SUBMIT_1 are permitted. It is a mathematical witness for the explicitly declared
soft policy, not the six-interval efficacy experiment and not general policy
gradient convergence.

For observed task state h, finite cell state s, fitted READ outcome o, and legal
action a, the incoming joint path measure is propagated as

`mu(next_h,next_s) += mu(h,s) * pi(a|h,s) * P(o|h,a) * T(next_s|s,h,a,o)`.

`pi` is the legal softmax of Q divided by the declared positive temperature. It
must occur before the cell transition: choosing an action selects and reweights
latent cell states. Terminal rewards are 0, `1-2p(h)` or `2p(h)-1`; p is the
teacher/reference posterior under the fitted observation law. The policy never
receives this posterior. READ, repair and elapsed-time costs are charged on the
transition that incurs them. State merging retains the complete observed history,
pending read, broken state, budget, clock and accumulated charges.

The entire sum remains differentiable through both action probabilities and cell
transitions. `prefix_mass` is never used. Detaching action probabilities is an
explicit negative control: it preserves forward return but deletes the policy
selection derivative. This is particularly clear for raw history, where the
incorrect gradient is zero even though the actual policy derivative is nonzero.

The independent sampled reference draws the hidden class, READ outcomes conditional
on that class, legal policy actions and realized cell states. Terminal scoring uses
the sampled hidden class, independently of the exact evaluator's posterior reward
calculation. Its standard error describes Monte Carlo error only. Central finite
differences check head and cell derivatives; they do not establish optimization
convergence or superiority of the learned policy.

The witness admits only bounded horizons and a bounded number of task nodes and
rejects violations. It handles delayed READ completion, failure, repair and the
remaining spent cost when a pending read is abandoned by terminal submission. It
does not read packet bytes, refit a content model or open old confirmation cohorts.

For new impulse models, a transition context contains the pre-action driver plus
an optional successful completion impulse. The latter is injected after the
elapsed interval, exactly once for a new completed observation. Legacy models
retain their original sustained-driver transition semantics.

Run the checks from the repository root with the project's configured Python:

```sh
python -m tools.hcsn.digital_mechanisms_20261101.policy_checks -v
python -m tools.hcsn.digital_mechanisms_20261101.policy_checks --output /tmp/policy-witness.json
```
