# Saturated-policy gradient numerical fix

Baseline: `0ea61fb707fbcc399ea2318238652efe411c6535` (#4875).

The identical five new tests were run against the fixed baseline and the repaired
source alongside the unchanged 11 original finite-control tests. The baseline
produced four error subtests in three new test methods; its 11 original tests
passed. The repaired source passed all 16 test methods. Both attempts preserve
raw stdout/stderr, source hashes before and after execution, command, dependency
versions, exit code, wall time and child CPU time in their respective receipts.

The baseline fails when finite logits separated by 2,000 make some legal action
probabilities exactly zero. At risk `1e-12`, the small-risk derivative divides by
that zero probability. At risk `1e6`, a zero-mass low-return branch can shift the
exponentials until all supported risk weights underflow, producing a nonfinite
derivative while the independent forward policy value remains finite.

The fix uses the same positive joint support as the forward certainty equivalent,
normalizes the supported risk weights in log space, and algebraically cancels
division by the action probability in the small-risk derivative. It adds no
probability floor and does not change `core.py` or the objective.

The new tests check finite value/gradient agreement with `evaluate_policy`,
the risk-neutral limit, zero masked and zero-support derivatives, deterministic
policies without artificial probability mass, and finite differences computed
through the independent forward evaluator at resolvable extreme logits.

This is a finite-control numerical regression only. No formal model training or
real multimodal experiment was started. The original unit suite includes its
existing small tabular optimization test. These results do not establish NDU
net benefit, Hepta's independent contribution, real content improvement,
production qualification or whole-repository CI.
