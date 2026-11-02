# The new risk channel can distinguish identical finite constructors

This is a deterministic local analysis of the ideal exact mathematical
financial-boundary/finite-constructor formulas, not an additional
outcome-selected numerical gate, an executed byte-equality witness or a
task-utility claim.

Hold r, delta, sigma, alpha, tax, coupon and stationary maturity fixed at an
interior admitted point. Vary liquidity lambda while adjusting principal P
to keep the boundary b fixed. Such a local adjustment exists: the boundary is
linear in P and its P coefficient is

\[
 b_P=\frac{(1-e^{-Rm})/(m\eta)
       +e^{-Rm}[B(-a)+B(a)]/m}
 {.5\sigma^2(\gamma+1)+\alpha[B(-\tilde z)+B(\tilde z)]/m}>0.
\]

Here R=r+lambda, m>0 and B(y)>0 follows directly from its positive
Laplace/Mills integral representation. The denominator is positive. Hence
the implicit-function theorem supplies a local principal curve P(lambda)
through the point with constant b; it stays inside the explicit principal
box for sufficiently small changes.

Along this curve, the corresponding ideal nine-coordinate finite
constructor's three summaries b, drift and diffusion are unchanged, so its
mathematically assembled Q, emissions and prior are unchanged. The
new G channel at any fixed positive log-distance instead satisfies

\[
G(x,m)=\int_0^m e^{-(r+\lambda)t}h_x(t)\,dt,\qquad
\frac{dG}{d\lambda}=-\int_0^m t\,e^{-(r+\lambda)t}h_x(t)\,dt<0.
\]

The first-passage density h_x is independent of principal and liquidity for
these fixed drift/diffusion/maturity coordinates. Thus adjusting principal
does not cancel this change. At least one new native financial channel is
not a function of those finite Q/prior summaries alone. The earlier
R20 three-coordinate API fixed principal and does not itself admit this
principal-adjustment curve. An admitted
interior baseline away from reset knots gives the corresponding local
finite-constructor witness without invoking a knot derivative.

This proves representation nonredundancy, not nine-parameter
identifiability, analytic-core exclusivity, a quality gain or a CPU gain.
An ordinary model supplied the same financial information can compute the
same G. Whether a learned/controller system benefits from these quantities
still requires the matched-information, matched-cost comparison and actual
runtime integration that this numerical port does not perform.

The native implementations use different approximations for boundary b:
the preceding finite constructor uses a truncated positive-tail/GL path,
whereas the new value channels use libm erfc/GL. An exact mathematical
constant-b curve must not be relabeled as a run showing constant FP64
boundaries, identical Q bytes or a live runtime intervention in those two
implementations. No such numerical witness was run here. Fixed asset and
fixed log-distance agree along the ideal curve only when defined using the
same exact b.
