# Spatial refinement of first-passage values and gradients

This is an additional audit, not a modification or reinterpretation of the
frozen `event_audit_verified.json`. The original Brownian kernel and finite
generator files retain their recorded hashes. The new source is
`resolution_audit.py`, and its raw output is
`evidence/spatial_resolution_audit.json`.

The audit supplies a positive convergence example alongside the retained
low-noise counterexample. It does not turn a five-state or other coarse CTMC
into an exact continuum solver. Every grid remains a distinct finite model.

## Fixed experiment and error budgets

The continuum process is

\[
dX_t=0.4\,dt+0.6\,dW_t,\quad X_0=0,\quad b=1,\quad T=1.2,
\]

and the discount rate is \(\rho=0.7\). We compare

\[
F=\Pr(\tau_b\le T),\qquad
G=\mathbb E[e^{-\rho\tau_b}\mathbf1_{\tau_b\le T}],
\]

and their derivatives with respect to drift and boundary distance. The
one-upper-boundary closed forms provide the reference. Their values are:

| Quantity | Reference |
|---|---:|
| \(F\) | 0.3267209477116415 |
| \(G\) | 0.19195326844862723 |
| \(\partial_\mu F\) | 0.6238562067290127 |
| \(\partial_b F\) | -0.6381858892478225 |
| \(\partial_\mu G\) | 0.37581046119883627 |
| \(\partial_b G\) | -0.43123275409294193 |

The finite chain has absorbing endpoints \((-4b,b)\), uniform spacing
\(h=5b/M\), and \(M=40,80,160,320,640\) intervals. Zero is an exact node at
every resolution. A boundary derivative changes \(b\) while retaining
\(-4b\) as the lower endpoint; the image bounds below explicitly control the
effect of this moving lower endpoint. No interpolation or grid-index switch
is hidden in the reported derivative.

The protocol, grid sequence and gates were written into the new source before
its first execution. This is a local predeclared numerical audit, not an
independently timestamped external preregistration. No tolerance was changed
after inspecting results. All six errors must strictly decrease at every
refinement. The last observed order must be at least 0.85 for upwind and 1.8
for fitted rates. Finest-grid absolute errors must be below 0.005 and
0.00005, respectively. The derivative finite-difference check uses a fixed
step of 0.00002 and tolerance 0.000002. Lower-truncation bounds must be below
\(10^{-30}\).

## Finite-matrix values and differentiation

Let \(K\) be the transient generator and \(r\) its upper-absorption flux.
Discount acts only before absorption. For a fixed discount \(\rho\), define

\[
A_\rho=\begin{pmatrix}K-\rho I&r\\0&0\end{pmatrix}.
\]

The last component of \(p_0e^{T A_\rho}\) is the required finite-chain value.
Thus \(\rho=0\) gives \(F_h\) and \(\rho=0.7\) gives \(G_h\). This integrates
positive absorption flux; neither quantity is obtained by subtracting
survival from one.

The source differentiates the upwind or Bernoulli fitted rates analytically.
For \(\theta\in\{\mu,b\}\), the column-form sensitivity solves

\[
\dot y=A_\rho^\top y,\qquad
\dot s_\theta=A_\rho^\top s_\theta+
(\partial_\theta A_\rho)^\top y,
\quad s_\theta(0)=0.
\]

One sparse block-matrix exponential evaluates the value and both
sensitivities. This is a derivative of the finite law itself; it does not
claim that differentiation commutes with a continuum limit without further
conditions. Fixed-grid central differences independently check the matrix
derivatives at \(M=80\). Their largest absolute disagreement is
\(2.5288104943399503\times10^{-10}\).

For the closed discounted reference, put
\(\kappa=\sqrt{\mu^2+2\rho\sigma^2}\) and
\(a=\exp((\mu-\kappa)b/\sigma^2)\). Then

\[
G(b,\mu)=aF(b,\kappa),
\]

\[
\partial_\mu G=a\left[
\frac b{\sigma^2}\left(1-\frac\mu\kappa\right)F(b,\kappa)
+\frac\mu\kappa\partial_\mu F(b,\kappa)\right],
\]

\[
\partial_b G=a\left[
\frac{\mu-\kappa}{\sigma^2}F(b,\kappa)+\partial_bF(b,\kappa)\right].
\]

## Lower-truncation bounds for values and derivatives

The reflection construction for the absorbing interval \((-4b,b)\) gives
upper first-passage density

\[
f_I(t)=\frac{e^{\mu b/\sigma^2-\mu^2t/(2\sigma^2)}}
{\sigma\sqrt{2\pi t^3}}
\sum_{k\in\mathbb Z}(1+10k)b
\exp\!\left(-\frac{(1+10k)^2b^2}{2\sigma^2t}\right).
\]

The \(k=0\) term is the one-upper-boundary density. All remaining images
have absolute distances \((10j-1)b\) and \((10j+1)b\), \(j\ge1\). For an
image with distance \(d\), put \(z=d/(\sigma\sqrt T)\). Dropping the
nonpositive time exponent, including \(-\rho t\), bounds its integrated
magnitude by

\[
e^{\mu b/\sigma^2}2\Phi(-z)
\le e^{\mu b/\sigma^2}\frac{2\phi(z)}z.
\]

The derivative of its density with respect to drift multiplies it by
\((b-\mu t)/\sigma^2\). Its absolute integral is therefore bounded by
\((b+|\mu|T)/\sigma^2\) times the value bound.

Because each image distance is proportional to \(b\), its boundary
derivative multiplies the density by
\(1/b+\mu/\sigma^2-d^2/(b\sigma^2t)\). Substitution
\(u=d/(\sigma\sqrt t)\) gives
\(2\int_z^\infty u^2\phi(u)\,du=2[z\phi(z)+\Phi(-z)]\).
The image's absolute boundary-derivative integral is thus bounded by

\[
e^{\mu b/\sigma^2}\left[
\left(\frac2b+\frac{|\mu|}{\sigma^2}\right)
\frac{2\phi(z)}z+\frac{2z\phi(z)}b\right].
\]

Successive images are separated by
\(\Delta=10b/(\sigma\sqrt T)\). Their positive envelopes have ratios at
most

\[
r_0=e^{-z\Delta-\Delta^2/2},\qquad
r_2=(1+\Delta/z)e^{-z\Delta-\Delta^2/2}.
\]

For the registered \(z\ge1\), both ratios are below one and decrease with
\(z\). Summing two geometric envelopes, one starting at \(9b\) and one
at \(11b\), bounds the entire omitted image series and justifies the
corresponding termwise differentiation. The resulting absolute bounds are:

| Quantity | Lower-truncation bound |
|---|---:|
| \(F\) and \(G\) | \(3.4109956955749467\times10^{-42}\) |
| Drift derivatives of \(F,G\) | \(1.4022982304030338\times10^{-41}\) |
| Boundary derivatives of \(F,G\) | \(6.501736795287582\times10^{-40}\) |

These are mathematical inequalities evaluated in binary64. This report does
not add an interval-arithmetic certificate for floating-point evaluation or
for SciPy's sparse exponential. The lower truncation is nevertheless far
below every measured spatial error and the fixed audit budget.

## Observed convergence

The table contains absolute errors against the upper-only closed form.
Unrounded values and every finite-chain output are in the raw JSON.

| Scheme | Intervals | \(F\) | \(G\) | \(F_\mu\) | \(F_b\) | \(G_\mu\) | \(G_b\) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Upwind | 40 | 2.49003e-2 | 1.93940e-2 | 2.74845e-2 | 4.03423e-2 | 3.30298e-2 | 1.61396e-2 |
| Upwind | 80 | 1.29599e-2 | 9.73452e-3 | 1.69851e-2 | 2.01491e-2 | 1.83621e-2 | 7.57322e-3 |
| Upwind | 160 | 6.61258e-3 | 4.87354e-3 | 9.41870e-3 | 1.00271e-2 | 9.68228e-3 | 3.63101e-3 |
| Upwind | 320 | 3.33988e-3 | 2.43782e-3 | 4.95665e-3 | 4.99412e-3 | 4.97146e-3 | 1.77168e-3 |
| Upwind | 640 | 1.67837e-3 | 1.21909e-3 | 2.54219e-3 | 2.49108e-3 | 2.51893e-3 | 8.74187e-4 |
| Fitted | 40 | 1.07789e-3 | 1.92393e-3 | 1.95745e-3 | 8.16089e-3 | 1.45949e-3 | 5.38366e-3 |
| Fitted | 80 | 2.63410e-4 | 4.80953e-4 | 5.08091e-4 | 2.02381e-3 | 3.62916e-4 | 1.34943e-3 |
| Fitted | 160 | 6.54710e-5 | 1.20236e-4 | 1.28197e-4 | 5.04856e-4 | 9.06063e-5 | 3.37551e-4 |
| Fitted | 320 | 1.63439e-5 | 3.00587e-5 | 3.21226e-5 | 1.26144e-4 | 2.26439e-5 | 8.43996e-5 |
| Fitted | 640 | 4.08448e-6 | 7.51467e-6 | 8.03525e-6 | 3.15317e-5 | 5.66050e-6 | 2.11006e-5 |

All six quantities decrease at every refinement in both schemes. The last
observed orders range from 0.96329 to 1.01910 for upwind and from 1.99918 to
2.00053 for fitted rates. All nine new audit gates pass. The complete audit,
including repeated low-noise rejections, used about 4.11 process CPU seconds
on the recorded environment.

The original low-noise case remains rejected on all grids 15 through 255,
for both upwind and fitted rates, by the unchanged five-percent extra-variance
gate. In particular, a positive regular-region convergence table does not
admit those coarse low-noise chains, remove their artificial diffusion, or
establish uniform accuracy as noise tends to zero.

Run with a fresh output path:

```bash
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.round8_20261031.event_dynamics.resolution_audit \
  --output /tmp/spatial-resolution-audit-new.json
```

The source refuses to overwrite an existing evidence file. This audit checks
one regular parameter group with controlled domain truncation. It is useful
positive evidence for values and gradients; it is not a general convergence
theorem for OU processes, nonlinear boundaries, coupled cells, or learned
policies.
