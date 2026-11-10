# Finite-cohort value gate

The existing study reports descriptive means and source bootstraps on observed
policy outcomes. This calculator retains every frozen source/context in the
denominator. A missing or unpriced outcome uses its predeclared utility interval;
it never becomes zero or a model prediction. Contexts are equally weighted within
each source, and sources are equally weighted. Per-method one-off training/tuning
cost is debited over the exact planned cohort size in common utility units.
This is an explicit per-task amortization contract, not derived per-source billing.

Every baseline must be declared before evaluation. Only fully observed and priced
cohorts exceeding the practical margin against every baseline receive RESEARCH_PASS.
Missing one-off cost prevents a numeric net comparison. This is finite-cohort
arithmetic, not a confidence bound for new sources, proof of observer provenance,
or certification that the declared bounds/cost scope cover reality. Adoption
authority is always false. The caller must separately bind terminal observations
and independently justify bounds, tariffs and the complete cost scope.

Four manufactured regression tests pass: source weighting and baseline veto;
missing contexts retained in the denominator; full one-off and unknown costs;
plan mismatch, duplicate results, predictions and unregistered contexts rejected.
No real paired policy evaluation or scientific benefit is established here.

Reproduce: PYTHONPATH=scripts python -m unittest ndu_real_runtime.test_metacontrol_value_gate -v
