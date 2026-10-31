# Fixed-cell calibration contract

## Purpose and scope

R7 already trained encoder, dynamics and readout jointly. This increment holds
its finite transition law fixed and repairs the learned four-action controller.
The independent fixed-cell optimum is a target, not a claim that a learned head
has reached that optimum. R7 nominal configurations are development data here.
The new confirmation configurations and worlds are owned by the outer study and
are not read by this trainer or used to choose a checkpoint.

The experiment uses all registered original seeds 11–15 and the direct,
continuous, clocked, and first-passage laws. The original weights remain intact.
The continuous and first-passage laws retain R7's numerical limitations. This
calibration does not certify unrestricted Gaussian propagation or continuous OU
first-passage accuracy.

## Frozen training decisions

Each stage uses 400 full-batch Adam updates, gradient norm clipping at 5, FP64,
and one Torch/OMP/MKL thread. Readout-only uses learning rate 0.01; the subsequent
`content_readout` stage uses 0.003. The final update is always retained. Traces
are recorded every 20 updates; no development or confirmation return selects a
different update. All modes receive the same updates and data rule; actual CPU
cost is recorded and is not asserted equal.

Targets are complete four-action Q* values of the independent finite product
DAG, with current event fee sunk after the incoming transition. Target generation
never reads the trained Q head. The fixed weighting mixture is 45% original
greedy occupancy, 45% optimal occupancy, and 10% uniform public/latent cells.
Each occupancy distribution is separately normalized. At each cell, squared
error is averaged over legal actions, then weighted by that mixture. The mixture
is held fixed across both stages. Q1 has no auxiliary loss and is not evaluated
or claimed as a calibrated head.

## Two encoder branches keep the target law fixed

R7's content encoder also drives the cell. Merely freezing the core parameters
and drive weights would therefore leave stale targets when content changes.
The new wrapper saves a separate frozen `kernel_content` copy:

\[
c_{read}(s)=E_{read}(x_s),\qquad
u(s)=1.5\tanh(W_{drive}E_{kernel}(x_s)+b_{drive}).
\]

The first stage trains only the readout. The second trains `content` and readout;
`kernel_content`, `drive`, and all core parameters stay fixed. This is explicitly
content/readout joint training, not full-cell joint training. The original R7
full joint fit is the baseline. Checkpoints use schema
`round8-fixed-cell-calibrator-v1`, the unchanged three-field R7 configuration,
and the original state-dict keys plus `kernel_content.*`.

## Primary diagnostic and structural ceiling

Every stage is evaluated under the deployed order: sample the internal successor,
observe it, then take the greedy legal action. The exact finite-DAG optimality
gap must equal the sum of optimal four-action regrets weighted by the deployed
occupancy. This is the primary calibration endpoint. Q-value RMSE is secondary.
All configurations are retained, including predefined failure configurations 4
and 7; no hand-selected world establishes a win. Repeated states, trajectories,
and stages are not independent training runs: the independent unit is the five
original fit seeds.

The public state in this task is a sufficient statistic for external rewards
and successors. With zero event price, backward induction gives

\[
Q^*(s,z,a)=r(s,a)-c+\sum_{s'}P(s'\mid s,a)v^*(s'),
\]

independent of internal state. Any stochastic internal transition preserves the
same `v*`. The audit compares every joint public/latent value with a separate
scalar public DP at event price zero. With price 0.0002 and at most one event per
tick, the positive event fee can change an optimum by at most `0.0002 H` (at most
0.0012 in these configurations). The no-event public optimum is an upper bound.
This task can identify approximation, optimization and cost effects; it cannot
establish that the cell gains external content information unavailable to the
already sufficient public state.

## Required receipts

Each fit retains original, readout-only and content/readout checkpoint bytes;
the original source hash; the frozen-cell hash; complete static target and weight
arrays; traces; actual training CPU cost; exact policy/occupancy audits; and the
zero-event-price equality check. The original checkpoint and each transition
matrix must remain unchanged throughout calibration. Saved two-encoder execution
must round-trip exactly. The three stages are compared without selecting a
winner from heldout results.

The trace field `active_parameter_count` counts tensor elements carrying
`requires_grad`; it includes the unused Q1 output rows within the shared final
layer. It is not a count of nonzero gradients or independently identifiable
degrees of freedom. The replay audit states this counting convention explicitly.
