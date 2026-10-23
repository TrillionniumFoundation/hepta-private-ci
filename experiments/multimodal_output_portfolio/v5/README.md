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

## Bounded System 2 search cost

`JointController` counts unique Bellman state expansions with an exact integer
`max_expansions` cap. If the cap is reached, `select_with_fallback` returns
the feasible `STOP` action with an explicit `BUDGETED_STOP_FALLBACK`
disposition. It **does not** report the STOP valuation as a certified optimal
continuation. The search-work cap is separate from the modeled four-output
physical budget: the number of expansions is a computational complexity
counter, not measured CPU time, energy or actual GPU usage. Tests cover
both exact-small-state and exhausted-budget dispositions.

## Falsification and explicit assumptions

An *intentionally adverse* observation-law shift freezes the controller's
98%-accurate witness model and applies an actual **2%-accurate** report channel
during independent external evaluation. A once-helpful query becomes worse
than no query. This is a counterexample to an out-of-distribution reliability
claim, not a measured natural-data error rate.

A zero-probability hidden-truth branch cannot poison entropic risk arithmetic.
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

The 12 focused tests include risk recursion versus independently enumerated
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
