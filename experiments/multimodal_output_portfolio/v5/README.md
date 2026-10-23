# Hepta NDU-OOP v5: jointly priced evidence and four-output control

**RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**
This experiment extends the finite v4 source-only mechanism in #3393/#3409.
No v1-v4 source or frozen result is rewritten. No model is selected or deployed.

## Original blocker

The earlier four-channel allocation and paid independent witness were
implemented **as separate toy controllers**. Their respective utility gains
could not prove that a single controller chooses between paying for genuine
information, repairing generated modalities, and emitting all four required
outputs **from the same remaining budget**.

## Controlled finite mathematical model

The public state is:

`(levels[text,audio,image,video], posterior P(truth=0),
remaining physical units, stage, active Cell mask, witnessed)`.

It contains no unrevealed witness report, hidden truth, future random
innovation or sampled seed. The admissible actions are:

- `STOP`: emit all four distinct toy media objects, paying four mandatory
  decoder reserve units, with external factual and cross-modal loss;
- `REFINE(w_text,w_audio,w_image,w_video)`: charge integer work units plus
  fixed Cell activation and observe one *joint* three-branch shock;
- `QUERY`: charge one separately paid evidence unit and a decision stage;
  receive an observed binary report from a declared stochastic 98%-accurate
  channel, then update the posterior. At most one query per episode.

At every stage an exact finite entropic Bellman recursion decides among all
these actions under the **same physical modeled budget**. Every action leaves
sufficient funds for four final decoders. The terminal decoded-outcome
distribution includes externally hidden truth and can be independently
enumerated; the controller itself only receives a public posterior.

The output scorer verifies shape and completeness of actual Python toy text,
audio, image and video structures; it is not a pretrained multimodal model.
Four agreeing but false claims incur real terminal factual loss. The
independent full-path audit enumerates hidden truth, conditional witness
reports, correlated refinements and actual four-modal emissions. Nominal
Bellman values are checked against complete path entropic utility, with
weighted fractional CVaR90 and explicit paid-resource conservation.

## Fresh-episode state custody (source-level modeled budget)

A stage-zero `PublicState` must start with `active_mask=0` and
`witnessed=False`. Otherwise an unrecorded mask can waive a modeled fixed
Cell activation charge, or an unobserved witness purchase can be silently
claimed before a registered QUERY. Both are denied at state construction,
before controller evaluation or independent full-path scoring. A genuine
stage-one continuation retains its paid activation mask and witness flag,
so the ordinary finite action lifecycle is unchanged.

`test_fresh_root_custody.py` covers the activation-charge counterexample,
fabricated witness, valid continuation, and unchanged complete terminal
emission. This establishes a **synthetic input-admission invariant**, not
physical metering, real witness provenance or production NeuronRuntime trust.

## Bounded System 2 search cost

`JointController` counts unique Bellman state expansions with an exact integer
`max_expansions` cap. If the cap is reached, `select_with_fallback` returns
the feasible `STOP` action with an explicit `BUDGETED_STOP_FALLBACK`
disposition. It **does not** report the STOP valuation as a certified optimal
continuation. The search-work cap is separate from the modeled four-output
physical budget: the number of expansions is a computational complexity
counter, not measured CPU time, energy or actual GPU usage. Tests cover
both exact-small-state and exhausted-budget dispositions.

## Independent solver-cache lifecycle and profile version fence

The Bellman controller now uses a **per-instance bounded memoization cache**.
The previous class-level `@lru_cache` included `self` in every key, potentially
retaining completed episodes and their cost/preference profiles across unrelated
controller lifetimes. The cache is scoped to one controller and its frozen
`Profile`, so deleting the instance permits garbage collection. A new
admission ceiling requires 1–100,000 cache misses and at most that many
retained values per owner. Exhaustion still takes the explicit nonoptimal
`BUDGETED_STOP_FALLBACK` route; it must not be reported as an optimal action.

The public `cfg` property is read-only. A new controller is required to
evaluate a different coefficient, budget profile, objective or model generation;
already-computed value rows must never be relabeled for a new profile. Five
new regression tests check completed-instance collection, read-only profile,
cross-profile score separation, cache/work bounds and invalid constructors.
This is **Python memory-lifecycle correctness**, not physical model-generation
or deployment latency evidence. Ordinary Python reflection is not a trusted
authority boundary; production hosts must independently enforce model/profile
version and effect authorization.

## Fail-closed numerical interpretation near zero risk

A scientific audit of the bounded v5 controller found that the ordinary
`log(sum(p * exp(-gamma * payoff))) / gamma` expression loses precision
as `gamma` approaches zero even when all inputs are finite, normalized
and admitted. For two supported payoffs `[-10, -3]` with probabilities
`[0.4, 0.6]`, `gamma=1e-16` previously returned about `-5.5591`
instead of a value near its risk-neutral limit `-5.8`. This can
incorrectly change Bellman policy rankings without any change in evidence.

The finite scorer now uses `expm1/log1p` relative to the minimum
**positive-support** payoff when `gamma * payoff_span <= 1e-4`, and
normalizes the already-admitted rounded probability mass on that path.
Extremely subnormal positive risk coefficients use the mathematically
indistinguishable risk-neutral limit; ordinary `gamma=1` frozen research
scoring follows its original evaluation path. An independent 90-digit
Decimal numerical oracle, boundary-mass counterexample, and near-zero
terminal Bellman tests are collected in `test_near_neutral_risk.py`.

This is an isolated **finite numerical correctness** fix, not a
re-estimate of frozen v1–v4 outcomes, calibrated natural preference,
independent real-world reward, physical budget or model promotion.

## Falsification and explicit assumptions

An *intentionally adverse* observation-law shift freezes the controller's
98%-accurate witness model and applies an actual **2%-accurate** report channel
during independent external evaluation. A once-helpful query becomes worse
than no query. This is a counterexample to an out-of-distribution reliability
claim, not a measured natural-data error rate.

A zero-probability hidden-truth branch cannot poison entropic risk arithmetic.
The independent outcome enumerator also drops exactly zero-mass *witness and
shock paths* from the reported support count. Under deterministic perfect or
completely reversed evidence laws, nonexistent report outcomes must not
masquerade as observed coverage. Repeated visits to exactly the same
public state must yield exactly the same admissible action; otherwise the
external replay fails closed. This prevents a stateful policy callback from
quietly choosing a different action depending on private truth enumeration
order. The check only establishes finite deterministic-policy consistency;
it does **not** authenticate a real witness or establish source independence.

No benefit is asserted for unverifiable independent evidence, and no
assumption of independence among the four generated modalities is made.
The toy common-shock law is an explicit modeling simplification; it is not a
calibrated natural-data joint law.

## Reproduce exact finite mechanism tests

From the repo root:

```bash
cd experiments/multimodal_output_portfolio/v5
python3 -m unittest discover -v -p 'test_*.py'
python3 -m compileall -q joint_portfolio.py test_*.py
```

The focused tests include risk recursion versus independently enumerated
full terminal outcomes; physical emission reserve shared with paid evidence;
legal posterior updates and no label leakage; jointly false output claims;
actual state-feedback reallocation; query-vs-stop choice; risk numerical
support; invalid budgets; and a shifted witness-law adverse control.

## What this does NOT close

This is a bounded **synthetic** algorithm-level P0/R05/R03 coupling witness.
It does not make NDU utility identifiable in natural generation, implement
a true high-dimensional FBSDE solver, perform Generator/Critic 2x2 training,
provide real media decoding, validate licensed source-disjoint cohorts, give
physical CPU/GPU/energy equivalence, establish trusted witness accuracy,
prove distribution-shift robustness or attach the production NeuronRuntime
driver. Those P1-P5 scientific and authorization blockers stay OPEN.

A source-level test pass is not a real-world efficacy measurement.
