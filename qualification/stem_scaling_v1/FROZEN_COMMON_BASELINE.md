# P5 original-source frozen five-axis design (research / DENY_ALL)

This additive child of [PR #2270](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2270) at frozen source SHA `71f2c46e80941dfaa69b29f19bcbf79ee5187ba9` repairs the critical risk that an evaluator which *reports only complete eligible curves* may silently suppress unfavorable/missing groups. It adds a second, stricter **predeclared full-source experimental matrix** gate while leaving the original `scaling_frontier.py` and all historical original P4 metrics unchanged.

## Structural protocol and experiment geometry

The author must freeze one exact manifest **before outcomes**. The manifest pins:

- One common pre-existing 16-case denominator (or another explicitly fixed denominator in a future compatible schema), original source hash, withheld-label material hash, evaluator hash, base model hash, seed, method arm and distinct source-group count.
- One baseline tuple `(logical_cells, active_cells, reasoning_depth, train_rows, compute_budget_ns)` registered under the original P5 four-level profile.
- **Sixteen distinct preregistered trial identities**: the common baseline counted **once** plus **three changed values per five axes**, each changing exactly one input. All five four-level quality curves reuse the same exact baseline; do not create five independent synthetic baseline cases.
- Independently frozen complete physical quality/cost observations for all sixteen outcomes. No score, CPU, Encoder forward, RSS or held label can be invented, silently omitted, or imputed for a failed/queued original run.

`frozen_design.py` audits the entire exact registered trial set. It rejects missing or extra arms, changed model/source/scorer/held labels, changed denominators, posthoc trial-identity amendments, type forgery and fake production/teacher claims before calling the already implemented P5 descriptive fourth-level prediction-error calculation.

The presence of a manifest hash does **not prove it was actually registered before any outcomes**. That requires a separately independently witnessed timestamp or original signed PR commit. For that reason all outputs keep `prospective_registration_time_authenticated=false`, `source_publisher_or_scorer_authenticated_externally=false`, `independent_teacher_equivalence_certified=false`, `ten_t_hundred_t_extrapolation_permitted=false`, `whole_system_cost_pareto_qualified=false`, `production_accepted=false`, `DENY_ALL`.

## Exact execution

```sh
PYTHONPATH=qualification/stem_scaling_v1 python3 -m unittest discover \
  -s qualification/stem_scaling_v1 -p 'test_scaling_frontier.py' -v
PYTHONPATH=qualification/stem_scaling_v1 python3 -m unittest discover \
  -s qualification/stem_scaling_v1 -p 'test_frozen_design.py' -v
PYTHONPATH=qualification/stem_scaling_v1 python3 -O -m unittest discover \
  -s qualification/stem_scaling_v1 -p 'test_frozen_design.py' -v

python3 qualification/stem_scaling_v1/frozen_design.py \
  --frozen-design /registered/original-design.json \
  --expected-design-sha256 ACTUAL_64_HEX_SHA256_OF_ORIGINAL_DESIGN_BYTES \
  --original-observations /independently/scored/original-16-trial-results.json \
  --output /create-only/frozen-p5-description.json
```

The command will **refuse** synthetic panels if provided as real model evidence unless their full shape and claim flags are valid; passing synthetic fixture tests **does not authenticate** their producer. Do not use a retrospective fitted manifest as proof of preregistration.

## Validation and next real evidence

Two exact remote Python blobs match the locally tested originals: source `333c814cbc33a643036d61b711242c3b8994adcf`, tests `84b62776932a8f47c886d0921b22a75824c903d2`. Local source-only 9/9 normal and 9/9 `python -O` tests passed, using synthetic receipts. Existing [PR #2270](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2270) original 10 tests and this child added nine are both required by the scoped CI. Exact-head cloud CI must run and complete; queued is not green.

Still missing: independent model weights/issuer, real physical 16 trial source-matched signed cost/score, old-task retention, genuine future data, model-load/training/backward/router/FBSDE/decoder/energy boundaries, 3+ independent source families, and 10T/100T teacher comparison. No source-only pass can authorize model selection, release, Cell Split or NDU runtime effects.
