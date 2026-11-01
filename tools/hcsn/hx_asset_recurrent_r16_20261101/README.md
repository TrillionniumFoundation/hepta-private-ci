# Fixed physical log-potential H-X recurrent candidate

This is a **new dynamical model and initial-state family**, separate from the
signed independent-margin recurrent V1. All earlier V1 sources, inputs, gates
and the nearly unchanged V1 training loss remain preserved. The original
financial C++ kernel and V3 first-order adapter are unchanged.

## Exact model and what changes

The state is physical log-potential z, with represented V=exp(z). The physical
initial z, external drive, restoration reference z_rest, and terminal targets
are fixed once in ASSET_INPUTS.json and do not depend on trainable theta.
z_rest is the single FP32 representation prepared from log(67).

```
(Q,R,x) = original_V3_asset_readout(theta, FP32_exp(z))
Q = E/b
R = 1-(1-F)^2
x = log(V_represented/b(theta))
dz/dt = drive - leak*(z-z_rest) - k_equity*Q - k_risk*R + adaptation
da/dt = (k_risk*R-adaptation)/tau
```

The implementation takes 16 simultaneous explicit Euler steps. Q/R are used as
values, not gradient forces. x is retained as a diagnostic readout; the terminal
loss reads only actual z and adaptation. No loss, initial-state or restoration
reference is recentered using the learned b. A fixed z_rest replaces the prior
theta-related log(b) reference, so this is not an equivalent coordinate rewrite.

At each fixed z, the represented physical asset is independent of theta. The
original asset interface carries the full parameter derivatives, including the
moving-boundary contribution. In the ideal continuous formulas,

```
Q_theta|z = E_theta|V/b - E*b_theta/b^2
Q_z       = V*E_V/b
R_theta|z = 2*(1-F)*F_theta|V
R_z       = 2*(1-F)*V*F_V
x_theta|z = -b_theta/b
x_z       = 1
```

The asset Jacobians already include the dependence of the financial functions
on b. Applying an additional moving-boundary shift to them would double count
that dependence. The numerical exp(z) graph is kept intact. Because exp is
computed in FP32, log(V_represented) is not assumed exactly equal to z; the
roundtrip discrepancy is recorded. There is no silent FP64 input downcast.

## Financial and differentiation contracts

Only finite CPU torch.float32 inputs are accepted. Nonfinite inputs, overflow
or underflow of represented exp(z), and rejected financial parameters propagate
as errors. The original asset interface requires V>0 and handles V<=b with its
actual financial default branch. Q=0 and R=1 there; x still carries the state
and boundary information. Raw F/G/debt are not made C1 or used as neural channels.

The original five financial outputs and 5-by-10 Jacobian are computed internally
in FP64 at represented FP32 inputs. Q/R are explicitly converted to FP32 for
the Euler updates. Gradients follow the continuous formulas evaluated at those
represented points, not derivatives of rounding. V3 rejects create_graph=True;
ordinary first-order BPTT is supported. Conditional joint C1 of Q/R is not a C2
force claim. No reset, binary output, event sparsity or analytic temporal flow is
introduced.

Every normal recurrent state update retains its graph. One extra no-grad
financial readout at the final state records the seventeenth state margin/phase;
it is logging-only and cannot enter the terminal loss. Explicit detach_state
mode is a diagnostic negative control, not the trained model.

## Fixed functional experiment

The protocol fixes 16 steps, 8 driven sequences, 12 optimizer updates, and one
9-vector raw_theta mapped as base*(1+0.03*tanh(raw_theta)). There are no learned
gains or output head. The terminal loss is mean((z_T-target_z)^2) plus 0.25 times
mean((adaptation_T-target_adaptation)^2). Loss improvement is not an acceptance
gate. Every state, margin, represented asset, loss, gradient and parameter update
is retained, including weak or negative training results.

The audit covers five physical-state fixtures, complete parameter and z chains,
15 input/interface contracts, per-time theta VJPs for terminal-only loss, a
manual raw-Jacobian discrete adjoint, initial/middle-state and early-drive
gradients, a detached-state negative control, and the all-default linear Euler
matrix raised to the 16th power. A before/after fixed-physical-input fixture
checks that any boundary motion shifts its margin by -log(b_final/b_initial),
while represented V remains identical. Nine parameters also change feature
shape; this test does not isolate a causal task benefit of threshold motion.

The manually composed reference is independent of the PyTorch temporal graph
but uses the same previously validated financial Jacobian. It is not a separate
financial high-precision oracle or a new financial holdout. The five known
functional fixtures include near-boundary points selected from the already
observed baseline b; they are not advertised as unseen cases.

## Reproduction

Use immutable adapter and compiled financial roots and the exact protocol SHA P
in the publication mapping. All outputs are create-only:

```
python -B audit_asset.py --adapter-root ADAPTER_V3_ROOT --financial-root FINANCIAL_ROOT --protocol-sha256 P --output NEW_AUDIT.json.gz
python -B train_asset.py --adapter-root ADAPTER_V3_ROOT --financial-root FINANCIAL_ROOT --protocol-sha256 P --output NEW_TRAINING.json.gz
```

Exit 0 means the corresponding frozen functional gates pass. A file existing or
a loss decreasing alone is insufficient. Do not regenerate the protocol to
bypass source identity failures. Subsequent executions on these opened fixtures
are regressions. No quality, generalization, SNN/Transformer superiority, limit
cycle, global stability, calibrated feedback first-hit probability or GPU/power
advantage is claimed by this protocol.
