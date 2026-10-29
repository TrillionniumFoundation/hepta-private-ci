# One-step bilevel training contract

The deployed readout is an eight-cell bipolar integrate-and-fire network. Its
weights and output coefficients are task-trained. Forward deployment uses only
hard comparisons and accumulated signed spikes; neither a Gaussian CDF nor a
surrogate derivative is evaluated by the native owner.

The three training arms use identical initialization, independent support/query
task streams, context schedules and support-step counts. `standard` uses a fixed
logistic surrogate. `fixed_theta` uses the fixed first-passage surrogate.
`meta_theta` jointly updates its drift, volatility and cancellation parameters.
Credit conditions are deployed using the same trained checkpoint, so credit
effects need not be conflated with retraining.

## Surrogate parameter domain

For raw parameters \(a\in[-6,6]^3\), define

\[
\mu=1.25\tanh(a_1),\quad
\sigma=0.35+1.65\operatorname{sigmoid}(a_2),\quad
\lambda=0.01+0.99\operatorname{sigmoid}(a_3).
\]

The initial physical values are \((0.25,1,0.1)\). Volatility and cancellation
remain strictly positive and the diffusion discriminant is bounded away from
zero. This eliminates the root degeneracy from the registered training domain;
it does not prove global optimizer convergence.

For a unit surrogate horizon and threshold gap \(d\ge0\), let

\[
\Delta=\sqrt{\mu^2+2\lambda\sigma^2},\quad
\kappa=(\Delta-\mu)/\sigma^2,\quad
\gamma=(\Delta+\mu)/\sigma^2.
\]

The primitive is the previously verified killed Brownian first-passage value

\[
P(d)=e^{-\kappa d}\Phi((\Delta-d)/\sigma)
     +e^{\gamma d}\Phi(-(d+\Delta)/\sigma).
\]

Its backward slope is \(g=-P_d\). The implementation evaluates the slope with a
positive Mills-ratio decomposition and differentiates that decomposition. Its
physical root derivatives satisfy

\[
\kappa_{(\mu,\sigma,\lambda)}
=\Delta^{-1}(-\kappa,-\sigma\kappa^2,1),\qquad
\gamma_{(\mu,\sigma,\lambda)}
=\Delta^{-1}(\gamma,-\sigma\gamma^2,1).
\]

The raw-parameter Jacobian of the bounded transform is included. Above the
threshold, the primitive's extension is constant and the backward slope is
zero; at the threshold its specified slope is the continuation-side limit.
This is a local surrogate for discrete neural events. It does not turn
Bernoulli evidence into Brownian motion or prove a moving-boundary theorem.

Here \(\lambda\) is the cancellation parameter of the **training surrogate**.
It is neither the task's exogenous cancellation rate nor the Organ Credit
resource price. Changing it does not silently alter deployment environments.

## Actual inner and outer objectives

At iteration \(k\), draw disjoint support and query episodes of one context.
Let \(G(W,a;S)\) denote the explicit SG-BPTT rule for the support hard-network
prefix calibration BCE. The inner step is the actual clipped and projected map

\[
\phi(W,a;S)=\Pi_{\mathcal W}
  [W-\alpha\,\operatorname{clip}_{c}(G(W,a;S))].
\]

The query loss uses a **fixed logistic-soft** network:

\[
F(a;W,S,Q)=L_{\mathrm{query,soft}}(\phi(W,a;S);Q).
\]

The query objective has no direct occurrence of \(a\). This prevents reducing
the outer loss simply by changing its own smoothing rule. Its ordinary weight
gradient is computed by exact reverse-mode algebra for that soft network.

At fixed \(W\), support hard spikes do not depend on \(a\). The SG rule's mixed
derivative \(D_a G\) is therefore computed analytically: the parameter tangents
of every slope are propagated through the recurrent backward pass. Away from
projection boundaries,

\[
\nabla_a F=(D_a\phi)^\top\nabla_\phi L_{\mathrm{query,soft}},
\qquad
D_a\phi=-\alpha\,D\Pi\,D\operatorname{clip}_{c}\,D_aG.
\]

For a clipped gradient \(\|G\|>c\),

\[
D_a\operatorname{clip}_{c}(G)
=\frac c{\|G\|}\left[D_aG-
G\frac{G^\top D_aG}{\|G\|^2}\right].
\]

The derivative of an active box projection is zero. At an exact projection kink
the implementation uses that stated branch convention rather than claiming a
unique classical derivative. Checks compare the analytic chain with complete
support-update re-solves at multiple central-difference step sizes, including
active norm clipping and box projection.

The outer update jointly changes all three raw coordinates with Adam applied
to the clipped hypergradient, followed by the raw box projection. Adam uses
\(\beta_1=0.9,\beta_2=0.999,\epsilon=10^{-8}\); every moment and update is
recorded. Each arm, including both fixed-surrogate controls, then uses the same
query labels to advance the shared weights:

\[
W_{k+1}=\Pi_{\mathcal W}\left[
\phi-\eta\operatorname{clip}_c(\nabla_\phi L_{\mathrm{query,soft}})\right].
\]

The hypergradient above concerns the query objective evaluated at \(\phi\),
before this subsequent weight update. It does not differentiate through that
later step or the full history of training. All arms use the same support and
query observations and both supervised weight updates; only the meta arm uses
the additional mixed derivative to update the three raw coordinates. This is
**online one-step bilevel surrogate
hyperparameter learning**. It is not a claim of MAML initialization learning,
an exact derivative of a hard-spike objective, or a convergent global solution.
Final task utility is assessed with hard deployment, separately from the soft
outer training loss.

## Audit and deployment interface

Development tests compare the first-passage operator against the sealed v1
implementation, differentiate its parameter slopes independently by central
differences, check ordinary soft-query derivatives, verify mixed recurrent
derivatives and check the complete bilevel map at multiple step sizes.

`network.step` performs exactly one observation update using scalar operation
order. Its state, logit and spike counts can be compared with native inference
at every event. The exported model binds the actual training checkpoint SHA and
contains all weights, thresholds and the precise six-feature schema. Truth,
future evidence and test scores are excluded from deployment inputs.

Training receipts retain every support/query digest, raw and physical parameter
update, hypergradient, clipping/projection event, conditioning diagnostic,
weight change and actual support/query cell-update count. Hard and soft work
are separately identified. Training wall and process CPU cover generation,
inner update, outer evaluation and progress callbacks inside the timed loop;
they do not include an earlier environment installation or subsequent scoring.
