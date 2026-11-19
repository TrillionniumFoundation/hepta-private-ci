# Differentiable current-state flow

`differentiable.py` advances a finite killed CTMC with deterministic delay,
event-time reset, vector signed content and discounted rewards. Each frozen
input interval is a matrix-exponential step. Its current state contains active
and upper masses, accumulated readouts, the cumulative discount factor, and
complete pending exponential release laws or release atoms. The operator
does not reconstruct history from event totals or replace refractory ages by
uniform deposits. It is a finite spatial model; upper escape is permanently
active and nonreturning, with an explicit reward.

The finite-horizon terminal condition in the implemented `state.value` is
**zero**. This field accumulates discounted active/escape running rewards and
event rewards paid at the hit, up to the current time. Waiting refractory
mass earns no running reward in this model; returning from refractory does not
pay the event reward again. No pending future reward or terminal payoff is
implicitly added. If a task declares a differentiable nonzero continuation
payoff `Phi` on the complete state, the finite-horizon objective must explicitly
add `state.discount_factor * Phi(state)` once. Such a task-specific terminal
functional is caller-defined and is not an additional payoff implemented or
validated by the present identification experiment. A perpetual value requires
its own continuation model; it is not obtained by repeatedly summing finite-step
terminal rewards.

Between calls, generator rates, rewards, discount and reset targets may change.
Each pending law retains the generator and reset target that created it; new
inputs change current active dynamics and new events. This gives a complete
forward state across input changes. Probability and signed marks use exactly
the same transport. `intervene` consumes supplied spatial-cell swept fractions
and creates a delayed release atom; computing a moving diffusion boundary's
overlap and coordinate transformation remains the caller's separate model.

PyTorch differentiates initial states, rates, reset, signed content, rewards
and discount through the complete retained packet graph. Fraction-valued
logical times and delays are fixed configuration. Saving/loading the state
preserves cold forward continuation, not the autograd tape before that save.
It therefore does not implement the original C2 full-training replay contract.

State payload includes every pending generator and mark. `tensor_bytes()`
reports the logical tensor payload, counting repeated fields; it excludes
autograd and allocator overhead. Work caps reject an oversized state or matrix
without pruning packets. Exact finite propagation can grow in cost with time;
the implementation does not claim constant-memory compression.

Run `python -m qualification.hcsn_currentstate.study_differentiable --output
NEW.json` on one line. The bounded Linux CPU study checks five excursions
against independent gamma-renewal formulas; changing rates/reset and signed
content against a DOP853 method-of-steps oracle; cold continuation and partition
composition; full-state AD/FD; swept mass; resource limits and FP32 overflow.
It then fits six positive transition rates through the complete recurrent state
to three independently generated DDE trajectories for sixty Adam updates.
The source hashes, original errors, loss path and full-state costs are saved.
This process-identification experiment complements the existing encoder and
N256/C2 experiments; each keeps its own objective and numerical definition.

## Executed result

Attempt001 passed all five integration/gradient/resource tests. Three complete
state trajectories differ from the independent DDE oracle by at most
2.64e-11; probability and signed-mark mass differences are below 8.9e-16.
The retained state has three pending packets and a 3,336-byte logical tensor
payload per two-channel case; this excludes the backward graph and allocator.
The largest exponential has order 14, with 19 calls per trajectory.
Sixty Adam updates reduce the independent-trajectory identification loss from
7.00836e-4 to 1.74838e-7. The complete Linux CPU study takes 3.412 seconds
(3.406 CPU seconds), with process peak RSS 313,100 KiB including Torch.
This is training on the three process-identification trajectories, not an
unseen-data accuracy claim. Raw results and source hashes are retained in
[evidence/differentiable-20261119/attempt001.json](evidence/differentiable-20261119/attempt001.json).

The final attempt002 adds an explicit two-layer flux-and-signed-content
backpropagation comparison: all six tests pass. It retains the same numerical
and learning limits, with the complete final source hashes in its raw output.
The complete study takes 4.007 seconds (4.006 CPU seconds), including the
additional gradient test, with peak RSS 313,192 KiB. Both attempts and their
test logs are retained. The current-state CI also runs the six tests and the
sixty-update study, retaining its own runtime, source head and raw result.

A separate [longer-horizon cost diagnostic](evidence/longtime-20261119/README.md)
keeps this kernel unchanged and evaluates five fresh-process cases against
independent finite Gamma-renewal values and rate derivatives. All five complete,
with maximum absolute value/gradient errors below 6.04e-14 / 9.06e-14. In this
one-state example, the complete logical state grows from 192 to 134,256 bytes
between one and 64 refractory intervals, despite retaining only one pending
packet: its internal generator grows from order two to 128. The results make
the long-sequence storage and backward-cost limit explicit; they do not qualify
a constant-memory cell or change any existing numerical admission gate.
