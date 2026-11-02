# Two layers with a continuously transmitted margin and a changing boundary

This is a bounded functional experiment using the already frozen H-X financial
operator and its first-order PyTorch bridge. The new object is a two-layer
stateful network with eighteen trainable financial parameters. It tests whether
an upstream continuous margin can change a downstream financial boundary within
a rollout and transmit a genuine financial conditioning gradient. It is not a
quality, generalization, multimodal, speed, power, or spiking benchmark.

## Model and precise scope

Each layer has physical log-potential `z` and adaptation `a`. Its represented
asset is `V = torch.exp(z)` in CPU FP32. The original V3 asset interface supplies
`Q = E/b`, `R = 1-(1-F)^2`, and `x = log(V/b)`. It preserves the full fixed-asset
parameter derivatives, including the dependence of the boundary on theta.
The neural channels are only Q, R, and x. Original raw F, G, and debt do not
become globally C1 channels by being returned in the diagnostic API.

For each old state, layer 1 uses

```
theta1 = base1 * (1 + 0.03 * tanh(raw_theta1))
link = FP32(x1)
drive2 = external_drive2 + 0.2 * link
theta2 = base2 * (1 + 0.03 * tanh(raw_theta2 + 0.5 * link))
```

The scalar link is broadcast into the nine downstream parameter preactivations.
Both layers then advance simultaneously by sixteen fixed Euler steps of 0.05:

```
dz/dt = drive - 0.5*(z-z_rest) - 0.15*Q - 0.04*R + a
da/dt = (0.04*R-a)/0.4
```

Both rest potentials are fixed at FP32(log(67)). Initial physical states,
external drives, connection gains, targets, and step size are fixed before any
new evaluation. Only raw_theta1[9] and raw_theta2[9] are trained. The terminal
loss is `mean((z2-target_z2)^2) + 0.25*mean((a2-target_a2)^2)`; it has no direct
margin, boundary, first-layer, or learned-head term. Layer 2 does not feed back
into layer 1. The final extra readouts are logging only and use no gradient.

The first boundary is constant within an individual rollout. The second
boundary is recomputed from the actual theta2 at every used time and sample.
The protocol requires a nonzero within-rollout range of b2 over the first
sixteen used states; a change only in final logging does not pass this gate.
This is a new model, not an equivalent coordinate rewrite of the prior
single-layer candidates.

Every H-X call still evaluates a **static** financial model. A time-dependent
theta2 does not make these values the solution of a time-dependent financial
PDE. Euler integration is not a closed-form temporal flow. The original F keeps
its static first-passage interpretation only in that original model; R is a
new observable and is not a calibrated risk probability for this feedback
process. The conditional C1 readout argument requires valid positive b and
joint regularity on a neighborhood of the states used. The tanh parameter box
alone does not prove those financial conditions, global stability, C2 forces,
or autonomous cycles.

## Four same-value gradient controls

The audit uses four graphs with identical numerical forward values:

| Mode | Drive link gradient | Financial conditioning link gradient |
|---|---|---|
| full | active | active |
| drive_only | active | detached |
| conditioning_only | detached | active |
| both_detached | detached | detached |

The mandatory tests compare actual autograd VJPs to an independently written
NumPy 4-state/18-parameter Jacobian composition and its time-reversed adjoints.
They retain actual per-time financial-parameter VJPs and raw parameter credit.
The conditioning-only upstream gradient and the norm of its time-resolved
direct b1 boundary contributions must be nonzero. Individual time contributions
can cancel; the net sum is recorded but is not required to be nonzero. The full
upstream VJP must equal the sum of the two separate
routes. Both-detached upstream parameter, initial-state, and drive gradients
must vanish, while downstream parameter gradients must agree across modes.
Early layer-1 input and state gradients must reach the terminal layer-2 loss.

The direct boundary contribution uses the actual `-b1_theta/b1` term, the
parameter-map diagonal, the downstream conditioning Jacobian, the Euler step,
and the later-state adjoint. Its time sum is recorded separately from the
remaining upstream state-history contribution. These derivative interventions
identify graph routes; they do not isolate a causal improvement in task quality.
If the financial route is zero or a gate fails, the result remains a failure.
Inputs and thresholds will not be tuned after inspecting these results.

## Precision, branching, and numerical contracts

The financial input order is r, delta, sigma, alpha, tax, liquidity, maturity,
coupon, principal, and asset. The immutable kernel returns boundary, equity,
F, G, debt and its full 5-by-10 Jacobian. Internal financial arithmetic and saved
Jacobians are FP64; neural state, represented assets, interlayer link, parameter
maps, and Euler updates are FP32. The interface rejects implicit float64 input
downcasts. It differentiates the continuous formulas at represented points as
ordinary floating AD does; it does not differentiate the rounding map.

Actual V <= raw b selects the original asset-default branch. Q=0 and R=1 there,
while the x channel retains information and its boundary derivative. Negative
margin is not clamped into a false continuation output. Default saturation and
sampled branch changes are recorded using V and raw b, not the sign of a rounded
log ratio. A sampled branch change is not an exact event time or a discrete
spike. Only first-order reverse AD is supported; V3 explicitly rejects
create_graph requests. No Hessian or C2 force is supplied.

Gradient comparisons use absolute tolerance 2e-9 plus 2e-5 times reference
magnitude. The independent record checker allows four FP32 ULPs solely when
checking cross-library exp/tanh and their derived parameter values. This
separate represented-value allowance was fixed before evaluation. It does not
alter the financial accuracy gates or the gradient tolerance. Linear links,
preactivations, and Euler reconstruction must match exact FP32 numerical values.
Exact numerical equality does not distinguish positive and negative zero.

## Frozen experiment and executable entries

The inputs are deterministic mixed default/continuation fixtures selected from
the already observed physical 40-100 asset range. They are functional cases, not
an unseen financial or task-quality holdout. The experiment is sixteen steps,
eight samples, four audit graphs, and twelve Adam updates at learning rate 0.02.
Every loss, gradient, represented trajectory, actual boundary, and effective
theta is retained. Loss reduction is not a success gate. Earlier nearly flat
training results and increased default saturation remain valid negative
observations and are not replaced by this candidate.

The required dependencies are the unchanged directories
`hx_autograd_r16_20261101` (the V3 root) and `compiled_fp32_r16_20261101/capsule`, whose
protocols, sources, and binary are checked by identity. The scientific protocol
also seals every local runnable source, including the independent checker.
Run the following from this candidate directory after its protocol and inputs
have been saved and reviewed; use fresh output paths each time:

```sh
python -B audit_two_layer.py --adapter-root ADAPTER_V3_DIRECTORY --financial-root FINANCIAL_CAPSULE_DIRECTORY --protocol-sha256 FROZEN_PROTOCOL_SHA256 --output NEW_AUDIT.json.gz
python -B train_two_layer.py --adapter-root ADAPTER_V3_DIRECTORY --financial-root FINANCIAL_CAPSULE_DIRECTORY --protocol-sha256 FROZEN_PROTOCOL_SHA256 --output NEW_TRAINING.json.gz
python -B check_two_layer_results.py --root . --protocol-sha256 FROZEN_PROTOCOL_SHA256 --audit NEW_AUDIT.json.gz --training NEW_TRAINING.json.gz --financial-root FINANCIAL_CAPSULE_DIRECTORY --output NEW_CHECK.json
```

The audit and training writers return zero only when their frozen functional
gates pass, and preserve a failure record otherwise. The independent checker
must also return zero; a completed writer alone is insufficient. The checker
uses only NumPy and sealed files, recomputing represented Euler steps, all
local chains, route controls, actual branch classification, physical loss, and
parameter update continuity. It does not replay Adam or evaluate new financial
points. Its financial values/Jacobians are archived outputs of the same frozen
kernel, not a second financial oracle. All three outputs are create-only.

`freeze_two_layer.py` is a one-time preparation utility, not a CI command. It
creates the fixed inputs, protocol, and publication mapping without importing
Torch or executing a financial model. Publication precedes the first new
functional audit. Future CI runs on these opened cases are regressions.
