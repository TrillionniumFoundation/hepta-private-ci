# Paid intervention identification with a physical-clock model

**Research-only mechanism evidence, 2026-11-05.** The accepted run is
[evidence/cancellation_complete/results.json](evidence/cancellation_complete/results.json):
18 frozen task cells, five policies each, and 520 exactly enumerated terminal
histories. The corresponding [raw histories](evidence/cancellation_complete/trajectories.jsonl)
include failures, timeouts, paid fees and negative outcomes. Probabilities and
posteriors use rational arithmetic; discounts and utility use ordinary floats.
This is a simulated clock, with computation wall/CPU recorded separately.

## What is new relative to the existing JAC example

The unknown object is **which internal execution configuration is useful**.
The old JAC task exposes a known sensing-accuracy family and optimizes its
recursive entropic control objective. This slice instead isolates paid
identification of intervention response, under a fixed, risk-neutral external
score. It is a finite Bayesian SMDP reference problem. It establishes no novel
RL algorithm, general learning guarantee, delta-PAC guarantee, hardware net
benefit, or advantage over exact DP.

Let hidden hypothesis H be 0 or 1 with prior 1/2. Choosing execution configuration
p in {0,1} and stopping gives external score 1{p=H}. Any passive initial data has
the same law under both hypotheses. Therefore passive observations cannot tell
which intervention is preferable: the best prior-only success probability is
1/2, while the two known-model optima require opposite interventions. Paid
calibration probes have known likelihoods but H remains hidden from the policy.
Learning these likelihoods from data is a separate unresolved problem.

This single-episode p=H slice is mathematically **active binary classification
and sequential hypothesis testing**. Renaming its hidden label or decision as
an NDU internal state does not establish novelty. The useful implementation
increment is the explicit joint duration likelihood, censoring, cancellation,
stopping and payment semantics, with strong exact and myopic baselines.

## Joint information, time, and fee contract

There are fast, slow, and joint probes. Every launch pays the same frozen fee c.
Fast has success probability .9 and conditional label accuracy .7, with duration
1; its failure duration is 2. Slow has success probability .9 and accuracy .98,
with duration 3; its failure duration is 4. Failure has no information about H.

The joint probe has the following full observation law:

| Observation (label, duration) | H=0 | H=1 |
| --- | ---: | ---: |
| (0, 1) | .40 | .05 |
| (1, 1) | .05 | .40 |
| (0, 3) | .05 | .40 |
| (1, 3) | .40 | .05 |
| (failure, 2) | .10 | .10 |

Each label marginal and each duration marginal agrees across H. Their **joint
law** identifies H: observing (0,1) gives posterior P(H=1)=1/9, while (0,3)
gives 8/9. Its full-observation KL divergence is .7 log(8), whereas either
marginal has KL zero. Thus discarding timing from the likelihood can discard
all useful evidence for this probe. This does not imply timing is always
necessary: an early cancellation cap changes the experiment and can convert
some of that joint information into label information.

Each launched probe selects a positive integer timeout cap no greater than
remaining time. Durations beyond that cap are collapsed into one timeout event;
their likelihoods are summed **before** the posterior update. The hidden label
and uncensored completion time never reach the policy. Cancellation consumes
its observed cap and its launch fee; it can leave time for another probe.
Completion exactly at the cap is observed. Zero time or zero remaining probes
permits only an immediate intervention and STOP. At most three probes are used.

For launch times t_i and terminal time tau, the fixed evaluation target is

\[
J(\pi)=E\left[e^{-\rho\tau}1\{p=H\}
             -\sum_i e^{-\rho t_i}c\right].
\]

The fee is charged once at launch. The discount is a declared delay preference,
not a second monetary latency charge. There is no additional runtime tariff.
Discount rho=.12 is per simulated model time unit. Computation time is measured
for transparency and is not silently converted to that unit or into dollars.

For belief b, remaining time r and remaining probes k, let K_a^h(o,d) denote
the **censored joint** observation law for probe/cap action a. Put
m=(1-b)K_a^0+bK_a^1 and b'=bK_a^1/m. Exact DP uses

\[
V(b,r,k)=\max\left\{1-b,b,
\max_a[-c+\sum_{o,d}m(o,d)e^{-\rho d}V(b',r-d,k-1)]\right\}.
\]

The maximum over probes is omitted when r=0 or k=0. Terminal choices do not
change the scoring rule. Backward induction proves optimality in this finite
model: conditional expectation gives each action value, every feasible policy
chooses one of those actions, and selecting a maximizing action attains the
upper bound at each smaller horizon. The same induction shows V is
nondecreasing in r because all smaller-horizon timeout controls remain feasible.
An independent hidden-state path enumerator verifies the DP values numerically.

## Frozen comparisons and results

The [protocol](protocol.json) fixes deadlines {0,1,2,3,4,6}, launch fees
{.025,.1,.6}, rho=.12, the prior, three-probe limit, all kernels and all policies.
The local protocol file was saved before executing its version; this is not an
independently timestamped external preregistration. No fitted parameter or
reported task is selected using the resulting values.

- **Exact:** full belief/SMDP DP, including timeout-cap selection.
- **No probe:** immediate best prior-only intervention, value .5 in every cell.
- **Myopic:** recompute one-probe value of information after each observation.
- **Fixed step:** same full observation information, but planning assumes every
  probe takes one unit. Its chosen probe runs against the actual censored law.
- **Label only:** correct clock and selectable caps, but discard duration from
  posterior updating. This is an information-loss ablation, not a fair learning
  competitor that should replace exact DP.

Selected rows below are examples from the full 90-row result, not an acceptance
subset. All numbers are deterministic expected utilities, not confidence bounds.

| Deadline | Fee | Exact DP | Myopic VOI | Fixed step | Label only | No probe |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | .025 | .578105897 | .578105897 | .418460218 | .578105897 | .500000000 |
| 2 | .025 | .611771839 | .585033269 | .368313931 | .611771839 | .500000000 |
| 3 | .025 | .654314126 | .654314126 | .625234336 | .628194295 | .500000000 |
| 4 | .025 | .656962382 | .654859052 | .621289689 | .634761385 | .500000000 |
| 6 | .025 | .660308877 | .660308877 | .613141174 | .639408739 | .500000000 |
| 6 | .600 | .500000000 | .500000000 | .500000000 | .500000000 | .500000000 |

At deadline 1 and fee .025, the wrong-clock policy chooses the slow probe,
which always times out. It pays its fee and returns .5 exp(-.12)-.025 =
.418460218, below never probing. Correct DP buys fast:1 and reaches
.68 exp(-.12)-.025 = .578105897. Costs are retained even when information fails.

At deadline 2 and fee .025, DP buys joint:1 and can buy again after cancellation;
myopic VOI buys fast:1. The .026738570 difference is the value of this model's
future information options. Myopic VOI ties DP on **16/18** cells and loses on
two. Every .6-fee cell and every zero-deadline cell stops without buying data.
These limited facts support the mechanism, not a broad algorithmic gain.

## A model repair found during this work

The initial pilot omitted selectable cancellation caps. That made action sets
nonnested: extending a global deadline could force a failed probe to run longer
and slightly lower its value. The repair adds cap selection to every competent
planner and preserves the initial result under [evidence/initial](evidence/initial/).
Its original three source files are stored in `source_snapshot.json`; their
SHA-256 values exactly match the original run. The v2 protocol records the
reason for the repair. A retained legacy deadline-field wording is clarified in
[PROTOCOL_CLARIFICATIONS.md](PROTOCOL_CLARIFICATIONS.md); the executed selected-cap
semantics are given above. Initial pilot numbers are superseded, not overwritten.

The accepted run's result SHA-256 is
`5a58d13b58979a3889e2be551bde240c7b5f71a56708bebf6fed036f5b9eef8e`.
Its source and raw-history hashes are inside the JSON. The separate
[validation receipt](evidence/validation.json) records nine passing behavioral
tests covering censored likelihoods, opposite optima, fee timing, an independent
one-step calculation, horizon monotonicity, and myopic-policy failure.

## Reproduce and next gate

From repository root:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_identification.test_model -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_identification.study --output /tmp/ndu-identification-new
```

Use a fresh output directory. Python standard library only. A new host changes
compute timing, timing-bearing result hashes and possibly final float bits.

The next meaningful gate is estimation with unknown likelihoods and legally
available intervention data, followed by independent tasks and real frozen-model
tool execution with measured timestamps. Bayes expected net utility here differs
from fixed-confidence best-arm identification. The cost-aware identification
literature must be compared directly before novelty or lower-bound claims;
relevant primary comparison targets include
[Kanarios et al., RLC 2024](https://rlj.org/papers/kanarios2024cost) and
[DBCARE, NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html).
