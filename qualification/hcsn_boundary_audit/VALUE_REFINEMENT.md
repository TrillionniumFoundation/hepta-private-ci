# Independent review of the retained-law P1 failure

The observed continuation failure is real for the declared projected chain and
the reconstructed recorded law. I found no prior/posterior indexing error,
finite-versus-perpetual comparison error, or repeated terminal-payment error.
This conclusion is limited to the retained-law continuation diagnostic; it is
not a percentage error in task loss or the remaining asynchronous trajectory.

## Semantic checks

- `audit_training_domain.derive_visits` reconstructs the first prior with the
  source-declared absolute initial location `exp(.55)` and the recorded physical
  boundary. Later priors are the preceding observation-conditioned posterior.
  This agrees with `network.forward`, whose event receipt is produced during
  `operator.advance` before the current observation update.
- `value.perpetual_basis_value` uses discounted active occupation and event
  rewards only. It does not reuse `OperatorTable.call`, so the endpoint terminal
  feature is excluded from every Bellman continuation step.
- The high-precision reference and projected Bellman solve both value the same
  fixed boundary, reset location, deterministic refractory delay, active reward,
  hit reward, and discount policy. Neither computes an optimal free boundary.
- For each recorded posterior, the auditor repeats that record's positive
  `dt` indefinitely. This is a fixed-cadence continuation probe from that law,
  rather than a replay of future asynchronous observations. The zero-time
  fallback is disclosed by the auditor and is not used by the selected case.
- The scaled value error is `abs(projected-reference)/max(1,abs(reference))`.
  The reference exceeds 1 in this case, so the displayed number is its relative
  value error. The original 0.01 limit has not changed.
- The passing 80-digit gradient check differentiates the analytic continuum
  basis coefficients while holding the posterior fixed. It does not establish
  that the projected Bellman value, learned posterior, or whole training
  trajectory has a continuum-accurate gradient.

## Independent component isolation

The selected case is the same retrospective maximum in seed 11, arm c0_b0,
visit 39 used by the parent probe. It has `dt=0.001`, `sigma=0.35`, and
continuum value `4.451977681702048`. All comparisons preserve its continuous
initial law exactly by uniform subdivision; the returning tail is unchanged.
The standalone script checks the parent result, original audit, and derived
trace hashes, and uses a separately written 80-digit basis integral.

| Active cells | Phase cells | Quadrature | Projected value | Scaled error |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 8 | 32 | 7.668510481900419 | 0.7224952661866555 |
| 256 | 8 | 32 | 4.706157069966479 | 0.057093589958711326 |
| 16 | 128 | 32 | 7.66671160519838 | 0.7220912038056978 |

The parent's joint 256-active/128-phase result is
`0.057025075827649`. Its original-basis q16 and q64 results are respectively
`0.7225534899552492` and `0.7224953411967283`. Spatial basis refinement accounts
for almost all of the improvement in this case; phase refinement and additional
quadrature points have much smaller effects. All cases still fail the original
1% limit. This is a selected diagnostic, not a domain-wide qualification or an
estimate on independent task sources.

## Explanation and minimum next experiment

The original active-cell width is 0.3, whereas the diffusion displacement scale
at `dt=0.001` is approximately 0.0111. Replacing each propagated density by a
uniform density in each active cell after every short interval repeatedly
discards within-cell location. For a uniform interior cell, the short-time
mass crossing an adjacent edge is proportional to `sigma*sqrt(dt)/cell_width`;
a repeated coarse-cell chain can therefore introduce excessive effective
spatial mixing as `dt` decreases at fixed cell width. This mechanism is
consistent with the component controls. The controls identify the spatial
projection as the main source in this case; they do not isolate every spatial
error mechanism throughout the visited domain.

The minimum useful repair experiment should preserve a pinned reconstructed
law and the same original threshold while changing the spatial representation
or the consistency of repeated propagation. Candidates include retaining
within-cell shape or moments, a suitable near-boundary/reset basis, or a
conservative generator whose repeated propagation has the intended continuum
limit. Increasing the existing uniform grid to its current 256-cell maximum
is insufficient for this selected short-gap case. A lower-cost representation
must retain first-hit flux and reset/refractory semantics before compression
or runtime gains can count as progress.

Substituting the closed analytic continuum value as a readout would remove
this particular value discrepancy while leaving the projected risk and content
transport unchanged. It would not establish that those operations have been
repaired. Row normalization and a small Bellman solve residual likewise do not
address this projection bias. No numerical threshold was relaxed, and no
original experiment, audit, or source file was modified.

## Actual execution

The independent three-point diagnostic exited 0. Its process wall time was
1.487749196 seconds and its outer subprocess time was 3.632189023 seconds in the
shared CPU environment. The recorded per-row intervals cover one uncached
transition/reward build and dense Bellman solve. They are not network training
or inference throughput measurements. Source, complete raw results, stdout,
stderr, and the execution receipt are retained with this review.
