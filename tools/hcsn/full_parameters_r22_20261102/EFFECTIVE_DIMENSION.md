# Nine physical coordinates do not imply nine identifiable dynamics

This is a direct property of the declared source, not a gate fitted to the
confirmation results. Define three summaries

\[
z(\theta)=(b(\theta),\;r-\delta-\sigma^2/2,\;\sigma^2/2).
\]

The constructor's entire 2,001-word value vector factors through these three
numbers. Centered rates use only drift and diffusion; prior/reset completion
weights use only `log(90/b)`; READ/REFRESH emissions and recovery constants are
fixed. Within each admitted reset interpolation regime, the chain rule gives

\[
D_\theta F=(D_zF)(D_\theta z),\qquad
\operatorname{rank}(D_\theta F)\leq3.
\]

All nine input coordinates may have nonzero derivatives while the output
Jacobian has rank at most three. Its physical parameter nullspace therefore
has dimension at least six locally. This is not a numerical derivative bug,
and a gate checking nonzero derivatives is not a parameter-identifiability
test. Coupon/principal scaling additionally satisfies the ordinary Euler
identity `coupon*b_coupon + principal*b_principal = b` in real arithmetic.

Correct native derivatives close an implementation limitation of the earlier
six-fixed-coordinate constructor. They do not create a distinct nine-mode
neural mechanism, identify the original financial parameters from finite
task histories, or establish utility superiority over an ordinary model with
the same three summaries and transition/filter equations. New channel/value,
learning or compression mechanisms require their own explicit matched
comparison. Full financial equity/debt channels are outside this component.
