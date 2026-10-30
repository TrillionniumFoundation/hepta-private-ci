# HCSN v4: bounded regularized associative memory

This is a new memory component within this prototype, added to the fixed-finance
full HCSN gate, its toy reference, and its ordinary sigmoid control. It uses
regularized least-squares associative retrieval; it is not claimed as a new
statistical estimator and does not follow from the He–Xiong equity solution.
The same memory without fast/slow financial-neuron dynamics is a required control.

## API and task contract

`models.init_model(kind, key, input_dim, hidden_dim, output_dim)` returns a JAX
parameter pytree. `models.apply_model(params, x, dt, kind)` accepts
`x[batch, time, features]` and strictly positive `dt[batch, time]`, returning final
classification logits. `return_aux=True` additionally exposes the sufficient
statistics and fast/slow states for the four ridge variants. Financial parameters
and the operator table are fixed; key, query, value, write, boundary, and dynamic
neuron parameters are learned. The fixed table is shared by units.

Every input coordinate and log(1+dt) enters generic dense projections. There is
no model code selecting the data generator's marker, key, value or answer
coordinates. Key and query share exactly the same projection. The final token
queries the prefix statistics and does not write into them. This final-query
contract is suitable for the sequence-to-one tasks here; it does not establish
cheap per-token autoregressive decoding.

The full operator receives `z = x_fast - boundary` in natural diffusion units,
corresponding to `log(V_b/V)/(sigma sqrt(m))`. Its C1 risk patch/mirror remains an
explicit neural design. It is not relabeled as an original smooth-pasting put.

## Recurrence and certificate

For key dimension K=16, bounded key and value are

\[
k_t=\tanh(W_k u_t+b_k)/\sqrt K,\qquad
v_t=\tanh(\text{learned candidate}_t).
\]

Consequently \(\|k_t\|_2\le1\), while each coordinate of \(v_t\) lies in [-1,1].
The value vector's Euclidean norm need not be at most one. The generic C1 gate

\[
w_t=\frac{\max(s_t,0)^2}{1+\max(s_t,0)^2},\qquad s_t=W_wu_t+b_w
\]

lies in [0,1] and is exactly closed for nonpositive scores. The implementation
uses algebraically equivalent reciprocal branches to avoid squaring an extreme
positive score. The derivative at zero is zero and both derivatives at the
branch junction s=1 are 1/2.

Initialize \(r_0=1\), \(G_0=0\), \(H_0=0\). At each prefix token,

\[
r_t=\frac{r_{t-1}}{1+w_tr_{t-1}},\qquad
\alpha_t=w_tr_t,
\]
\[
G_t=(1-\alpha_t)G_{t-1}+\alpha_t k_tk_t^\top,
\qquad
H_t=(1-\alpha_t)H_{t-1}+\alpha_t k_tv_t^\top.
\]

Writing \(S_t=\sum_{i=1}^t w_i\), induction gives

\[
r_t=(1+S_t)^{-1},\quad
G_t=\frac{\sum_iw_i k_ik_i^\top}{1+S_t},\quad
H_t=\frac{\sum_iw_i k_iv_i^\top}{1+S_t}.
\]

Every update is a convex combination, and closed writes preserve all three
states. In exact arithmetic, G is PSD with trace at most one and every column
of H has Euclidean norm at most one. The read map is

\[
R_t=k_q^\top\left(\tfrac12(G_t+G_t^\top)+\lambda I\right)^{-1}H_t,
\qquad\lambda=0.01.
\]

Thus the matrix eigenvalues lie in [0.01,1.01], its spectral condition number is
at most 101, and the separate bounds on H and the inverse give the conservative
read-coordinate bound 100 used in the initial certificate. The common weights
of G and H provide a stronger result. For each column h_j of H, put
\(t_j=\sum_iw_i v_{ij}^2/(1+S_t)\le1\). The joint second-moment matrix
\(\begin{pmatrix}G&h_j\\h_j^\top&t_j\end{pmatrix}\) is PSD, so
\(h_jh_j^\top\preceq t_jG\preceq G\). Consequently

\[
|R_j|^2\le k_q^\top(G+\lambda I)^{-1}G(G+\lambda I)^{-1}k_q
\le\max_{g\in[0,1]}\frac{g}{(g+\lambda)^2}
=\frac1{4\lambda},
\]

and the exact-arithmetic read bound sharpens to **5** at lambda=0.01. This
post-freeze proof refinement changes no implementation or test threshold; the
original conservative bound remains valid. The output uses tanh(R), plus bounded
learned fast/slow/current residuals. Symmetrization removes roundoff asymmetry;
the exact PSD theorem is not itself a floating-point error bound. Numeric
eigenvalue, residual and gradient checks accompany it.

Writing A=G+lambda I and B=A^{-1}H, the read differential is

\[
dR=(dk_q)^\top B+k_q^\top A^{-1}(dH-dA\,B).
\]

The implementation uses a solve rather than explicitly forming an inverse.
Strict positive definiteness makes this read differentiable; composing it with
the C1 write/financial gates and a finite scan permits ordinary backpropagation
through time. This establishes existence of the implemented gradients, while
their conditioning remains an empirical and analytic concern discussed below.

The fast/slow update uses positive bounded timescales and frozen-gate exponential
steps. For positive time gaps and q,a in [0,1], zero initial states imply
\(x_t\in[-9,9]\) and \(y_t\in[0,6]\): every update interpolates between the
previous state and a target in these intervals. The frozen-gate step is not the
exact solution of the complete nonlinear neuron ODE.

## What the certificate does not show

Finite matrix condition does not prove that long-time BPTT avoids vanishing or
exploding gradients. Matrix inverse derivatives can include factors of
\(1/\lambda^2\); the trainable projections and readout have no universal weight
bound. The recurrence also normalizes by total write mass, so an old rare item
can become less influential as writing continues. More precisely, the fitted
matrix B minimizes

\[
\sum_iw_i\|v_i-B^\top k_i\|_2^2
+\lambda(1+S_t)\|B\|_F^2.
\]

Thus a fixed lambda on normalized statistics increases the effective ridge in
the unnormalized sum as write mass grows. Fixed lambda deliberately keeps
conditioning bounded; lambda times r would change that tradeoff and was not
adopted. Neither arbitrary-length exact recall nor unlimited association
capacity is claimed.

The memory-only variant's prefix statistics are permutation invariant when
tokens and their local time-gap features are permuted together: key, value and
write weight depend only on that token, and their weighted sums commute. With a
fixed last query, this variant therefore cannot represent every order-sensitive
decaying-filter target in the irregular task. Fast/slow dynamics supply temporal
order information. A gain from adding those states is distinct from a gain from
the particular financial activation shape.

## Experimental provenance and resource accounting

Development used base 2690000, one development initialization, only train and
validation, and four runs. FullHX and memory-only both reached 100% validation
accuracy on memory and retrieval. The initial run encountered a JAX tracer leak
from lazy table loading; its source and error log are preserved in
`development_failures/aot_lazy_table/`. Loading the fixed table at module import
resolved this implementation error. No architecture change followed the scores.

Before any confirmation test construction, `freeze.json` froze sources and
protocol. Confirmation uses base 2700000, five initializations, training lengths
8/16/32, 600 updates of 32 examples, and a 0.003 learning rate for every model.
Only validation loss selects checkpoints. The primary FullHX targets apply to
every seed and every test length 32/64/128: memory at least 95%, retrieval at
least 90%. Base 2800000 provides separately declared 512-token, eight-association
and noisy-filler challenges with no post hoc passing threshold.

The trainable parameter target is about 6200. FullHX/toy/sigmoid have width 62
and 6217 trainable parameters; ridge memory-only has width 66 and 6250. Logical
persistent state is respectively 1373 and 1313 FP32 scalars per sequence,
excluding temporary activations and parameters. The full financial gate adds
131128 fixed FP32 bytes, about 128.05 KiB, shared across neurons.

Per prefix token, the statistical state update costs O(K²+Kh), in addition to
the learned value projection and dynamics. A final read costs
O(K³+K²h). Streaming inference state is O(K²+Kh+h); ordinary BPTT activation
storage still depends on sequence length. Matching parameters, data and updates
does not match persistent state, FLOPs, compilation, energy, or hardware cost.
The ordinary GRU, Transformer and SNN comparisons test small architecture
packages on this synthetic family, not all members of those architecture classes.

## Files and reproducibility

`validation.json` contains the declared tolerances, exact-closure checks,
independent weighted-sum comparison, FP32/FP64 gradients and stress inputs.
`results.json` records every confirmation checkpoint, data fingerprint,
validation history, training budget, latency and test score. `challenge_results.json`
contains fixed-checkpoint extrapolation results. `audit_results.json` replays all
test32 scores and verifies every checkpoint hash and dataset fingerprint.
`stress_solve_results.json` checks zero and rank-one states approaching the
matrix condition bound. `REPORT.md` is generated from these measured results.
