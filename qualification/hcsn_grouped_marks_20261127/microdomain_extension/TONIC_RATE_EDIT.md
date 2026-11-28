# Directly writing a requested local steady firing rate

For a fixed absolute post-event reset level $V_r$ and a controlled common wall $B$, the new cycle starts at the positive log distance $d=\log(V_r/B)$. After each hit there is an absolute refractory duration $h>0$. The physical diffusion drift is zero. All paths share one scalar volatility $\sigma$ and reset together. These assumptions are essential. If the model holds the **relative** reset distance fixed independently of $B$, sliding the wall leaves the renewal cycle law and steady firing rate unchanged.

For $n\ge3$ independent paths, the dimensionless constant $C_n=E[(\max_{1\le i\le n}|Z_i|)^{-2}]$ depends only on the integer channel count. A single high-accuracy quadrature fixes it for all later writes at that count. For two paths with correlation $-1<\rho<0$ and equal reset distance and volatility, the exact constant is $C=-1/\rho$. In both cases
$$
f(B)=\frac{1}{h+(C/\sigma^2)\max[\log(V_r/B),0]^2}.
$$
When the boundary reaches the reset level, each exit follows immediately after its refractory interval and the steady rate saturates at $1/h$. The shared-distance expression has a matching zero first derivative at the transition. A prescribed positive live rate $f^*<1/h$ gives
$$
d^*=\sigma\sqrt{\frac{1/f^*-h}{C}},\qquad
B^*=V_r e^{-d^*}.
$$
For $B=\beta_0+\beta_1P$ and $P=P_0[1+\eta\tanh z]$, $\beta_1>0$, $P_0>0$, $0<\eta<1$, solve $P^*=(B^*-\beta_0)/\beta_1$ and $z^*=\operatorname{atanh}[(P^*/P_0-1)/\eta]$. A finite open drive requires the target boundary to lie strictly between the two tanh limiting boundaries. Finite distances give positive rates for these finite-mean models. A target above $1/h$ is outside their support. For a reachable target equal to $1/h$, keep an already saturated input or apply the smallest drive reached from a live input that reaches $B=V_r$. For independent one- and two-path zero-drift models, the live mean cycle duration diverges. The positive live rate inverse above therefore has a different domain from the one-step hitting-probability inverse elsewhere in this package.

With frozen input keys $K$, the desired preactivations yield the linear constraints $K\,\Delta w=z^*-Kw$. The positive-definite covariance-minimum solver in microdomain.py then finds a feasible write, including explicit protected rows whose desired change is zero. This calculation targets a supplied internal firing rate with an identifiable, known local state. A training objective expressed in semantic labels, tokens, images or rewards still needs a mechanism to identify the required rates and keys.

The implementation checked 31 target rates for each of three independent-path families and two negatively correlated two-path families. The largest scalar rate error over 155 inversions was $1.78\times10^{-14}$. Jointly changing three keys while protecting a fourth produced maximum rate error $9.77\times10^{-15}$. A fifth unconstrained key changed by +0.210 to +1.577 model-rate units across the five families. Each bounded drive rejected four infeasible requested rates. Additional tests verified preserving an already saturated drive and reaching the plateau from below. These are measured numerical accuracies on designated keys, with the target values given. [Raw verification](tonic_rate_edit.json) · [Rate port](tonic_rate_edit.py) · [Verification source](verify_tonic_rate_edit.py)
