# Stable equity gradients in the negative normal tail

The prepared-equity study exposed a pre-existing failure at FP32 maturity
0.05 and log-margin 12: equity was finite but its gradients were NaN in both
the original and prepared implementations. Two positive normal-tail integrals
had logarithms near -36,000. Their small difference disappeared when those
logs rounded to the same FP32 value. Taking `log(0)` then contaminated backward
even though the final far-tail contribution underflowed harmlessly in forward.

`_log_normal_tail_pair` evaluates that positive difference before adding its
large common logarithm. Let

\[
J_n(w)=\int_0^\infty t^n\phi(t-w)\,dt,\quad w=vs,
\]

so that `J0=Phi(w)` and `J1=phi(w)+w*Phi(w)`. For the existing integral,

\[
H(\lambda,v,s)
=s\sum_{n=0}^{\infty}\frac{(-\lambda s)^n J_{n+1}(w)}{(n+1)!}.
\]

The difference at `lambda1=u-z` and `lambda2=u+z` factors into
`2*z*s**2*J2*P`, where v is the potentially shifted second argument of H
and P starts at 1/2. Divided powers compute the remaining
terms without subtracting nearby powers. Continued fractions give the positive
moment ratios `r_k=J_k/J_(k-1)`. They also give the exact identity

\[
\log\Phi(w)=-w^2/2-\log\sqrt{2\pi}-\log(r_1-w).
\]

This avoids a second issue: cancellation in the backward expression for
`torch.special.log_ndtr` at large negative arguments. The unused ordinary
and tail branches both receive safe dummy parameters before evaluation, so an
unselected `log(0)` cannot enter the backward graph. These are algebraic changes
to the same kernel, without clipping the result or replacing a small derivative.

## Expansion bound and scope

The sixteen-term expression is used only for `w < -2` and
`max(abs(lambda1),abs(lambda2))*s/(1-w) < .08`. Since
`r_k < k/abs(w)`, each absolute polynomial term is bounded by
`n*R**(n-1)/2`, with `R < .12`. The omitted tail is consequently below
`R**16*(17-16*R)/(2*(1-R)**2) < 1.80e-14` before floating-point rounding.
The same bound puts P above 0.35, avoiding a nearly zero polynomial denominator.
This bound concerns the analytic truncation; finite-precision and continued-
fraction errors are checked separately. The ordinary expression remains in the
other part of the domain.

## Executed validation

Thirty targeted tensor, Cell, prepared-equivalence and new stability tests pass.
The new cases compare both precisions with an independent 80-digit formula
at twelve negative-tail locations for three parameter choices; they also check
parameter finite differences, all nine physical gradients and the margin
gradient at the original failure, and the previously contaminating unused branch.
An independent 80-digit differentiation review checks the branch boundary and
deep tails. Its raw values, gradients, method and source digest are retained.
Within the new branch, its maximum gradient relative error is 9.74e-14 in
FP64 and 1.62e-7 in FP32. The preserved ordinary branch just outside the switch
has a measured FP32 gradient relative error of 1.92e-5 in the reviewed case.

The original failure remains in the prepared-equity evidence. Two initial
repair attempts also remain: their stricter independent reference revealed
ordinary-branch error at the initial switching choices. The acceptance bounds
were retained while the stable expression's justified domain was expanded.
Attempt003 passed 29 checks; the final attempt004 passed 30, including the
independently discovered unused-branch and large-argument backward case.

This repair is separate from the frozen fixed-update and equal-wall-time
training studies. Their source identities and measured results remain those
actually used. It has no new task-performance or universal parameter-domain
accuracy claim.
