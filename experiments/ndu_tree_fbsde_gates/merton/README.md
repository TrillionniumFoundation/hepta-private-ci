# NDU-Merton finite control experiment

Research-only / DENY_ALL. Parent: `dcc92f52ea105ef371f9d792a5d411519dd92b90`
(PR #1923). This is an additive finite known-law mechanism experiment. It does
not replace the existing two-bit oracle, global FBSDE obstruction, native NDU,
Neuron, Reader, production execution owner or model artifact lifecycle.

## Model and falsifiable scope

The state contains remaining tasks, separate token and duration budgets, an
synthetic resource-capital flag (not selected model parameters), bounded preference and public sensor
history. Hidden bits and sensor errors are integrated out, never passed as
realized future truth to a policy. Both exact solvers enumerate admissible
controls; neither is a fitted neural model. Action duration is explicit.

Controls are submit, quit, purchase a bit/hint, and buy a specified synthetic
capital upgrade. The upgrade costs two resource units and an external fee,
then reduces future bit-query resource consumption from two units to one.
It is NOT actual model training, an optimizer step or a proven learning curve.
The 15 registered cases examine complementarity, budget/deadline exclusion,
correlated errors, information cost, finite investment horizon, expensive
investment, observed resource shocks and outcome-driven preference changes.
No real data, new LLM call, GPU measurement or future-task efficacy is claimed.

A fixed external outcome is binary task success. Common external reporting is
sum(success) minus separately declared external utility fees. Resource budgets
constrain feasibility; no shadow-price penalty is additionally charged. The
integer token/tick/fee quantities describe the synthetic environment, not
hardware observations. Process CPU and wall counters are recorded separately
for planning and auditing; they are self-reported, not independently attested.

Three recursive profiles use R_alpha(V) = (1-alpha) E[V] + alpha min_support(V).
This is monotone and cash-additive, and uses exact rational arithmetic. Neutral
alpha is zero; fixed alpha is 1/4; endogenous alpha is the public preference.
After an independently specified observed task outcome, preference decreases by
1/8 on success or increases by 1/4 on failure, clipped to [0,1/2]. The outcome
criterion, rule and bounds are fixed. No optimizer can rewrite them. This is a
DISCRETE SPECIAL CASE motivated by NDU semantics, not the original continuous
neural FBSDE, a learned preference filter or evidence of preference identifiability.

Five controllers are no-computation, myopic value of information, exact neutral
Bellman, exact fixed-profile recursion and exact endogenous-profile recursion.
Every sealed policy is rescored under ALL THREE profiles and the same external
metric. An independently implemented augmented-state Bellman reference must
match every optimum under the SAME profile. A change of preference/utility is
not an algorithmic improvement. Exact equality is an expected falsification
control, not a novel NDU performance victory.

## Reproduce

From the repository root, using Python 3.13 and only the standard library:

```sh
D=experiments/ndu_tree_fbsde_gates/merton
python -m unittest discover -s "$D" -p 'test_*.py' -v
python -O -m unittest discover -s "$D" -p 'test_*.py' -v
python "$D/portfolio.py" --output /tmp/ndu-merton-run
python "$D/audit.py" --directory /tmp/ndu-merton-run --output /tmp/ndu-merton-audit.json
```

Use a new output directory for each run. Outputs use exclusive creation and do
not overwrite existing evidence. The manifest is written before solving the
panel; it is a known synthetic specification, NOT a statistically pre-registered
or blinded real-data study. Raw public-history policies bind manifest and source
SHA256 values. The separate process reconstructs likelihoods, rewards, resource
changes and recursive values without calling the planner's Model, Planner,
aggregate or preference_next. It checks every reachable selected transition,
compares exhaustive-action optima and rejects missing, duplicate, tampered,
unaffordable, unsupported or nonconserving records. Both implementations have
the same author; no independent organizational reviewer or signer is claimed.

The parent #1923 global obstruction and real-model research remain unchanged.
Short-horizon existence or low local residuals do not certify global FBSDE
consistency. Preserve blocking-ci, Architecture and all original owner boundaries.
Do not merge to main or activate production based on this mathematical panel.
A real continuation requires fixed-Reader adequate-evidence tests, equal-input
budgeted controllers, observed full lifecycle cost, and future source groups.
