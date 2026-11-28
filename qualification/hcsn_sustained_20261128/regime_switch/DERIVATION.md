# One-way liquidity regime with an endogenous pre-switch barrier

He and Xiong’s published model prices debt and equity under constant secondary-market liquidity parameters. Their discussion on p. 412 proposes a Markov liquidity regime as an extension. The formulas below describe a particular extension with a single transition, fixed contracts and constant, risk-neutral switching intensity independent of the asset Brownian motion. The market-wide regime clock is distinct from investors’ trading shocks. The pricing hazard can differ from a physical spiking or default hazard. [He and Xiong, *Journal of Finance*, 2012](https://www.princeton.edu/~wxiong/papers/rollover.pdf)

Let the candidate pre-switch barrier be \(b\), the solved post-switch barrier be \(B_1\), and \(x=\log(V/b)\). The pre-switch log diffusion has drift \(\mu\), volatility \(\sigma>0\) and generator \(L\). Let \(K_s^b\) be its semigroup killed on first contact with \(b\), \(S_s=K_s^b1\), and \(\tau_b\) the corresponding diffusion hitting time. Write \(h\) for the regime hazard, \(q_0=r+\ell_0\) for the pre-switch bond discount, \(c=C/m\), \(p=P/m\) and \(u\) for the bond's remaining life. Extend the post-switch equity by zero and extend the post-switch debt by \(\alpha V/m\) on \(V\le B_1\). An asset level below the new wall can arise at a regime jump, so recovery depends on the actual asset value.

For an interior pre-switch issuer,

\[
 d_0(V,u)=p e^{-(q_0+h)u}S_u(V)+\frac{\alpha b}{m}\,\mathbb E_V[e^{-(q_0+h)\tau_b}\mathbf1_{\tau_b\le u}]+\int_0^u e^{-(q_0+h)s}\left[cS_s(V)+hK_s^b\{\widetilde d_1(\cdot,u-s)\}(V)\right]ds.
\]

The face payoff applies to surviving interior bonds at maturity. At an immediate default, recovery applies under the chosen convention. The maturity-default corner requires an explicit choice for a contract issued exactly on the wall. During a switch an outstanding bond retains its remaining maturity. A new issue in the equity cash account uses the full term \(m\).

Set \(F_b(V)=\delta V-(1-\pi)C+d_0(V,m)-p+h\widetilde E_1(V)\). Before the switch, \((r+h-L)E_0=F_b\), with \(E_0(b)=0\). If \(\eta=(D-\mu)/\sigma^2\), \(D=\sqrt{\mu^2+2\sigma^2(r+h)}\), and the linear-growth transversality terms vanish, integration by parts gives

\[
 E_{0,x}(0^+)=\frac{2}{\sigma^2}\int_0^\infty e^{-\eta x}F_b(be^x)\,dx.
\]

A root enforces smooth fit. The stopping obstacle and growth conditions still require verification. In the stopping region, a continuation deviation uses immediate-liquidation recovery \(\alpha V/m\) and the appropriate \(h\widetilde E_1\). Continuation equity must be nonnegative. If \(B_1>b\), split integrals at \(\log(B_1/b)\). If \(B_1\le b\), there is no switch-triggered default strip in the pre-switch continuation domain. The pre-switch solution receives no second value-matching or smooth-fit condition at \(B_1\). Since that physical post-switch wall remains fixed as the candidate \(b\) varies, the pre-switch root is generally nonlinear in \(b\).

An exact quadrature reduction comes from the reflection density \(k_s(x,y)\) of the pre-switch log diffusion absorbed at zero. With \(\gamma=(D+\mu)/\sigma^2\) and \(w=\sigma\sqrt{s}\), direct Gaussian integration gives

\[
 e^{-(q_0+h)s}\int_0^\infty e^{-\eta x}k_s(x,y)\,dx=e^{-(q_0-r)s}\left[e^{-\eta y}\Phi\!\left(\frac{y-Ds}{w}\right)-e^{\gamma y}\Phi\!\left(\frac{-y-Ds}{w}\right)\right].
\]

This weight is nonnegative. It vanishes at \(y=0\) for \(s>0\) and tends to \(e^{-\eta y}\) for \(s\downarrow0\) at positive \(y\). A log-CDF difference with `expm1` improves accuracy in the cancellation region. Direct numerical integration of the two original Gaussian terms over twelve interior time/distance pairs agreed within \(1.14\times10^{-16}\) at \(\mu=0.03355,\sigma=0.23,r=0.08,h=0.27,q_0=0.094\). The weight removes one of the three direct quadrature levels in the debt contribution to the equity-root equation.

The source grows at most linearly in asset value under the usual contract assumptions. The condition \(\eta>1\) holds for the risk-neutral drift \(r-\delta-\sigma^2/2\) when \(\delta+h>0\). If \(\eta=1\), the limiting boundary integral and transversality need separate handling. With \(h=0\) the known pre-switch contract should be recovered. With equal regimes and contracts, the same stationary debt, equity and boundary solve the equations for every \(h\). Under unequal regimes, fast switching can support pointwise value limits away from the barriers. Boundary convergence needs separate justification.

The corresponding finite-horizon physical first-passage probability follows by conditioning on the first switch. With physical hazard \(h_P\), physical killed semigroup, and post-switch hitting CDF extended by one below its barrier, the CDF equals \(\mathbb E_V[e^{-h_P\tau_b}\mathbf1_{\tau_b\le T}]+\int_0^T h_Pe^{-h_Ps}K_s^b\{\widetilde F_1(\cdot,T-s)\}(V)ds\). Instantaneous absorption at a wall jump and later diffusion absorption appear once each. A realized state change still generates a discrete regime mark. The averaged distribution can offer a differentiable neural message under appropriate regularity and parameterization.
