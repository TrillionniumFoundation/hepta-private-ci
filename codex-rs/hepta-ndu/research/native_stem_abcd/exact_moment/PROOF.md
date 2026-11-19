# R12 exact rational population certificate (narrow scope)

Forward Stem: \(H_1=X+\theta X^4+\varepsilon/5\), \(X\sim \mathrm{Uniform}[-1,1]\), \(\varepsilon\in\{-1,+1\}\) equiprobably and independent. Target \(X^2\). Terminal loss \((H_1-X^2)^2\), recursion discount 9/10, zero-risk conditional expectation. The discrete BSDE martingale coefficient is the difference between its two successor terminal losses. **Theta is in the forward state evolution, not a readout-only approximation.**

Uniform moments satisfy \(E[X^{2k}]=1/(2k+1)\) and odd moments vanish. Expanding the actual terminal loss and averaging both Bernoulli outcomes:

\[
J(\theta)=\tfrac9{10}(\tfrac{43}{75}-\tfrac{2\theta}{7}+\tfrac{\theta^2}{9}).
\]

Since the Hessian equals 1/5 > 0, its unique global optimum is \(\theta_*=9/7\), and

\[
J(\theta)-J(\theta_*)=\tfrac1{10}(\theta-9/7)^2.
\]

The 5-node normalized Clenshaw–Curtis rule has even moments \(m_2=1/3,m_4=1/5,m_6=2/15,m_8=1/10\), unlike true \(m_6=1/7,m_8=1/9\). Thus its own optimized forward Stem is \(\theta_{CC5}=m_6/m_8=4/3\), and its **exact true population excess** is \(J(4/3)-J(9/7)=1/4410\). No Monte Carlo, heuristic confidence bound, learned critic or fitted reference is used.

The five-node Gauss–Legendre rule integrates every polynomial of degree up to nine exactly; our expanded population objective has degree eight in X, so *in exact arithmetic* this rule evaluates its expected cost and minimizer exactly. This is an application of the classical quadrature exactness theorem and is not a claim of machine-float interval-enclosed numerical accuracy.

This is a **genuine global certificate for one bounded-degree, one-step, one-parameter, zero-risk NDU/FBSDE special case**. It is not a uniform nonlinear neural Stem/FBSDE, nonzero-risk recursive utility, higher-dimensional state, viscosity-solution or LLM generalization certificate. Old R10 status (35/96 passed) is unchanged; the R11 cross-rule 68/96 remains numerical corroboration, not a strict bound.
