# Independent internal review of the finite-catalog cost theorem

Reviewer: the mechanism-analysis agent in the same research session.
Scope: independent reading and reconstruction of the mathematical argument,
inspection of the deterministic verifier, and matching the final source hashes.
This is not external peer review or a formal proof certificate. The review did
not rerun the author's checks or collect new data.

## Reviewed version

| File | SHA-256 |
| --- | --- |
| DECISION_COST_THEORY.md | `85a324c6a9f55e9f4e085483f56b9032daf5e2e491df4b1f78b587becdd1b1be` |
| verify_decision_cost.py | `ff196db8766e171fd4df5028e2df27ee8968607a8e115c49a0b097e7c9156fed` |
| decision_cost_verification.json | `08d4982272a047411bc0dab4abff8d49b64cb73e8a9a8eb38f3469ea40f777bf` |

The author's final receipt reports 45 deterministic checks and identical source
hashes before and after. Those 45 are not additional checks executed by this
reviewer and are not independent experimental observations.

## Findings and resolutions

Four precision issues were identified and corrected before acceptance:

1. The all-answers-identical case now returns the common answer without sampling;
   it no longer reaches normalization of the zero LP allocation.
2. The time-expanded state-flow statement now explicitly assumes a sufficient
   controlled-Markov state, and its transition kernel includes the source time.
3. Abstention is explicitly counted as wrong under both binary members. The
   displayed no-observation payment argument includes this case. Deployment
   volume is a prespecified positive integer.
4. The verifier now distinguishes the negative member's forced-deploy value
   `.35` from its optimal STOP value `.5`; the old ambiguous field is gone.

No blocking mathematical or implementation finding remains in the reviewed scope.

## Reconstructed arguments

- **Lower bound:** the common adaptive policy cancels from the likelihood
  ratio. Bounded log increments and finite expected cost permit the stopped
  expectation identity. Binary data processing applies exactly to members with
  different correct answers. Outcome-dependent charges obey the same predictable
  sampling cost identity; they need not be independent of the observed outcome.
- **Matching expected cost:** the full-catalog pilot error has the stated
  Bhattacharyya exponential bound after observationally identical members are
  legally merged. Conditional on a correct pilot, main samples are IID and the
  Hoeffding tail sum yields `L/r+O(L^(2/3))`. The wrong-pilot main cost is bounded
  by `O(L^2)` times an exponentially small probability. Uniform fallback has
  `O(L^2)` expected remaining cost uniformly over its possible entry histories;
  its entry probability makes the unconditional contribution negligible.
  Conditional Wald accounting gives the claimed cost constant.
- **Time constraint:** the flow LP is a necessary relaxation. Its feasible
  occupancies need not implement one policy across catalog members. The stronger
  full-probe Bayes-error obstruction is legitimate because observing all allowed
  probes is at least as informative as an adaptive rule using a subset.
- **Nuisance separation:** independent nuisance bits add KL, while the closest
  opposite-answer member keeps the nuisance law unchanged. Thus the decision
  constant remains fixed as full-model identification becomes arbitrarily costly.
- **Economic boundary:** zero-acquisition decisions have the same distribution
  under both members. Uniform correctness therefore requires positive expected
  acquisition cost at the member where no-data STOP is already optimal. The
  necessary and sufficient positive-member amortization inequalities use the
  lower and upper cost bounds in the correct direction.

## Limits preserved by the review

The catalog and its laws are supplied; only the true member is unknown. The
matching theorem is pointwise in a fixed separated catalog and uses exact
allocation optimization. It is not uniform over vanishing gaps or growing
catalogs, nor a proof for unrestricted unknown kernels, a fixed hard deadline,
or unpriced computation. The reference test and the same-information classical
baseline share the guarantee. Actual model/billing evidence, external proof
reconstruction and a new general RL contribution remain separate requirements.
