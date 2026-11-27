# Initial-amplitude adjoint: stage 1 intent

This is a new continuous finite-DDE candidate. No numerical qualification is
inherited from #6241, the physical-partial candidates, a larger mesh, or the
continuum diffusion. Its initial status is HOLD until its own evidence exists.
The first stage uses NumPy/SciPy on two small fixed models; it has no Torch
adapter or optimizer. Existing interfaces remain unchanged.

## Domain and snapshot

Physics, actual spatial geometry, rational query times and phase supports are
fixed. Amplitudes are the signed linear extension of active probability,
signed content, phase mass and phase signed content. Normalized probability
clients require their own explicit parameterization. The lower absorbing
coordinate is excluded; the permanently active upper escape is included.
No derivative of physics, delay, supports, initial migration, filtering,
training history or cross-checkpoint state is claimed.

`freeze_problem` copies the actual model's transient row generator Q, lower
and upper exit rates k/u, actual reset interpolation r, actual nodes, d/q,
validated query times and phase supports. Arrays are read-only and their
complete identity is checked before and after each solve. Later mutation of
the caller's model or containers has no effect on this snapshot. Any future
custom backward must retain the snapshot used by its forward; reconstructing
it from mutable metadata during backward is forbidden.

## Equations and sides

For each independent mark, state is y=(a,U,R,M,H,A,Z), where a has N-1
interior coordinates. The initial active input has N coordinates, including
U. With eta=exp(-q d), define

```
a' = Q^T a + r [k^T a(t-d) + f_phase(t)]
U' = u^T a
R' = k^T a - k^T a(t-d) - f_phase(t)
M' = k^T a
H' = exp(-q t) k^T a
A' = exp(-q t) [sum(a)+U]
Z' = eta k^T a + q Z - k^T a(t-d) - f_phase(t).
```

Negative-time active hit history is zero. Initial phase amplitudes separately
initialize R and weighted Z, and release through the known fixed supports.
Let b=(r,0,-1,0,0,0,-1), h=(k,0,...,0), B=b h^T, and L(t) be the
instantaneous forward matrix above. For J=sum_i v_i^T y(t_i),

```
-lambda'(t) = L(t)^T lambda(t) + 1(t+d<=T) B^T lambda(t+d)
lambda(t_i^-) = lambda(t_i^+) + v_i
w(s) = lambda(T-s)
w'(s) = L(T-s)^T w(s) + B^T w(s-d), w(s<0)=0.
```

The instantaneous reverse Jacobian includes the physical clock
exp(-q*(T-s)) and the positive q coefficient on Z. The delayed rank-one
term reads completed history and is excluded from the current Jacobian.
Only query cotangents jump w. Phase release is an affine input source and
does not jump or force w. Reverse breakpoints include query jumps, sampling
points and their delay translates; interpolation never crosses a jump.

Forward queries see the state after same-time releases. Reverse evaluation
first adds the query cotangent, then samples an atom. The initial gradient
uses the query-inclusive lambda(0), including a query at zero. Thus an atom
at remaining time rho has phase gradient

```
lambda_R(0) + exp(-q rho) lambda_Z(0)
  + 1(rho<=T) b^T lambda(rho^-).
```

For a uniform support [a,b], replace the exponential by its exact support
average and the last pairing by its integral over [a,min(b,T)]/(b-a).
At rho=0 the R/Z initialization cancels the release sink, leaving the reset
pairing. Stored BDF interpolation is a polynomial of degree at most five;
3- and 4-point Gauss rules independently integrate that same polynomial.
Their agreement checks polynomial integration, not the DDE time error.

This is a numerical continuous-DDE adjoint. It is not the discrete backward
of the adaptive BDF program, and need not be a bitwise transpose of a
numerically computed forward basis. Agreement is assessed with declared
finite time tolerances and independent reference data.

## Admission and resource limits

Admission: N=4..32, 1..5 marks, 1..5 strictly increasing queries, at most
8 phase supports in [0,d], T<=min(.6,3d), q in [.001,4]. Initial stage
actually exercises uniform N=7 and graded N=12, each using its actual
ingredients, and scalar counterexamples. It does not admit N=512.

Per adjoint: <=185 state scalars; <=64 distinct resolvable exact method
breakpoints; <=4096 accepted BDF steps; <=100000 RHS calls; current sparse
Jacobian <=10000 nonzeros; <=1000000 float64 dense/snapshot coefficients;
phase pairing <=250000 quadrature evaluations. The coefficient cap is a
stored-payload cap, not a process RSS limit. Process peak RSS, actual steps,
RHS, sparse nnz, stored payload and times are reported. No all-basis map is
allocated. Sparse actions do not imply that complete solver cost is O(N).

Stage budget: exactly 18 adjoint calls (two have zero horizon), two static
perpetual solves, at most 1024 independent small matrix exponentials,
zero forward DDE/basis calls, zero Torch calls and zero optimizer updates.
NumPy source and harness must be committed before this stage is executed;
source-before/after and original raw arrays must be retained.

## Prefrozen acceptance matrix

For both geometries:

1. Compare all 69 initial-amplitude VJP coordinates with the original #6241
   shared-forward-basis contraction, and ten scalar directional contractions
   against its retained two-step FD data. No old experiment is rerun.
2. Tighten rtol/atol from 2e-11/2e-13 to 2e-12/2e-14 and max step .01 to
   .005. Queries 0,.13,.29,.53 cross two deterministic delays d=.21.
3. Preserve the same result after mutating live times, supports and model
   physics after snapshot creation. Mutating the snapshot is rejected.
4. Mass conservation functional sum(a)+U+R has unit gradient for every
   active and phase amplitude, including signed marks.
5. The finite-model Bellman continuation functional
   h H(T)+alpha A(T)+exp(-qT)[a(T).V+U(T)*alpha/q+Z(T)*V_reset]
   has initial gradient V and phase gradient E[exp(-q rho)]*V_reset.
6. Atom at zero, atom exactly on a query, and an atom's delayed front are
   compared with independent augmented CTMC matrix exponentials before any
   new return is possible. An R-only cotangent at release must give zero.
7. Uniform support endpoints coincide with queries. Compare phase pairings
   with independent 32/64-point integration of the same CTMC reference.
8. Upper occupation gradient is (1-exp(-qT))/q.

Scalar checks are x'=c*x(t-d), whose initial gradient for d<T<2d is
1+c*(T-d), and a'=-alpha*a, H'=k*exp(-qt)*a, whose initial H gradient is
k*(1-exp(-(alpha+q)T))/(alpha+q). These catch sign, delay direction,
negative-history and discount-clock mistakes.

General comparisons require abs error <=3e-7+2e-5*abs(reference).
Time tightening uses 1e-7+1e-5*abs(reference). Mass and continuation use
2e-7+2e-6*abs(reference). Zero-time algebra uses 1e-12+1e-12*abs(reference).
Reference quadrature convergence uses 1e-11+1e-10*abs(reference). Upper and
scalar checks use the tighter limits recorded directly in the harness.
These mixed gates are not relative rare-tail qualification.

## Remaining gates

Even a stage-1 PASS leaves: actual first-order Torch custom backward and all
input/version guards; scalable memory/cost at N=128/512; broad physics and
phase domains; derivatives of physics/support/delay/migration; full network
training and restoration; continuum rare-phase error; independent task and
control comparisons. Global HCSN status remains HOLD.
