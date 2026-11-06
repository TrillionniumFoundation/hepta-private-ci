# Exact deadline feasibility after the NDU negative reference

This unit closes a finite **attainability** gap: a necessary KL/occupancy bound
can permit a deadline even when no common observable-history policy meets it.
A classical sequence-form LP now constructs that common policy, while exact
rational evaluation certifies achievable error/resource and a separate exact
Lagrangian Bellman calculation supplies a lower bound. Float solver success is
never the certificate. This is a benchmark, not a new RL algorithm.

## Contract and result

The joint-label/duration task imports the unchanged known likelihoods from
`../ndu_identification/model.py`. Failed queries and cancellation are charged;
events hidden after a cap are aggregated, not disclosed. Three launches are
permitted, each priced at 1/40 plus 1/100 per actual consumed model-time unit.
The model-time deadline is pathwise. Resource B is an **expected** limit under
each of the two hypotheses, not a pathwise spending cap or a prior-average cap.
Both hypotheses share one randomized full-history policy. Terminal correctness
is fixed externally. Runtime/CPU of solving is measured separately and unpriced.

The complete grid has 31 LP cells and 31 analytic binary-catalog rows. With no
additional expected resource cap, the original joint task gives these **exact**
minimum maximum conditional errors:

| Hard model deadline | Minimax error | 5% attainable? |
| ---: | ---: | --- |
| 0 | 1/2 = .5 | No |
| 1 | 8/25 = .32 | No |
| 2 | 451/2000 = .2255 | No |
| 3 | 17/250 = .068 | No |
| 4 | 1/20 = .05 | Yes |

At deadline 4 and expected resource B=1/20, error is exactly 59/550,
approximately .1072727273. B=1/10 admits the .05 rule. Every declared cell,
including impossible targets and zero-budget STOP, is kept in the result.
An additional gated family requires paid preparation before information becomes
available: deadline 1 forces risk .5; deadline 2 permits .1. Its resource-limited
case B=.05 has exact risk 3/14. This is a designed mechanism, not new task data.

In the inherited `.57/.87` calibration catalog, the sharper analytic result is
**22 complete macros are insufficient; 23 suffice for uniform 5% error**.
The latter risk is .048835172241606405. Each complete macro costs .30 and takes
three model units, so the hard calibration-time cap is 69. The proof, exact
threshold construction and nonoptimal expected-cost boundary are in
[BINARY_DEADLINE.md](BINARY_DEADLINE.md). This does not transfer an unlimited-time
SPRT guarantee to a deadline or change the earlier 144-cell lifecycle failure.

## Why the certificate is meaningful

[THEORY.md](THEORY.md) proves both directions of the realization-weight
equivalence and gives the resource/risk LP. The fitted solver's output is
converted to a normalized rational behavioral policy. If rounding would exceed
B, an explicit fair-STOP mixture is written into the returned root policy and
re-evaluated. This fixes a concrete independent-review counterexample; merely
adjusting a reported number would not yield an executable certificate.

For rational lambda>=0 with sum one and mu>=0, a separate Fraction recursion
computes the minimum over all shared policies of weighted error plus priced
resources, then subtracts B times the summed resource multipliers. It remains a
valid lower bound even if proposed floating dual coordinates are inaccurate.
Thirty of the 31 LP intervals have zero exact gap; the larger 13-macro tree has
a rigorous gap below 1.8e-7. Its separate analytic minimax value lies in that
interval. No larger gap is silently labeled exact equality.

## Internal review and numerical changes

The source and evidence under `evidence/first-complete` are retained with a
lossless source snapshot. Accepted inputs additionally reject floating
probabilities in the exact binomial interface and require full catalog charges.
The accepted run is in `evidence/accepted`; these are deterministic development
computations, with no new random sample, external preregistration or model call.

Two separate internal reviewers checked the formulation. Independent pure-policy
enumeration plus a mixture LP agreed on 50 small contract/budget cases to
5.56e-17; rational scalarized values agreed exactly. The review also enumerated
binary observation strings through n=8 and exposed the stronger random-STOP cost
baseline. Its 2,745 assertions are deterministic checks, not 2,745 scientific
repetitions. A separate 41-check theory verifier covers exact KL/attainability,
randomization and joint/censored-information counterexamples. Review artifacts
retain the original source hashes and are not claimed as external review.

The finite-sample bridge in the theory only says that existing uniform row-TV
bounds can tighten fitted constraints. If tightening makes them infeasible,
there is no learned certificate; STOP is not a 5%-error identification fallback.
No useful uniform unknown-kernel certificate or novel RL contribution follows.

## Reproduce

From the repository root with NumPy and SciPy:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_deadline_frontier_20261106.test_frontier -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_deadline_frontier_20261106.study --output /tmp/ndu-deadline-new
```

The output directory must not exist. The compressed certificate artifact is
lossless JSON containing every contract, complete rational policy and proposed
lambda/mu. Hashes bind all executed code and the inherited kernel. No source,
old score, confidence level or historical negative result was rewritten.
