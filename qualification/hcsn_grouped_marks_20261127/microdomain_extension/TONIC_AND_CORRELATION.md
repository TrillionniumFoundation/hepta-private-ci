# A zero-drift threshold for sustained firing and its dependence on noise correlation

A single zero-drift Brownian process on the half-line hits the wall almost surely and has infinite mean hitting time. Independent parallel paths change the tail of the first event. The following results apply to the joint-reset mechanism, in which the first hit among the paths releases the neuron, all paths wait a fixed time $h$, and all restart at distance $r>0$. Model time has no calibrated conversion to biological seconds here.

## Multiple independent paths

At zero drift, the reflection principle gives $S_1(t)=\operatorname{erf}[r/(\sigma\sqrt{2t})]$. Conditional independence gives $S_n=S_1^n$. Expanding the error function at zero gives
$$
S_n(t)\sim \left(\sqrt{\frac2\pi}\frac r\sigma\right)^n t^{-n/2}.
$$
Thus $E[W_n^k]=k\int_0^\infty t^{k-1}S_n(t)\,dt$ is finite exactly when $n>2k$. The elementary renewal theorem gives the long-run rate $1/(h+E[W_n])$ in the finite-mean case and zero otherwise. Two independent paths still have zero long-run rate. Three independent paths have a finite mean waiting time and a positive long-run rate. The variance of the waiting time becomes finite at five paths. For the latter regime, the usual long-time renewal count Fano factor is $\mathrm{Var}(W_n)/(h+E[W_n])^2$.

At positive outward drift, each individual reset-to-wall path hits with probability $p=\exp(-2\mu r/\sigma^2)$. The whole group escapes with probability $(1-p)^n>0$ on each independent cycle. If the initial and reset distances coincide, the number of releases before permanent escape has the geometric failures-before-success law with mean $[1-(1-p)^n]/(1-p)^n$. Starting at a different distance $x$ changes the numerator to the first-release probability at $x$. The long-run event rate is zero for every finite $n$. With inward drift every wait is integrable. As that drift increases to zero, monotone coupling gives the limit of the mean by monotone convergence.

At $n\ge3$, the long-run rate as a function of drift has a genuine one-sided discontinuity at zero. For every finite measurement horizon the event observations can instead change continuously with drift. This distinction matters when interpreting network activity recorded over a short window. Very large expected lifetimes before escape can coexist with zero asymptotic firing rate.

For the source values $r=0.30$, $\sigma=0.23$ and illustrative $h=0.025$, the exact scale-free moment calculation and an independent survival integral give the following results. The outward column uses the original positive log drift 0.03355.

| Independent paths | Zero-drift long-run rate per model time | Expected lifetime releases at positive source drift | Positive-source-drift long-run rate |
|---:|---:|---:|---:|
| 1 | 0 | 2.15955 | 0 |
| 2 | 0 | 8.98278 | 0 |
| 3 | 0.38419 | 30.54111 | 0 |
| 4 | 0.66536 | 98.65580 | 0 |
| 5 | 0.88621 | 313.86780 | 0 |
| 8 | 1.35441 | 9,930.27939 | 0 |
| 16 | 2.04149 | 98,630,309.41 | 0 |

For the independent calculation, $W_n\overset d=(r/\sigma)^2(\max_i|Z_i|)^{-2}$ for independent standard normal $Z_i$. Integrating the density of that maximum and directly integrating the survival probability give finite dimensionless moments agreeing within $4.0\times10^{-15}$ over the displayed cases and orders one and two. A separate 2.8-million-sequence geometric sample checked the eventual release counts. The historical project already documented the three single-path drift regimes. The multi-path threshold follows from established independent order statistics and renewal theory. [Lawley (2020)](https://doi.org/10.1103/PhysRevE.101.012413) · [Krapivsky, Majumdar and Rosso, independent Brownian walkers in the half-space](https://doi.org/10.1088/1751-8113/43/31/315001) · [Gallager, renewal processes](https://ocw.mit.edu/courses/6-262-discrete-stochastic-processes-spring-2011/931ffa0940899c27f34b71ad64fd2bb0_MIT6_262S11_chap04.pdf)

## Two correlated paths

Let $dX_i=\sigma_i\,dB_i$ with positive starting distances $x_i$ and $d[B_1,B_2]_t=\rho\,dt$ for $-1<\rho<1$. Let $\tau$ be the first time either path reaches zero. After whitening by a Cholesky factor, the two coordinate axes become rays with included angle $\alpha=\arccos(-\rho)$. The survival tail in the isotropic wedge has exponent $\kappa=\pi/(2\alpha)$. Indeed the lowest positive angular Dirichlet mode is $\sin(\pi\theta/\alpha)$ and its harmonic radial power is $r^{\pi/\alpha}$. Brownian scaling yields the survival tail $Ct^{-\pi/(2\alpha)}$ for interior starts. Consequently the mean is finite when $\rho<0$, logarithmically divergent at $\rho=0$, and power-law divergent for $\rho>0$. Two negatively correlated paths can support a positive long-run firing rate at zero drift. A second moment additionally requires $\rho<-1/\sqrt{2}$. [Ben-Naim and Krapivsky, first passage in conical geometry](https://cnls.lanl.gov/People/ebn/pubs/conerev/conerev.pdf) · [Redner, wedge domains](https://www.cambridge.org/core/books/abs/guide-to-firstpassage-processes/wedge-domains/2FA70CC7D51331813A3A624769C05F28)

An independent stopped-martingale argument gives an exact mean across the finite-mean regime:
$$
E[\tau]=\frac{x_1x_2}{-\rho\sigma_1\sigma_2}\qquad(-1<\rho<0).
$$
Itô's product rule makes $X_1X_2-\rho\sigma_1\sigma_2t$ a martingale after localization. Stopping at $\tau\wedge t$ is integrable for fixed $t$. Nonnegativity of the stopped product yields $E[\tau\wedge t]\le x_1x_2/(-\rho\sigma_1\sigma_2)$ when $\rho<0$, hence an integrable exit time. The two stopped Brownian coordinates then converge in $L^2$ by the stopped Brownian isometry, so their products converge in $L^1$. One coordinate is zero at exit, giving the stated equality. For $\rho\ge0$, assuming finite mean would give the same equality $0=x_1x_2+\rho\sigma_1\sigma_2 E[\tau]$, a contradiction. After a fixed refractory time and full reset the exact steady firing rate is the inverse mean cycle time.

A separate finite-domain computation solves $\tfrac12\Delta u=-1$ with zero values on both race boundaries and a further absorbing circle of radius $R$. The angular sine expansion uses 5,001 odd modes and approaches the infinite-wedge mean monotonically as $R$ grows. With $x=(0.18,0.30)$, $\sigma=(0.23,0.31)$ and outer radius $10^{12}$ times the starting radius, the values are 0.94670406732149 at $\rho=-0.8$ and 1.5147265077123 at $\rho=-0.5$. Their discrepancies from the product formula are below $2\times10^{-12}$. At zero and positive correlations the finite-domain means continue to grow with the outer radius. The model assumes constant covariance, fixed walls and simultaneous resets. The two-path wedge formula does not specify a many-path correlated firing law.

Reproduce the [independent moment and rate calculations](tonic_microdomains.json) with verify_tonic_microdomains.py. [Correlated finite-sector results](correlated_two_tonic.json) come from correlated_two_tonic.py.
