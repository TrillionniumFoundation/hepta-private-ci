# P1: actual physical cost tail-risk admission (shadow, fail-closed)

Status: **DRAFT / HOLD_NO_GO / DENY_ALL**. This scoped child of #3339 at pinned parent `26ead9ac950166dca2c30b85a5674424ae409b84` adds a predeclared physical tail-cost gate; it never modifies #3055's source-frozen generator or the negative #3039/#3213 heldout results.

## Identified fail-open comparison

The parent demands that the mean NDU/controller cost ratio **and** the Bonferroni-adjusted seed/world bootstrap upper bound both stay within the registered 1.05 ratio. Neither bound constrains the **observed worst 10% resource spending**.

A deterministic 3-seed x 32-world research example with the same encoder/backbone/decoder and cost units yields, in every seed:

- 29 NDU episodes cost 0.97 units each and 3 episodes cost 1.35 units each.
- All ordinary controls cost 1.01 units per episode.
- NDU mean/control cost ratio **0.995668** (PASS).
- Paired hierarchical bootstrap ratio upper bound **1.03094** (PASS; 2,000 draws).
- Fractional-mass CVaR90 cost ratio **1.3131188** (FAIL), because 3.2 worst-decile episodes per seed include 3 expensive and 0.2 inexpensive requests.

The project cannot report *equal actual resources* when the tail explodes even if the average and its bootstrap uncertainty appear acceptable.

## Fix

Require finite preregistered `max_tail_cost_ratio` between 1.0 and 1.1 with **no fallback**. Compute fractional-mass empirical CVaR90 for actual `measured_cost.total` separately within each registered training seed, then average seeds and divide NDU by the same comparator's measured cost tail. Every one of six comparisons must pass this additional gate. Keep and expose both old mean-point + cost-bootstrap gate and new observed physical tail gate; never conflate them with resource-unit authentication or with an absolute per-world physical budget.

Three new regression methods cover missing declaration, the rare-spike falsely passing prior mean/bootstrap tests, and positive constant-cost controls. The existing formatter/pytest/Rust/CI gates remain unchanged.

The scenario above was independently executed in a local CPU test fixture using the original #3251 evaluator plus the tail-risk correction; no claim is made that the exact combined #3339 child source has passed its own GitHub CI until that exact SHA's workflow finishes. Both the favorable and adverse synthetic examples retain `HOLD_NO_GO` and `DENY_ALL`.

## Boundaries

- These are caller-supplied numerical cost observations, not hardware-signed meters.
- Actual per-world hard caps (e.g. parallel research #3270), source-group bootstrap (#3257), protected-world semantic and custody fixes (#3332), and exact-source CI need independent reconciliation; do not overwrite or duplicate those branches.
- No scientific or production superiority, final-use grant, model deployment, target-host operation or authorization follows from this patch.
