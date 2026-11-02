# Actual H-X recurrent integration prototype, R16

This additive experiment uses the already frozen actual finite-maturity H-X
financial kernel in FP64 through the V3 first-order CPU PyTorch adapter. It is
separate from the perpetual toy's cycle argument and from numerical financial
qualification. Its purpose is to check a genuine stateful forward calculation,
cross-time financial-parameter gradients and real optimizer updates.

## Readout and recurrence

For signed neural log-margin `x`, the original financial kernel is called only
at `max(x, 0)`. The new neural readout is `(Q, R, x)`, with `Q=E/b` and
`R=1-(1-F)^2` on the positive side. At `x<=0`, it explicitly sets `Q=0, R=1`
and retains the original signed `x`. Nonfinite inputs are rejected before the
clamp. This does not widen the raw kernel's log-distance domain or reinterpret
its clamped F/G/debt as asset-default financial outputs. The ideal composite
Q/R readout is jointly C1 under the usual positive-boundary/smooth-pasting
regularity assumptions. Neither F/G nor a second-order force is called C1/C2.

The two state variables obey the *specified* value-based vector field

```
dx/dt = drive - leak*x - k_equity*Q - k_risk*R + adaptation
da/dt = (k_risk*R - adaptation)/tau
```

The implementation takes 16 simultaneous explicit Euler steps of size 0.05.
This is a sampled numerical map, not the closed-form solution of the feedback
ODE. There is no hard reset, clipping, binary event output or trainable head.
The only trainable tensor has nine entries, mapped to financial parameters by
`theta=base*(1+0.03*tanh(raw_theta))`. Changing theta changes the financial
boundary, but this small exercise does not establish an optimal boundary policy.

CPU inputs and Euler states are FP32. The original five financial fields and
their 5-by-10 Jacobian are evaluated in FP64 at those represented words; Q/R are
explicitly converted to FP32 for the state update. Gradients are derivatives of
the underlying continuous formulas evaluated at floating inputs, as ordinary
floating AD, not derivatives of rounding. Only first-order reverse AD is
supported. Temporal BPTT needs first-order local Jacobians; it does not require
`create_graph=True` or Hessians.

## Frozen checks

`RECURRENT_PROTOCOL.json` and `RECURRENT_INPUTS.json` fix all inputs, gains,
steps, optimizer settings and gates before any recurrent evaluation. The
5 signed fixtures cover negative, zero and positive x. The temporal audit uses
only terminal loss and compares all 16 per-step theta contributions against
an independent manual composition of local raw-kernel Jacobians. It also checks
initial and middle states, input drives, the shared-theta sum, and a deliberately
detached-state control whose early gradients must disappear without changing
the forward values. An all-negative trajectory has zero theta gradients and an
independently checkable 2-by-2 Euler state matrix raised to the 16th power.

The training smoke runs 12 updates on 8 fixed synthetic input sequences. It
retains every trajectory, loss, gradient and parameter update. Loss reduction
is explicitly **not** an acceptance gate. Forced sampled crossings are recorded
without being described as spikes, stable oscillations or a limit cycle.

## Commands

Use the official CPU PyTorch wheel pinned in `requirements.txt`; provide the
unchanged adapter and compiled financial capsule roots. Set `P` to the exact
SHA256 of `RECURRENT_PROTOCOL.json` in the published mapping.

```
python -B audit_recurrent.py --adapter-root ADAPTER_ROOT --financial-root FINANCIAL_ROOT --protocol-sha256 P --output NEW_AUDIT.json.gz
python -B train_recurrent.py --adapter-root ADAPTER_ROOT --financial-root FINANCIAL_ROOT --protocol-sha256 P --output NEW_TRAINING.json.gz
```

Each script creates its output once, verifies source/dependency seals, and exits
zero only when its stated gates pass. A written JSON or a training loss decrease
alone does not establish success. The protocol generator is provenance; do not
regenerate a new protocol to bypass a changed-source rejection. Results after
this first opening are functional regressions on these fixed inputs.

No claim is made here about large-model quality, multimodal generalization,
event sparsity, speed or power advantage, biological validity, global stability,
or calibration of financial first-hit probabilities under this new feedback
process. The constant-coefficient financial formula remains a local feature
calculation, not the transition kernel of this nonlinear recurrent dynamics.
