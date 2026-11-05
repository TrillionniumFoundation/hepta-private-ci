# Frozen STOP-relative reference policy

`stop_policy.py` consumes externally admitted evidence and returns a pure
proposal. It does not run a model, authenticate an owner, establish coverage,
execute a payment, qualify adoption, or change chainwork. It is not wired into
`critic_choice/run.py` or the native runtime.

## Evidence and state boundary

`Cohort` pins critic, objective, continuation policy, utility unit, and generation.
The objective must specify its risk functional, gamma when applicable, cost
conversion, and remaining-return boundary. `support_sha256` pins an independently
admitted support protocol with simultaneous coverage over the action and finite
monitoring roster. A matching hash checks identity, not truth or chronology.
The existing factorial bootstrap is exploratory and cannot supply this admission.

`state_sha256` must bind the full public decision state, history/input, remaining
budget, horizon/steps, and applicable owner authority and deadline. The existing
runtime `Snapshot.digest` covers state, input, profile, charged prefix and RNG;
it does not itself authenticate authority or add an absolute deadline. A future
adapter must bind those missing owner fields. `Report.available` must equal the
live resource vector, so planning charges invalidate a stale resource report.
Refreshing a field is not evidence that the old Q bound remains valid.

Every action, including STOP, has an owner-supplied hard admission and an integer
resource envelope covering the complete continuation and delivery. Hard denials
and resource limits apply before utility comparison. No admissible STOP means
rejection and an owner-qualified fallback, not permission to deliver anyway.

## Decision and exploration

Continue for supported benefit only when `lower(Q_action) - upper(Q_STOP)` is
strictly greater than the frozen nonnegative `minimum_gain`. Positive ties use
the action roster order. Net Q already includes future cost and risk; resource
reservations must not be subtracted from Q again. Nonfinite bounds or differences
are rejected. Existing critics predict log moments and minimize them:
`Bound.from_log_moment(L, U, gamma)` converts to CE bounds `[-U/gamma, -L/gamma]`,
with positive finite gamma and outward endpoint rounding. A raw critic prediction
is neither a net-Q bound nor a qualified confidence interval.

Otherwise, only predeclared admissible unresolved actions can use the separate
research pool. An action whose upper gain cannot exceed the threshold is not
explored. Each research proposal consumes one call and its full resource envelope
in `next_allowance`; success, failure, cancellation, or timeout cannot replenish it.
When no research action fits, the result is STOP.

The caller must atomically persist the general resource reservation and
`next_allowance`, using `request_sha256` as an idempotency key, **before dispatch**.
Retries return the stored proposal; concurrent callers must compare-and-swap the
same prior balance. Reconstructing `initial_allowance()` after restart defeats
the cap. This module provides no durable store or concurrent authorization.

## Reproduce

Run from the repository root, using only the Python standard library:

```sh
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_stop_policy -v
python -O -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_stop_policy -v
```

These are control-boundary tests. They do not establish natural-task gain,
future-window qualification, semantic validity, durable owner integration, or
production readiness.
