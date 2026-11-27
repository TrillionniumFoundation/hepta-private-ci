# A task-boundary population-flow network: frozen research comparison

This candidate puts the complete deterministic-delay neuron, actual interlayer
content transport, and a scalar task-derived boundary into one implementation.
It is a bounded finite-state research model, not a qualified multimodal backbone.

## Actual model and scope

Each layer preserves probability, signed content, permanent upper escape,
cumulative firing/discounted firing, active occupation, value and exact pending
release packets. It receives the preceding layer's previous-interval integrated
hit mass and content mass. Thus there is one declared sample interval of
synaptic latency. Writes add `tanh(W input)` marks only to currently active
mass, after due release atoms have entered the active state. A complete state
includes every packet, the message buffer and content-write ledger.

The scalar Brownian control objective is active reward `gain * Y - maintenance`,
release cost `K`, zero reward during refractory waiting, fixed absolute reset,
and positive discount. `neural_control.py` solves its regenerative matching and
smooth-pasting residual with a first-order implicit derivative. `task_physics.py`
connects that boundary to the actual finite process: four central-difference
interior nodes, extent 1.5, and an explicitly interpolated initial/reset law.
The finite model's perpetual linear solve and complete-state continuation value
agree with its forward rewards and pending release laws.

The boundary is episode-fixed. The finite projected policy is not asserted to
be optimal for this coarse grid. The classifier learns a bounded task cost
`K = .15 + .02*tanh(raw_cost)` through the actual boundary/reset/flow/readout
path; this is a scalar control-policy parameterization used by a classifier.
It does not solve the classification problem's content-dependent Bellman or
intervention value, and is not an endogenous classification decision surface.

Within a batch the physical probability law is identical. One probability
trajectory is shared while all sample-specific content channels are propagated
separately; independent-batch forward and VJP comparisons verify equivalence.
Inputs affect signed content, not the shared probability firing-time law.
Consequently the `flow_mass` arm is an intentionally information-free interface
negative control in this model. It does not establish that all margin-only or
ordinary SNNs are incapable of transmitting information.

Writes are sample-triggered, not an undeclared continuous input rate. Splitting
every input sample into repeated smaller steps changes the model. Continuous
flow correctness and fixed-schedule continuation do not prove arbitrary sample
resampling invariance. Saved state restores future forward dynamics, not the
past autograd tape. See [CORE_STUDY.md](CORE_STUDY.md) for the separately executed
60-update synthetic study and its original sources/costs.

## Explicit delay alternatives

`flow_no_return` retains the same projected boundary but postpones every reset
past the T=.5 episode by setting physical delay to 1. It is a no-return-within-
observation ablation, with all unreleased probability/content still retained;
the original task-optimality statement is not transferred to this changed law.

`flow_erlang4` uses four exponential refractory stages. Its mean is .2 and
waiting-time variance is .01. It includes the same reward/discount/occupation
accumulators and supports full saved-state continuation under an identical
frozen law. This is a different delay distribution, not lossless deterministic-
delay compression. Physics payload, transition views, actual saved state,
autograd-save payload and whole-process RSS are reported separately.

## Frozen real-task protocol

The official UCI Pen-Based Recognition of Handwritten Digits data have 7,494
training records from 30 writers and 3,498 test records from 14 other writers.
The eight ordered coordinate pairs are spatially resampled, not uniformly timed
measurements. The assigned interval .05 is a model time coordinate; this study
does not establish an advantage on irregular physical timestamps. Coordinates
are mapped from [0,100] to [-1,1], and every arm receives two final zero-input
intervals. A deterministic seed-271828 sample of 75 training records per class
forms the 750-record validation set; the remaining 6,744 records train.

Primary data and attribution: E. Alpaydin and F. Alimoglu,
[UCI dataset 81, DOI 10.24432/C5MG6K](https://archive.ics.uci.edu/dataset/81/pen%2Bbased%2Brecognition%2Bof%2Bhandwritten%2Bdigits).
The original UCI distribution is CC BY 4.0. `PROTOCOL.json` records exact file
hashes. Public test data are not a prospective externally sealed custody source.

There are ten predeclared arms and three seeds (101, 211, 307): deterministic
flow, fixed boundary, mass-only message, no return within the episode, Erlang-4,
ordinary gate, GRU, CfC, recurrent LIF with subtractive reset and surrogate BP,
and a small causal Transformer. All use FP64, batch 64, Adam .003 and gradient
norm cap 1. Parameter counts are measured, not assumed identical. No arm or seed
is removed based on its result, and there is no test-driven tuning.

Each fit has at most 60 seconds for construction, optimizer initialization,
training, periodic validation, validation-original writes and in-memory
checkpoint copies. Only validation plus snapshot completed within the limit
can select a model. Imports/data setup, final publication and test/profile work
are outside that scientific training interval but included in child and campaign
costs. Late steps/validations are retained, cannot select a later model, and are
not refunded. Validation is scheduled at roughly ten-second intervals; time to
80% validation accuracy is the first observed eligible check, with non-attainment
censored. This is not an exact continuous crossing time or proof of convergence.

Fits run in a frozen randomized order, at most two fresh children concurrently,
one numerical thread per child on logical CPUs 0 and 1. These are affinity
assignments, not exclusive physical-core reservations. Each child has a 4 GiB
address-space cap and 150-second whole-process deadline; a start requires 2 GiB
MemAvailable. Local cgroup limits are unavailable and no cgroup guarantee is
claimed. Source and runtime identities are fixed before the campaign.

Every one of the 30 training children must have a successful collected terminal
and a selected checkpoint before the common evaluation seal is written as
eligible. If any fit fails, test access is refused. The seal binds checkpoint,
result, terminal cost and selected validation-original bytes. Subsequent fresh
evaluation first replays the selected validation logits, then reads the full
3,498-record test set once for that frozen model. Checkpoints, all validation
logits, full test logits, loss/gradient journals, stdout/stderr and complete
process costs are retained. An independent NumPy-only reader recomputes
selection and metrics without creating a model or calling an optimizer.

Three seeds share one test set; their variation is initialization/training
variation, not three independent datasets or 104,940 independent test cases.
Equal-time results and first-observed target cost address the two requested
budget comparisons. They do not prove adequately converged training, energy
savings, general SNN/Transformer superiority or full-modality scaling.

## Verification and bounded length profile

Before freezing this campaign, 19 same-source tests passed. They include an
independent delayed ODE, real weight/input/physics gradients, complete cold
continuation, release-before-write event ordering, all seven supported task
derivatives, coupled classifier boundary derivatives, independent Erlang ODE and
value identities, all baseline forward/backward paths, and actual zero-model
process failures that must collect a surviving owned child.

The additional frozen length profile uses one untrained source-bound model per
arm (`flow`, `flow_erlang4`), B=1, and lengths 10/20/40/80. It retains full raw
state/logits/gradients and measures forward/backward cost and approximation
differences at matching weights. No optimizer is used. Conservation must remain
within 2e-9; resource rejection is recorded rather than silently truncating
pending state. Long-sequence classification generalization is not inferred from
this numerical/state-cost profile.

Historical failed sparse bitwise gates, original C2 UNKNOWN intervals, six-fit
full replay 0/6, HPCA external custody and prior negative task results remain
unchanged. This new experiment can close its own implementation and measured
comparison questions; it cannot turn those independent open requirements green.
