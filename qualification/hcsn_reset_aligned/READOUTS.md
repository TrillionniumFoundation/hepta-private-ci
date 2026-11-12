# Differentiable U and F from the same discrete generator

`perpetual_readout` is the regenerative perpetual value **U**, not the
single-cycle C. Its implicit derivatives include the reset closure and use
the same physical generator as `aligned_flow`. At observation time it uses
the active nodal law, permanently-active upper mass and discounted remaining
phase channel Z_q multiplied by U_reset. Replacing Z_q by total refractory
mass would violate the dynamic identity and its derivatives.

`first_hit_readout` is the finite killed first-excursion **F(T)**, not the
renewal count M returned by `aligned_flow`. It differentiates exp(T Q) using
the matrix-exponential Frechet derivative and the same analytic generator
Jacobian. F has exactly zero discount derivative. This initial version takes
only active nodal probability/content; it explicitly rejects phase rows.
It therefore is not a complete next-hit readout for an arbitrary saved Cell
state containing refractory mass. Fixed-support phase release integration
is a separate necessary extension.

Both readouts retain first-order CPU FP64 and fixed moving-nodal-prior
semantics. External fixed physical densities require migration derivatives.
Pure NumPy/SciPy tests check implicit/Frechet derivatives against independent
forward closure/differences and check the differentiated dynamic identity.
Native Torch checks exercise combined U/F gradcheck and phase-aware U
backward. These establish discrete differentiation only.

The first-hit controls deliberately retain current continuum/domain failures:
for reset .5, drift -.12, sigma .5, endpoint 2, equal left/right subdivision,
grading 1, the 8-interval F(.1) is about 185.9% above the half-line reference,
and 64 intervals remain about 3.27% above. Upper-exit probability by .1 is
below 1.16e-21, so upper truncation cannot explain that discrepancy. Rare
F(.01) relative error is much larger. With drift -.12 and sigma .08, this
geometry rejects nonpositive central rates through 64 intervals. The healthy
120-Adam fit against the same discrete model does not close these failures.

Draft / HOLD_NO_GO. No phase-aware F, learned supports/delay, full physical
prior Jacobian, original 14,336-position requalification of the moving mesh,
real-task benefit, strong-baseline win, device energy or Cell adoption claim.
