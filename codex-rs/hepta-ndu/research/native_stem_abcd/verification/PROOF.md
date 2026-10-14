# Mathematical scope: a valid but deliberately conservative error bound

This note proves the real-arithmetic statement implemented in `certify.py` and
states exactly why it is **not** yet a computer-assisted roundoff certificate.
It is additive to the existing NDU/SDE documents and does not claim a general
viscosity-convergence theorem.

## 1. Fixed system and the function being integrated

Let \(s=(h_0,x)\) range over the compact rectangle
\([-0.25,0.25]^2\times[-0.8,0.8]^2\). For a **frozen** coefficient vector
\(\theta\), the R10 program produces \(F_\theta(s,m)\) using three nonlinear
feedback stages, full binary branch enumeration, preference regimes, quartic
terminal cost and recursive entropic aggregation. Define
\(f_\theta(s)=(F_\theta(s,0)+F_\theta(s,1))/2\).
The target is \(J_\mu(\theta)=\int f_\theta(s)\,d\mu(s)\) with uniform product
\(\mu\). Both the observations and the objective remain unchanged in R11.

## 2. A global derivative majorant from the actual network

Write the feedback preactivation at stage \(k\) as
\(a_k=K_{k,m}[h_k,x]+V\tanh(W[h_k,x]+b)+c\),
\(u_k=U\tanh(a_k/U)\), with \(U=2.5\) and
\(h_{k+1}=Ah_k+Bu_k\pm n_m\). For each original coordinate \(j\), let
\(D_jh\) and \(D_j^2h\) denote first/second derivatives. Use entrywise
nonnegative majorants for absolute values. Since
\(|\tanh'|\le1\) and \(|\tanh''|\le1\), setting
\(L_{k}=\max_m|K_{k,m}|+|V||W|\) gives

\[
|D_ja_k|\le L_k|D_j[h_k,x]|,
\]

\[
|D_j^2a_k|\le L_k|D_j^2[h_k,x]|+
|V|\bigl(|W|\,|D_j[h_k,x]|\bigr)^{\odot2}.
\]

Thus \(|D_ju_k|\le|D_ja_k|\),
\(|D_j^2u_k|\le|D_j^2a_k|+U^{-1}|D_ja_k|^{\odot2}\),
with forward recurrences through \(|A|,|B|\). Stage quadratic and terminal
quartic bounds use the standard chain rule, including derivatives of the
nonlinear target \(x\mapsto T x+0.18(x_1x_2,\sin(x_1+x_2))\).

For the entropic continuation
\(C_\eta(v)=\eta^{-1}\log\sum_i p_i\exp(\eta v_i)\) with fixed positive
branch probabilities and \(\eta\ge0\), its derivatives satisfy

\[
|D_jC_\eta|\le\max_i|D_jv_i|,
\quad
|D_j^2C_\eta|\le\max_i|D_j^2v_i|
+\eta(\max_i|D_jv_i|)^2.
\]

The second inequality follows from differentiating softmax weights and bounding
the resulting variance by the maximum squared derivative. Backward propagation
through three stages therefore yields finite, **global**, nonnegative
\(L_j\ge\sup_s|\partial_j f_\theta(s)|\) and second derivative majorants
\(M_j\ge\sup_s|\partial_{jj}f_\theta(s)|\). Branch modes are maximized; no
training/test derivative samples enter these bounds.

The program converts every IEEE754 coefficient into its exact Decimal value
and performs all nonnegative majorant operations with upward rounding; its
reported binary64 radii are increased with `nextafter` until they are above the
high-precision expressions. These operations do not by themselves validate the
floating-point evaluation of \(f\) at quadrature nodes.

## 3. Tensor W1 enclosure

Let a positive 1D quadrature with nodes \(z_i\) and masses \(w_i\) define a
probability measure \(\nu_j\) on the support of coordinate \(j\). The masses
and node locations are treated as **exact rationals equal to the stored floats**
for the distance calculation, and masses are normalized as rationals. In 1D,
monotone quantile coupling is optimal for Wasserstein-1. For uniform
\([-a_j,a_j]\) with quantile \(x_j(t)=-a_j+2a_jt\), if the \(i\)-th atom owns
\([c_{i-1},c_i]\), the exact cost is

\[
W_{1,j}=\sum_i\int_{c_{i-1}}^{c_i}|-a_j+2a_jt-z_i|\,dt.
\]

Every integral is piecewise quadratic and is evaluated with `Fraction`, never
by sampling a finite 1D grid. Tensorize the 1D optimal couplings independently;
changing coordinates one at a time and applying the mean-value theorem gives

\[
\boxed{|J_\mu(\theta)-Q_\nu f_\theta|
\le\sum_{j=1}^4L_j W_{1,j}.}
\]

This is a valid **real-arithmetic** enclosure for the ideal normalized tensor
quadrature. It is conservative because it allows an arbitrary \(L_j\)-Lipschitz
function; high-order quadrature cancellations of this specific smooth neural
integrand are not used. A companion composite midpoint rule has the sharper
rate but uses global second derivatives:

\[
|J_\mu-Q_{\mathrm{mid},n}|\le\sum_j\frac{a_j^2 M_j}{6n^2}.
\]

Neither formula proves that a particular binary64 PyTorch root evaluation has
an outward-rounded error bound. Hence `machine_certified` is intentionally false
for every model; the code NEVER promotes the real-arithmetic formula alone into
an executable machine-formal certificate.

## 4. Manufactured controls and the coarse-rule failure

Constant, affine and centered quadratic controls have known expectations over
the same product-uniform support. As a fourth independent control, put
\(z=x_3/0.8\) and
\(g(s)=0.0484+0.001(z^8-1/9)\). Since \(E[z^8]=1/9\),
\(E_\mu g=0.0484\). Five-point Gauss–Legendre integrates degree-8 polynomials
exactly in real arithmetic, whereas the original CC5/CC9 agreement gate rejects
this particular manufactured function. This is an explicit control against
confusing an accurate underlying population mean with a prescribed coarse-rule
agreement. It is **not** evidence that a trained nonlinear Stem realizes \(g\).

## 5. Interpretation and next proof obligation

When \(L_j\) are enormous due to unconstrained global worst-case paths, the
rigorous bound can be very wide even when GL11 and CC17 numerically agree to
machine precision. A wide enclosure is **INCONCLUSIVE**: neither confirmation
nor refutation of high true-population performance. Agreement between independent
quadratures, QMC scrambles or repeated code paths cannot be silently promoted to
an error guarantee. A practical future certificate will require verified local
Taylor/interval enclosures (perhaps adaptive state-box subdivision), and
validated evaluation-roundoff/error propagation, while preserving the original
unmodified legacy outcomes for historical comparison.
