# Review of frontier.py (2026-11-06)

Read isolated source: `/workspace/scratch/e5ecafe4ccc8/hepta-research/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_deadline_frontier_20261106/frontier.py`.

## Core construction

The shared-history LP, actual duration checks, and exact trajectory evaluator are consistent with the finite-tree theorem. The independent Lagrangian Bellman lower certificate is correct: at each history its absolute nature masses weight `lambda` terminal errors and `mu` stage charges. An action adds all observable child values without multiplying their nature probabilities a second time, because each child's mass already contains that factor. Minimizing locally defines one common history policy and computes the exact infimum of the weighted loss/charge objective. Subtracting `sum(mu)*budget` yields a valid lower bound for all budget-feasible policies. Exact normalization of `lambda` makes this valid even though the LP bounds `eta>=0` and its raw error multipliers might sum below one.

## One delivery issue to fix

`solve()` corrects a rounded over-budget policy by returning a separate `mix` and mixed `errors/resources`, but `policy` and `root_actions` remain the *unmixed* base policy. Thus calling `evaluate(result['policy'])` need not reproduce the reported certified result after a repair. The correction is mathematically valid, but the executable artifact should incorporate it directly: multiply all root action probabilities by `mix`, add `(1-mix)/2` to each root STOP action, leave every descendant conditional distribution unchanged, then reevaluate the resulting policy exactly. Alternatively return a fully explicit wrapper policy and clearly label root_actions as base rather than certified. Direct incorporation avoids ambiguity and permits a meaningful roundtrip assertion.

## Essential boundaries

- This is expected-resource control per catalog member. It does not make each random path's bill <= B. The history construction does enforce the hard declared deadline.
- Generated `root_actions` contain only local root conditional probabilities, not complete deployment policy unless the full indexed history policy is also retained.
- A lower/upper interval with exact rational arithmetic is rigorous even with a positive gap. Do not round a positive exact gap to zero when claiming exact optimality.
- Model support, all durations, action costs, observed-state transitions and answer orientation are supplied. Do not rebrand rational arithmetic as real-world timestamp validation or learned uncertainty.
- `node_limit` is an explicit scalability boundary, not a hidden fallback that alters the problem.

## Reproduced delivery discrepancy

The separate-mixture issue is observed, not only hypothetical. With `Contract(1,family='bernoulli')` and budget `5928486/1000000007`, the solver returns `mix=1167398181655056199102600/1167398181655056214382883 < 1`. The returned reported resource equals the budget exactly after the mix, while `evaluate(result['policy'])` returns `3502194520449807/590740122345767300`, which is strictly greater than the budget. The two reported/evaluated risks also differ. Exact arithmetic confirms the excess although it is tiny numerically. See `POLICY_REPAIR_REPRODUCER.json`. Incorporating the mixture directly at the root fixes both executable feasibility and receipt roundtrip.
