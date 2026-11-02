# Fixed-grid jump tangents

This extension differentiates the finite numerical map of the R18 reflected
diffusion STOP/WAIT/delayed RESET task. It covers thirteen smooth task
coefficients, with domain, horizon, recovery duration and both meshes fixed.
It is not a derivative of the full He–Xiong financial model or a proof of
continuous free-boundary differentiability.

Write `A(theta) v = v_prev - c_wait dt` on WAIT rows. The tangent satisfies
`A dv = dv_prev - dc_wait dt - dA v`. With reflected finite differences,
`-dA v = dt sigma/dx^2 * curvature(v) d_sigma`. On STOP rows, `dv=dg`.
On RESET contact rows, `dv=dB`; those rows replace the corresponding linear
system rows, including off-diagonal coefficients, before the tangent solve.

For a reset successor `F_l=I_xreset V_l(t-rho)`,
`dB_j = sum_l M_jl dF_l + sum_l dM_jl F_l - dk_j - rho dc_rec`.
The interpolant derivative contains both `I_xreset dV` and the slope of its
active spatial cell times `dxreset`. Both rows of `M` are parameterized by
their own diagonal retention probability; the off-diagonal probability moves
by its negative. Both reward bases, amplitudes and common sigmoid slope carry
their analytic payoff derivatives, including the terminal condition at t=0.

At each admission date `t=k rho`, the left solve uses the previously saved
left successor `V((k-1)rho-)` and its tangent. The new right reset uses the
right successor `V((k-1)rho)` and its tangent. Only after the left obstacle
solve is complete do we apply `V=max(V_left,B_right)` and select that same
branch's tangent. The first admission left solve has no reset option.
Using the final right value in the preceding WAIT curvature or using a right
successor in the left reset would leak a newly feasible action backward.

The derivative is conditional on locally stable discrete active branches.
The audit exposes all left and right branch changes under both signs of two
finite-difference step sizes, retains every whole-array discrepancy, and
distinguishes stable from switched coordinates. Equal max branches and exact
contact topology changes can have nonunique derivatives. Reset interpolation
knots are rejected. Recovery, horizon, spatial bounds and mesh changes are not
supported coordinates: rounding a duration to a lag is not its continuous
time derivative. No action-selection or continuous hitting-time derivative is
claimed. Fixed-mesh verification does not establish a continuum gradient limit.
