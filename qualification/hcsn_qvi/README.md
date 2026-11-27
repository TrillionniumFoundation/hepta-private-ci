# Finite DP/QVI boundary oracle

This is a small P3 **control fixture**, with three explicit groups: a fixed
threshold, an ordinary fitted logistic threshold, and the optimal policy of
one finite discounted impulse-control problem. It supplies an independently
checkable oracle before any claim about useful neural free boundaries.

## Exact model being solved

The state grid covers `[0,2]`. A monotone birth/death approximation has drift
`mu=-0.2`, volatility `sigma=0.35`, and reflecting endpoints. Waiting earns
reward `g(x)=x` per unit time. An intervention pays a cost of `0.6`, waits
`0.2` time units with zero reward, and resets at `1.37` using fixed linear
interpolation. Discount is `0.15`. The initial value is evaluated at `0.8`.
These numbers are a declared synthetic fixture, not fitted sensor utilities.

For the finite generator `Q`, the control equation is

`max(Q U - q U + g, -cost + exp(-q*delay)*w_reset @ U - U) = 0`.

Uniformization gives a discounted Bellman contraction. Policy iteration and
independent value iteration solve that same finite problem. Residuals report
the generator and intervention equations separately because their units differ.
The small seven-state test also exhausts all 128 deterministic policies.

The ordinary baseline fits one logistic threshold by implicit policy-value
gradients and bounded line search. It does not consume the QVI active set.
Its finite iteration budget is disclosed and its local fit is not claimed
globally optimal. Every policy evaluation and gradient solve is counted.
Fixed/learned/oracle values are control diagnostics, not evidence that HCSN
outperforms an ordinary neural gate on a real task.

## Boundary, gradients and costs

The report includes the action set, its threshold bracket when it is a prefix,
Bellman/complementarity residuals, matrix condition number, cost perturbations,
and active-set changes. Implicit cost gradients are compared with central
differences only when both perturbations retain the same action set. A separate
test crosses an action-set change and rejects the smooth-gradient claim.
The 21/41/81-node comparison records discretization sensitivity. Reflecting
truncation, interpolation and discrete boundary location preclude a continuous
QVI or smooth-pasting certificate.

Wall times cover each algorithm on the executing CPU. They are not a neural
inference benchmark or a physical energy measurement. A useful task-driven
boundary still needs real task rewards, independent oracle agreement, content
and probability gradients, preregistered training resources and an advantage
that covers its optimization cost.

```sh
python -m unittest qualification.hcsn_qvi.tests.test_oracle -v
python -m qualification.hcsn_qvi.run_oracle --output /tmp/new-qvi-receipt.json
```

The runner binds source hashes and refuses to overwrite a previous result.
