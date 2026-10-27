# What the current Hepta experiment exercises

The native controller executes real recurrence, but only across two public
preview events within an independently initialized case. It is a test of a
fixed nonlinear history representation and a learned action readout. It does
not exercise the full stateful Hepta host, persistent learning, or a recursive
parameter-field controller. This boundary applies even if a later primary
comparison is favorable.

This review inspects source and already completed development reports. It
does not fit another candidate, read primary/audit outcomes, or modify frozen
H7/D1 code. The development proposal below is unexecuted and requires separate
coordination before a source/protocol freeze.

## Executed state and control sequence

The V1 task encodes one observation with seeded latent noise, decodes and reads
preview 0, applies the common fixed `couple` transition, and decodes and reads
preview 1. Each preview supplies eight public confidence, consistency, missing
fraction, and entropy features. Only after both previews does the controller
choose one of five final continuations. The final chosen continuation is
actually executed and scored; there is no second policy decision after it.
The model and observer remain fixed during this episode. [Task source][task]

The Rust bridge initializes `state = None` inside each request. It feeds
signed Q24 encodings of the two eight-vectors into the actual `sparse_tick`,
then discards the checkpoint. The kernel has 20 units, top-4 activation, fixed
paired inhibition, temporal decay 0.75, activity decay 0.75, threshold
adaptation, and eligibility decay 0.5. The readout receives only the final 20
activations and 20 eligibility coordinates. All kernel configuration values
are fixed; the fitted coefficients belong to the external Python ridge
readout. [Bridge source][bridge] [Readout source][controls]

The following operations genuinely use the previous checkpoint:

| Mechanism | What occurs in the two-event bridge | Scope limit |
|---|---|---|
| Temporal recurrence | The second temporal vector includes 0.75 times the first temporal vector. | One previous event; no cross-case memory. |
| Inhibition | The first activation affects the second score through fixed signed-pair edges. | No learned graph or population-level recurrence. |
| Homeostasis | First-tick activity updates the threshold used by tick 2. | Starting from zero, the first active-unit threshold is approximately 0.000781 in Q24 units. The second threshold update is never used by a later tick in this bridge. |
| Eligibility | The second trace combines half the first trace with current drive times activation, subject to the existing L1 bound. | It is read as a feature, not multiplied by a modulator to update model parameters. |
| Prediction error | The kernel can compute a discrepancy from a supplied prediction vector. | This bridge supplies an all-zero prediction vector; no prediction-error learning or adaptive prediction model is exercised. |

These statements follow directly from the original kernel and bridge, not from
action-change rates. The native mechanism must therefore not be described as
having no recurrence. Equally, two real ticks do not establish the usefulness
of long memory, converged homeostasis, or online plasticity. [Kernel][sparse]

## Hepta capabilities outside this experiment

The same pinned crate contains a stateful `NeuronRuntime` with journal and
witness recovery, an inference-control model-port adapter, population temporal
projection, and three-factor plasticity statistics projected into registered
parameter groups. The bridge calls none of these interfaces: it imports
`SparseConfig`, `SparseTick`, and `sparse_tick` directly. Its NDU/body digests
explicitly identify a target-free research profile rather than a complete
product NDU. Eligibility statistics here are not SGD momentum and are not a
proof of synaptic learning. [Runtime][runtime] [Inference port][inference]
[Population mechanism][population] [Plasticity][plasticity]

The kernel returns `DENY_ALL` and `requires_calibration=true`; the bridge
checks those values and records `native_owner_integration=false`. The Python
research harness can use these features to select its own model continuation.
That does not authorize the kernel to dispatch product effects or establish
production integration. These actual authority flags must remain unchanged.

## Information and interpretation

Write the complete public history as `h=(x0,x1)` and the native readout as
`z=phi(h)`. The current history comparator preserves both raw events. Since
the native transform is deterministic, any unrestricted policy using `z`
can be emulated by a policy using `h`. Native state therefore adds no new
information beyond those same observations. A finite-sample gain would be
evidence for a useful representation, inductive bias, or resource tradeoff
within the declared fitting procedure. It would not establish access to an
additional information source. Equal 40-dimensional heads and equal candidate
counts do not make the two feature families identical in capacity or cost.

The previews are informative computations and their difference may matter.
Their being self-generated does not make them useless. The narrower issue is
that the observation, seeded noise, and intermediate action are common and
fixed: no controller can choose an informative first action, receive a new
external measurement, and then adapt the next action. A task designed to test
that loop needs its own observed interaction sequence and action budget.

The prior raw native readout loses some public input distinctions. The
completed normalization diagnosis found strong first-tick competition from
the disagreement channels and an exact structural input collision; the
raw-preserving hybrid repairs the omission of the original 16 coordinates.
Neither development attempt established a consistent native advantage over
its equally tuned history family. More nonconstant coordinates or faster
transport do not close that efficacy question. See the preserved
[normalization review](NATIVE_REPRESENTATION_REVIEW.md) and
[hybrid review](HYBRID_CONTROL_REVIEW.md).

The original reset arm reuses the normal native head after deleting the first
checkpoint. It measures sensitivity to that intervention, with a changed
feature distribution. It is not a separately optimized memoryless policy and
does not alone identify beneficial memory. If a new selected controller uses
the raw16+native24 hybrid, resetting its native checkpoint also leaves the
raw first-event coordinates available. That intervention concerns the native
recurrent component, not removal of all historical information.

## Relation to the parameter-field paper

R45 defines a complete optimizer state, a fixed observable of that state,
an objective over future costs, and a declared intervention space. It separates
reachable projection forcing, information/policy loss, restricted actuation,
and coefficient/moment error. It explicitly distinguishes useful approximate
fields on their reached law from global closure, and does not identify a
loss panel with a recursive value merely because it is low-dimensional.
[R45, framework and information sections][paper]

The native two-event state has a different clock and meaning: it summarizes
inference previews while model parameters are held fixed. The H7 experiment
instead observes and controls actual local SGD trajectories, preserving
optimizer state. These are potentially complementary control layers, but
calling both of them a field does not identify their dynamics or value
functions. A successful combined arm would show an empirical interaction of
the registered training and inference policies. It would not verify the
paper's Riccati, HJB, FBSDE, scalar-martingale, or optimizer-closure assumptions.
The constructed momentum witness motivates this distinction without claiming
that its flipped optimizer states occur in the registered trajectory law.

## Coordinated development proposal; not executed

Before adding a longer native state or more kernel parameters, use only the
three existing frozen train/development banks to ask whether the first public
event adds usable decision information beyond the second event. A separately
registered diagnostic can compare four independently trained readouts:
current-only history, complete two-event history, native state reset before
the second event, and normal two-event native state. Use the same fixed
normalization grid and fitting opportunity on each side, preserve every head
and adverse seed, and include stop plus strong fixed-action references.
Source-pair grouping must keep all four conditions together; the development
set is already used for selection and cannot become fresh confirmatory data.

This would distinguish missing historical information from an inadequate
native readout. An unfavorable result would not prove that history never
helps. A favorable development result would only nominate a prospective
comparison. Existing two-event return banks cannot reconstruct unexecuted
long-horizon or action-dependent feedback trajectories, so those claims
require a new task/protocol rather than relabeling old rows.

The immediate primary protocol may keep the current two-event task and the
already specified equal-budget native/history family. Its inference should
remain exactly about that task. Genuine closure of the comparative-benefit
blocker requires the prespecified held-out effect and retention criteria;
engineering parity, information preservation, and a proposed future task are
separate accomplishments.

[task]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8ce0f538857f8bd869e275aa7fd258aa7989113/experiments/multimodal_output_portfolio/field_bridge_20261027/task.py
[bridge]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8ce0f538857f8bd869e275aa7fd258aa7989113/experiments/multimodal_output_portfolio/field_bridge_20261027/bridge_probe.rs
[controls]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e8ce0f538857f8bd869e275aa7fd258aa7989113/experiments/multimodal_output_portfolio/field_bridge_20261027/controls.py
[sparse]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f198ad85cfa2aa579032256355f446cfe793a0/codex-rs/hepta-neuron/src/sparse.rs
[runtime]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f198ad85cfa2aa579032256355f446cfe793a0/codex-rs/hepta-neuron/src/runtime.rs
[inference]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f198ad85cfa2aa579032256355f446cfe793a0/codex-rs/hepta-neuron/src/inference_control.rs
[population]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f198ad85cfa2aa579032256355f446cfe793a0/codex-rs/hepta-neuron/src/population_v2.rs
[plasticity]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/63f198ad85cfa2aa579032256355f446cfe793a0/codex-rs/hepta-neuron/src/plasticity.rs
[paper]: https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex
