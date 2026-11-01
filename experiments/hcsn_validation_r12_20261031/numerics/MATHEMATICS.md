# Complete successor for the inherited regenerative diffusion

The following derivation is for the process executed by the inherited renewal
module, not for the stationary financial equity-stopping problem. Write

\[
X_t=x+\mu t+\sigma W_t,\quad \tau_0=\inf\{t:X_t\le0\}.
\]

Its first-hit density is

\[
f_x(t)=\frac{x}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right].
\]

For positive drift this integrates to a probability below one. The remaining
mass is non-hitting mass at infinity; it is not renormalized away.

The killed transition density on positive distance is

\[
k_t(x,y)=\frac{e^{-(y-x-\mu t)^2/(2\sigma^2t)}}{\sigma\sqrt{2\pi t}}
\left(1-e^{-2xy/(\sigma^2t)}\right).
\]

The inherited implementation evaluates the final difference with `expm1`.
Integrating it gives unconditional survival mass, not a conditional density.
Conditional survival would require dividing by that mass and is not the state
convention in this study.

Let the reset distance be `r>0` and the refractory duration be `d>0`. Identical
independent drift/noise segments imply the convolution of hitting times from
distances `x` and `r` is the hitting time from `x+r`. Consequently the n-th event
time has the distribution of `tau_(x+(n-1)r)+(n-1)d`. This remains valid for the
defective hitting-time distributions when drift is positive.

The complete active density at horizon T is therefore

\[
A_T(y)=k_T(x,y)+\sum_{n\ge1}\int_0^{T-nd}
f_{x+(n-1)r}(s)\,k_{T-nd-s}(r,y)\,ds.
\]

Terms with a nonpositive integration interval are zero. The corresponding
refractory-age density, for `0<=a<d`, is

\[
R_T(a)=\sum_{n\ge1} f_{x+(n-1)r}\big(T-(n-1)d-a\big),
\]

where a density at nonpositive time is zero. Thus

\[
\int_0^\infty A_T(y)\,dy+\int_0^d R_T(a)\,da=1.
\]

The audit checks this identity by adaptive integrals and independently by a
forward PDE with delayed flux reinjection. It also compares the actual active
spatial bins, rather than relying on mass conservation alone.

For `F(x,mu,sigma,T)=P(tau_0<=T)`, the mean event count is

\[
\mathbb E N_T=\sum_{j\ge0}F(x+jr,\mu,\sigma,T-jd).
\]

Inside the declared positive-state/refractory domain the derivatives include

\[
\partial_r\mathbb E N_T=\sum_j jF_x,\qquad
\partial_d\mathbb E N_T=-\sum_j jF_T.
\]

The other four derivatives sum the corresponding derivatives of F. The
zero-time endpoints at positive distance are flat limits. The singular
`x=0,T=0` corner is outside this ordinary-derivative contract.

For `b(t)=s*t+c*t^2`, the boundary-distance drift is
`mu-s-2*c*t`. Only `c=0` preserves the stationary closed-form first-hit model.
The nonlinear example establishes measured convergence over three numerical
grids; it does not produce a rigorous truncation or uniform error certificate.
