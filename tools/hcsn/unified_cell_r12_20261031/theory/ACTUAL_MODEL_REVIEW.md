# Actual finite-model review

`audit_contract.py` imports the real `contract.py` and `models.py` read-only.
`actual_model_raw.json` records exact hashes of the files inspected and checks
that they did not change during the run. Re-run after changing those sources.
This audit is distinct from the reference fixtures in `audit.py` and from the
numerical qualification of the inherited financial formulas.

## Verified on the recorded source snapshot

The model has 20 states: eight active sites and two recovery phases for each of
two content classes. Its rates are nonnegative and row sums vanish. Recovery has
two exponential phases with mean duration `0.35`. The stated retention rule keeps
the bit with probability `0.75` and otherwise redraws a fair bit, yielding an
effective same-bit probability `0.875`, not `0.75`.

For the true-model parameters, the financial boundary was `65.01984023391907`.
At the three intervals `0.15`, `0.45`, and `1.05`, SciPy matrix exponentiation,
Torch matrix exponentiation, and independent Poisson uniformization agreed below
`1.2e-15` entrywise. Maximum mass error was `3.11e-15`; semigroup composition
error was below `8.1e-16`.

The actual first-order gradient bridge was followed through the financial
boundary, reset distribution, row generator, matrix exponential, equity, and debt.
Central differences in the three raw physical parameters differed from autograd
by at most `6.43e-12` on the stated scalar fixture. A separate fixed-prefix content
loss had finite nonzero gradients in all three raw parameters and in the emission
logits. This verifies a local gradient path, not global optimization or an
independent proof of the financial formulas.

Generic HMM filtering with the exported identical model matched the trainable
distribution cell's causal posterior to `1.53e-16`. Changing every unread token
to another valid dummy symbol changed outputs by exactly zero. The check passes
no actual future observations or privileged posterior to the forward call.

The decision world repeats one announced interval throughout each episode, so
the common controller's repeated single-`P` recursion matches that time contract.
A three-row clock-only construction checks this property without any actual READ.
Sequence fitting separately retains varying intervals within each history.

## Continuous first-passage discrepancy remains material

The actual active locations are cell centers `x_i=(i+1/2)h`, with `h=0.1`.
The first site's killing rate equals the ordinary interior downward rate; it
does not contain a half-cell absorbing-boundary correction. The upper boundary
also suppresses outward motion. These are specific finite-chain choices.

At the first site `x=0.05`, comparison with the same drift and volatility's
continuous first-hit formula, with no upper reflection, gave:

| Time | Finite chain | Continuous first-hit probability | Absolute difference |
|---|---:|---:|---:|
| 0.15 | 0.3876312038 | 0.6613844372 | 0.2737532333 |
| 0.45 | 0.6091974000 | 0.7970347979 | 0.1878373979 |
| 1.05 | 0.7336504172 | 0.8634308655 | 0.1297804483 |

No continuum-accuracy gate has passed. This discrepancy does not invalidate the
finite CTMC probability law or same-model comparisons, but it precludes calling
the current eight-site chain an accurate evaluation of continuous first-passage
probabilities. Spatial refinement, lower-boundary discretization, and upper
truncation must be studied separately for that claim.

## Scope of financial and learning claims

The boundary parameterizes reinjection. Drift and volatility govern active motion;
equity and debt enter the declared synthetic task rewards and read costs. Exported
financial `F` and `G` are diagnostics in this implementation, not separate active
channels. Recovery and bit renewal extend the original model. The boundary has
not been proved optimal for these synthetic task rewards.

The custom financial autograd bridge is first-order and CPU-specific. Its
upstream drift-dependent upwind rates have a kink at zero drift. This audit uses
a local smooth parameter point and supplies no higher-order-gradient guarantee.
The exact same-model generic Bayes result identifies the inference as ordinary
finite-state Bayesian filtering with a chosen structured generator; it supplies
no evidence of an HX-exclusive filtering mechanism or general learned content
capability.
