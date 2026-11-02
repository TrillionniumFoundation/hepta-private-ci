# Native financial channels and the admitted state convention

This component supplies actual native boundary, equity, first-passage
probability F, discounted first-passage quantity G and one newly issued
debt-unit value d(V,m). This is not aggregate stationary debt
D(V)=integral_0^m d(V,tau)dtau. Its ten Jacobian
columns are the nine physical coordinates in PROTOCOL.json followed by an
independent **log-distance** coordinate. This order differs from R11; the
reference snapshot is unchanged and both input and Jacobian orders are
explicitly remapped.

The state is restricted to `[.005,.6]`, strictly above R11's entire Taylor/C2
blend interval (whose upper endpoint is at most `.002`). The port evaluates
the raw continuation expression using smooth divided-difference identities.
It does not implement the asset/default extension, x=0 risk/debt kink,
Taylor/blend approximations or derivatives of parameter-dependent min ties.
No reset interpolation is used, so no reset-knot derivative is asserted.

For A, the exact numerator N obeys N(z)=0. Thus
`N(u)/(z-u) = -integral_0^1 N'(z-t*(z-u)) dt`. Applying this identity to both
signed arguments eliminates the removable denominator for every candidate
point. B uses its analogous derivative integral. The finite quadrature and
floating-point error still require numerical checking; no uniform proof is
inferred from finite validation.

The scalar Gaussian CDF value comes from the identified Linux libm `erfc`.
Its first tangent is the analytic Gaussian density, matching ordinary
mathematical automatic differentiation of the Gaussian primitive. This is
not a derivative of floating-point rounding. The one isolated FFI call has a
scalar double ABI, accepts finite bounded arguments and transfers no pointers
or ownership. Linux/libm identity is recorded; multiplatform, FP32 and
hermetic dependency qualification remain separate.

The primary independent numeric reference uses high-precision Gaussian
probabilities and the original B/A quotients, plus mpmath differentiation. A
second representation solves the full equity ODE as a Volterra integral with
zero value and slope at the boundary, uses a Laplace/Mills boundary integral,
and takes complex-step derivatives. It does not import candidate, primary
reference or R11 code. Its derivation was supplied and checked at old points
by a separate mathematical agent; the new audit script was composed by the
candidate implementer and receives separate static review. This is separate
numerical-path evidence, not a blind external human review.

No finite generator, actual runtime owner, observation policy, trained
content model or task reward is changed. Exposing five native financial
channels does not establish that a neural model consumes them, that its
complete gradient is correct, or that they add quality beyond an equally
informed ordinary model. Production adoption and exclusive-core gain remain
open even if every declared numerical gate passes.

The maturity column moves the stationary financial structure, coupon/principal
unitization and the evaluation horizon together (`tau=m`). No independent
remaining-tenor coordinate is qualified. Physical partials hold log-distance
fixed. At a strict continuation asset V=b*exp(x), the explanatory chain rules
are `f_theta|V=f_theta|x-f_x*b_theta/b` and `f_V=f_x/V`; this component does not
admit an asset-input API or claim its default-boundary derivative.

Observed shared-disk ENOSPC motivated a pre-roster8MiB allocated RAW extent.
Final compressed data overwrite those allocated blocks and truncate; output
capacity is fixed before confirmation. This is a bounded delivery precaution,
not general arbitrary-I/O, process-kill or power-loss recovery qualification.
