# Independent local nonredundancy review

The final `NONREDUNDANCY.md` claim is correct at its stated ideal exact-formula
layer. This is a mathematical review after source freeze, not a new acceptance
gate, numerical witness, parameter draw or performance measurement.

Write (d=e^{-Rm}), (q=P/m-c/R), (c=C/m), (S_a=B(-a)+B(a)), and

\[
D=\tfrac12\sigma^2(\gamma+1)+\alpha S_{\tilde z}/m.
\]

The inspected boundary numerator is
`cost/eta + q*d*S_a + (c/R)*S_zt`, where
`cost=(1-tax)*C+(1-d)*q`. Its denominator is independent of principal.
Thus (q_P=1/m), (mathrm{cost}_P=(1-d)/m), and exactly

\[
b_P=\frac{(1-d)/(m\eta)+d S_a/m}{D}>0.
\]

Indeed (r>0,sigma>0) imply (z>|a|), so both (eta=z-a) and
(gamma=z+a) are positive. The declared domain has (R>0,m>0,alpha>0).
The independently inspected Mills representation is

\[
B(y)=s\phi(ys)\int_0^\infty
 u e^{-u^2/2-zsu}\operatorname{exprel}((z+y)su)\,du.
\]

For real arguments every factor is positive for (u>0), including the
continuous value `exprel(0)=1`; the Gaussian factor gives convergence.
Consequently (B(y)>0), (D>0), and (0<d<1). This verifies the displayed
coefficient without assuming a sign for (b_\lambda).

These smooth formulas and (b_P\ne0) give a local curve
(P(\lambda)) with (b(\lambda,P(\lambda))=b_0) and
(P'=-b_\lambda/b_P). A strictly interior admitted starting point gives a
sufficiently small open interval that remains inside both physical boxes and
the strict admission conditions. This is a local result: it does not promise
a full-box or arbitrarily long principal adjustment. Reset weights stay fixed
because their input (b) stays fixed; starting away from a reset knot retains
the declared differentiable regime.

In the inspected finite assembly, rates depend only on drift
(mu=r-\delta-\sigma^2/2) and diffusion (sigma^2/2), reset weights depend
only on (b), emissions are constants, and prior uses those weights. Hence
the corresponding ideal value arrays (Q), emissions and prior stay fixed
along this curve. This does not assert that their full nine-coordinate
Jacobian arrays stay fixed.

At fixed (x>0,m>0,sigma>0), the first-passage density is

\[
h_x(t)=\frac{x}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right]>0
\quad(0<t<m).
\]

It depends on neither (P) nor (lambda) when the other declared
coordinates are fixed. Differentiation under the finite-horizon integral is
valid: locally bounded discount factors and (t\le m) give an integrable
dominator, with the (x>0) Gaussian factor controlling the endpoint at zero.
Therefore the *total* derivative along the principal-adjustment curve is

\[
\frac{dG}{d\lambda}
=-\int_0^m t e^{-(r+\lambda)t}h_x(t)\,dt<0.
\]

The principal term cannot cancel it because (G_P|_x=0). Strict positivity
inside a nonempty integration interval gives a strict, rather than weak,
inequality. The excluded (x=0), (m=0), or degenerate-volatility cases are
not covered. For the same exact boundary (b), (V=b e^x) shows that fixed
asset and fixed log-distance coincide along this constant-boundary curve.
This explanatory identity does not add an asset-coordinate native API.

The conclusion is that (G) is not a function only of the three ideal old
summaries ((b,\mu,\sigma^2/2)), or their indicated finite value assembly.
It does not establish nine-parameter identifiability, a difference from an
ordinary model given the same information, downstream utility, or a resource
advantage. The older R20 API fixed principal, so that API alone did not admit
the proposed adjustment direction.

The producer's final text correctly distinguishes this real-formula statement
from native arithmetic. The earlier finite implementation uses truncated
Mills-tail/GL evaluation while the new channel uses libm-erfc/GL evaluation;
an ideal constant-(b) curve is not an executed proof of identical FP64
boundaries or (Q) bytes across those implementations. No such numerical
control was run in this review. All 13 frozen value-channel source hashes
were checked unchanged; the completed 195-point experiment and audits were
not modified or rerun.
