# Sixty-four-step mechanism graph and fresh-process episode recovery

This independent qualification uses the real, frozen S81 operator bundle.
It reads no task train, validation or test split. Its namespace is
`hcsn-mechanism-sequence-probe-only-v1`; model seed 60713 and private episode
RNG seed 60729 are separate from the registered task-training seeds.
The source, bundle bytes, metadata bytes and individual arrays are bound in
the receipt and checkpoint. Previous S25 or three-step results do not qualify it.

## Fixed long graph fixture

All ten arms receive two 64-step deterministic episodes. Their interval index
patterns are `(0,1,2,3)*16` and `(3,2,1,0)*16`, respectively, so both episodes
last exactly four physical seconds and both initial boundary cohorts occur.
For integer j=0..63, the first observed coordinate is
`.1 + .25 sin(.17(j+1))` in episode one and `-.2 cos(.11(j+1))` in episode two.
The second coordinate is one only at j=0; the third is the actual interval.
The fixed target vector is FP32 `[.2,-.4]`. These constants are frozen before
the first tensor execution; they will not be changed to obtain a larger
long-range derivative or a passing result.

Every arm's final output is compared with the independently implemented
NumPy FP64 observer in `mechanism_qualify.numpy_mirror`, using represented
FP32 inputs, weights and fixed operators. The maximum absolute forward error
must be <=2e-5. This checks the learned observer graph, not the physical
accuracy of a transition matrix that both implementations consume.

For `regenerative_dual`, `risk_only` and `conditional_boundary`, autograd is
compared with central FP64 finite differences (step 1e-4) for the two largest
observed weight gradients in each of encoder layer 1, encoder layer 2, gate
and readout. This selection avoids vacuous zero checks; it does not represent
all 2,890 parameter derivatives. Each finite-difference derivative must be
finite and exceed 1e-10 in magnitude, and its absolute disagreement must be
<=2e-7 + .005 times its magnitude.

The first observed coordinate of episode one is separately differentiated
through the complete 64-step graph to the final mean squared loss. Independent
five-point differences use steps .002 and .001. Numerical FD consistency and
nonzero long-range sensitivity are separate gates. The two FD estimates must
agree within 1e-11 + .005 times the fine estimate. Autograd must meet absolute
error <=2e-7 + .005 times the fine estimate; when the estimate magnitude is
at least 1e-8, relative error must additionally be <=.01. A derivative below
1e-8 is reported as `sensitivity_unresolved_or_vanished`, not as evidence of
long-range sensitivity merely because two tiny numbers agree. It fails the
separate nonzero-sensitivity gate. All arm results and all failed gates remain
recorded; fixtures and thresholds are not adapted after execution.

## Actual-bundle optimizer recovery

Recovery uses `regenerative_dual`, the actual S81 bundle, the same learned
architecture and standard Adam at learning rate .001. A block is one complete,
independent 64-step episode minibatch with two examples and one optimizer
update. Each model forward initializes its belief from the first-step kernel;
no belief is supposed to persist between independent episodes.

The private CPU Torch generator creates recovery observations, interval
indices and a bounded synthetic target within this probe only. After the first
update the checkpoint stores model parameters and buffers, Adam, private RNG,
global Torch RNG, next episode number, source hashes and bundle identity.
The second episode update is performed uninterrupted and in a fresh Python
process after loading that checkpoint. Inputs, predictions, loss, gradients,
model, optimizer and RNG must match exactly on the same dtype/device. The
checkpoint file hash is verified before loading. This requires three actual
optimizer updates per device: first, uninterrupted next, replayed next.
If the child times out or supplies no complete receipt, the exact total is
unknown. The receipt records a lower bound of two completed parent updates
and an unknown child-update count; it does not relabel that lower bound as
the exact total. An owned timed-out child is killed, reaped and its observed
exit code recorded.

This test establishes neither continuity of a belief across episodes nor
production fault recovery. In particular, it does not borrow the separate
FV distribution-state continuation evidence. It does not test a task data
loader, a selected learning-rate outcome or a task split.

## Execution and costs

CPU and CUDA run independently with a per-device bounded stage; the fresh
child has a 180-second limit. The source is unchanged throughout each run.
All graph checks run before the recovery test, but a failed sensitivity gate
does not prevent recovery evidence from being collected. Receipts distinguish
graph agreement, resolved first-input sensitivity and episode recovery.
The overall gate is successful only when all required gates pass.

Record the actual completed updates, episode steps, wall time, parent and
child CPU times, memory and available GPU device-counter scope. Clocks that
overlap are not added. Full-machine physical energy remains unknown. Task
training updates and original-campaign completion credit remain zero.
The shared Torch setup resets CUDA peak counters, so graph and recovery
parent peaks are saved separately before reset; their maximum is the parent
allocated-memory peak. The child reports its own peak. A combined physical
device-memory peak is not inferred by adding these measurements.
