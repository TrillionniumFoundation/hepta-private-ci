# Hepta: stable Call–Put flow with explicit associative memory

This is a **new execution dated 2026-10-29**. It does not restore the lost
checkpoints or raw arrays from the previous Hepta execution. The genuine
surviving historical reports and recovery inventory are in
`research_evidence/hepta_callput_recovery_20261029/`.

The implementation separates three questions:

1. Can a shared-boundary analytic operator and its actual autograd derivatives
   be evaluated accurately near the boundary?
2. Can a signed fast-boundary/slow-recovery controller train through ordinary
   backpropagation when coupled to content memory?
3. Does the analytic boundary shape improve held-out performance over a
   carefully matched smooth operator at a fixed training budget?

Only the third question tests a performance contribution from that shape.
Correct arithmetic, successful optimization, and a financial interpretation
do not establish that contribution.

## Mathematical scope

[He and Xiong, *Rollover Risk and Credit Risk*, Journal of Finance 67(2),
391–430 (2012)](https://doi.org/10.1111/j.1540-6261.2012.01721.x) jointly
value debt and equity and determine endogenous default using value matching
and smooth pasting. Their finite-maturity debt and rollover-loss model is more
elaborate than the scalar operator implemented here. In particular, our Put
channel is not the paper's default probability, and our Call is not an
independently exercisable American call sharing the same exercise boundary.

This prototype uses a reduced perpetual-put construction. For a positive
strike-like scale K and shape parameter kappa, define

```math
\beta=\frac{\kappa}{1+\kappa},\qquad B=\beta K,
\qquad x=\log(V/B).
```

Its unnormalized functions are

```math
P(V,K)=\begin{cases}K-V,& V\leq B,\\
(K-B)(V/B)^{-\kappa},&V>B,\end{cases}
\qquad C(V,K)=V-K+P(V,K).
```

Thus C(B)=0, C_V(B)=0, P(B)=K-B and P_V(B)=-1. The normalized
channels are a=C/(K+C) and p=P/K. Both depend on the same margin x.
They are continuously differentiable at x=0, generally not twice
continuously differentiable. The analytic and `matched_c1` arms have the same
boundary values and first derivatives, the same Call right curvature, and the
same output ranges. Their shapes away from the boundary differ.

This construction makes a specific reduced modeling choice. It is not a
reproduction of every financial equation in He and Xiong. A literal extension
would additionally need debt maturity, debt issuance and rollover losses,
recovery assumptions, and their coupled valuation/free-boundary equations.

## Signed boundary dynamics

`flow.py` evolves v=log(V), q=log(K), and recovery state z:

```math
\begin{aligned}
\tau_v\dot v&=-v+I_v,\\
\tau_q\dot q&=-q+q_*+g_C(a-a_*)+g_P(p-p_*)-(z-z_*)+I_b,\\
\tau_z\dot z&=-z+g_zp.
\end{aligned}
```

The reference point is q*=-x*-log(beta), z*=g_z p(x*). Its dependence on
learned parameters remains in the gradient graph. The Call raises q when the
margin rises and supplies negative feedback to x. A larger Put raises q when
the margin falls and supplies positive feedback. Delayed recovery lowers q.
Learned time constants obey tau_z >= tau_q + 0.25 in floating arithmetic.

The dynamics are integrated using ETD2 with an explicitly registered maximum
internal step. This is not an exact solution of the coupled nonlinear ODE.
Analytic kernels alone do not remove integration error or guarantee stable
training, excitability, a limit cycle, event sparsity, or energy savings.

Each example has its own subdivision count; another example's sampling
interval cannot alter its trajectory. `PreparedFlow` shares differentiable
coefficients only inside one forward graph. It is rebuilt after optimizer
updates. External sampling intervals are supplied data; the integer mesh
selection is not a claim of smoothness with respect to a learned time grid.

The shared scale can be reconstructed as log(B)=q+log(beta). The dimensionless
margin x is the more informative continuous message when V is not otherwise
available. This study uses it to control memory rates. It does not implement
a deep network whose only interlayer information is a scalar boundary.

## Content memory and causal task prior

All five arms share a matrix state M, learned keys/queries/values and readout.
For keys k, values u and nonnegative rates lambda/gamma held constant over one
external tick, `memory.py` exactly integrates

```math
\dot M=-\lambda M+\gamma(u-Mk)k^\top.
```

The implementation is finite at zero key norm and has been compared with an
independent matrix exponential. The boundary-dependent rates are evaluated
after the flow update and held constant over the tick. Consequently, exact
conditional memory integration does not make the full coupled model exact.

Gated matrix memory and delta-rule writes are existing mechanisms; see
[Yang, Kautz and Hatamizadeh, Gated Delta Networks
(ICLR 2025)](https://arxiv.org/abs/2412.06464). Their general invention is not
claimed as a Hepta result. Here the experiment isolates a proposed controller
within a shared memory mechanism.

The two synthetic tasks expose explicit event roles. Selective copying uses
causal write/read counters; associative recall binds a preceding key to its
following value and includes queries before and after overwrite. Address
construction does not inspect answer values or future events. Every learned
answer passes through M; there is no direct answer residual. These shared
parsers are substantive task priors, not learned discovery of general token
semantics. They limit extrapolation to language or multimodal models.

The four trainable-controller arms each have 726 trainable parameters and
147 floating state entries plus two integer counters and one Boolean flag per
episode. `frozen_flow` has fewer trainable parameters and is diagnostic only;
its states still evolve. `ordinary` has the same parameter/state counts but
changes the controller feature map, so it is not the primary operator-only
ablation. Sigmoid has a+p=1 and therefore redundant gain directions despite
the matching tensor count.

## Registered execution

Use Python 3.12 with `requirements.txt`. The observed execution uses CPU
PyTorch 2.8.0, NumPy 2.3.5 and SciPy 1.17.0. From the repository root:

```bash
python -m unittest discover -s experiments/call_put_stable_flow/tests
python -m experiments.call_put_stable_flow.study freeze --output NEW_RUN --max-step 0.0625
python -m experiments.call_put_stable_flow.study prepare --output NEW_RUN
python -m experiments.call_put_stable_flow.study train --output NEW_RUN --candidate CANDIDATE_ID
python -m experiments.call_put_stable_flow.study select --output NEW_RUN
python -m experiments.call_put_stable_flow.study score --output NEW_RUN
```

Run each of the 60 candidate IDs in `protocol.json` before selection. There
are five arms, two tasks, three paired seeds and two learning rates. Each
candidate reaches both 384 updates and 30 training CPU seconds. Selection
uses validation cross-entropy separately for each budget regime, including
both learning rates' costs. Test data is scored only after all training and
validation selection are sealed. Hash mismatches stop execution.

The primary comparison is analytic versus `matched_c1`. Accuracy and
cross-entropy have separately registered multiplicity families. Three seeds
yield exploratory intervals; this is not evidence for broad model scaling.
All raw weights, traces, predictions, failed numerical refinements and source
snapshots are retained under `research_evidence/hepta_stable_flow_20261029/`.

## Limits of current claims

This package establishes an executable experiment, not an advantage over
Transformers, Mamba, CfC, SNNs or full multimodal encoders. Quality, latency,
training memory and energy require their own matched measurements. No GPU
scaling or neuromorphic sparsity claim follows from CPU kernel correctness.
Historical report results remain historical observations while their original
raw evidence is unavailable; they are never pooled with this new run.
