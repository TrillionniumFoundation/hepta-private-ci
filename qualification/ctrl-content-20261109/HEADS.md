# Shadow implementation and control investment heads

Research only; production admission remains false. This follows the identity
observations on #5450. #5451 is an independent sibling, not merged into this work.

The logistic head predicts observed payload-identity continuity, separately from
semantic correctness. Missing, incomplete or self-observed stages stay unknown.
The linear head targets one real continuation versus STOP:

`(gross_continue - full_cost_continue) - (gross_stop - full_cost_stop)`.

Two completed separately observed branches must share the pinned start snapshot,
source, public state, evaluator, utility and tariff profiles, with distinct
operation IDs and exactly one continuation. All eight declared cost categories
must be measured in common utility units. Unknown prices never become zero.
This declared cost scope is not proof of complete physical/lifetime accounting.
Paired subtraction avoids charging common sunk costs again. Authentication of
observers and the common starting state remains external.

The implementation estimand is identity-continuity probability conditional on
public state and a complete admitted identity observation. The value estimand is
mean paired net-return difference conditional on public state and a complete
admitted matched branch pair. Unknown labels are excluded, rather than coded as
failures or zero returns. Without missingness assumptions these complete-case
estimands do not describe all attempted actions or all attempted branch pairs.

Only training rows fit heads; calibration sources must be disjoint. Residual
summaries use source maxima and source counts. Inference takes only public belief,
pending evidence, freshness, legal actions, budget, predeclared context and control
action. Unsupported contexts, actions, legal inventories or feature ranges
abstain. Pooled/conditional residuals are descriptive, without coverage claims.

Tests actually fit manufactured protocol data. No #5450 real-data fit, native
training or policy evaluation has occurred. A fully trained real point critic,
useful/redundant/noisy READ controls and independent real returns remain pending.
No qualified matched STOP/continuation dataset with authenticated full costs is
available in the public records. This module does not invent one or admit dynamic
control. Promotion requires complete-cost gains over light and tuned fixed.

The final combined run passed 29 tests with zero skips, including four label
contract tests and five shadow-head tests. Observation contracts are a separate
stage described in `OBSERVATIONS.md`; existing head-module public imports remain
available for compatibility.
See `VALIDATION.json` for runtime, suite counts and the retained log identity.

```sh
PYTHONPATH=scripts python -m unittest ndu_real_runtime.test_control_investment -v
```
