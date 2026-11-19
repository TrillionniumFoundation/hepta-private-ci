# Exact reset on a moving graded mesh — research candidate

This stage starts from PR #6144, exact source
`7337b31059459cd14ba3b032f6dc1c758fe49d40`. It reuses that source's
`GradedSpatialGenerator` rates/linear solves and `JointModel` dense-history
deterministic-delay solver. It introduces a separate discretization, without
changing the original uniform or fixed graded model.

## Why the mesh moves

The old two-node reset weights are continuous and piecewise affine in reset
position; their derivatives jump at nodes. The retained original-model test
records both one-sided differences at reset 0.5. Rejecting that knot does not
make the original parameterization differentiable.

Here two fixed-topology graded segments meet at `r = log(Vr) - B`. Reset is
always the exact junction node, so its unit injection has a fixed index. The
point reset is not replaced by a smoothed distribution. Analytic generator
derivatives include every spacing/rate change as the junction moves. All
five physical derivatives (B, drift, sigma, Vr, discount) propagate through
the variational DDE and every recursively delayed flux history.

`aligned_flow` supplies an actual first-order Torch CPU FP64 custom VJP for
the five parameters and the initial nodal/phase probability and signed-content
totals. Each initial-law basis is propagated by the unchanged dense-history
solver. No detached-history shortcut is used. There is a 64-law-row limit,
at most 16 signed channels, and fixed exact phase supports.

## Derivative meaning and remaining gates

The derivative holds **moving nodal weights** fixed. It does not hold an
external physical density fixed: that requires a differentiable conservative
migration and its chain rule. Delay, phase supports, upper endpoint, grading,
mesh topology and query times are fixed. Higher-order derivatives, GPU
execution, rare-tail relative accuracy, posterior filtering and a full
network training or Cell-admission claim are absent.

Pure SciPy checks compare actual generator derivatives and all DDE output
partials with independent forward differences at two step sizes, including
the old reset knot, low noise and short time. They retain mass/content
derivative conservation and same-point-reset finite-continuum refinement.
These checks do not rerun or replace the original 14,336-position criterion.

The exact-source CI additionally runs Torch joint gradcheck and a declared
two-scalar synthetic fit: recover reset 0.65 and mark 2.0 from reset 0.42 and
mark 0.5, crossing the old node at 0.5, with 120 Adam updates and relative MSE
below 0.0002. The teacher is this same model. This is an optimizer sufficiency
diagnostic, not independent task generalization or a complete C2 replay.

All intermediate outputs and failures are retained. Draft / HOLD_NO_GO.
