# PLIF zero-moment diagnosis

The 3,534 zero-moment scalars are **38 identical output columns** in the recurrent
and readout matrices. Their recorded changes match AdamW weight decay exactly.
This does not establish a permanently disconnected model: frozen endpoint
replays activate 19 of those 38 channels on already prepared ABC inputs.

This addition diagnoses the retained seed-101 development pilot. It changes no
model, optimizer, sampling rule, threshold, training budget, or acceptance gate.
Scientific admission and training adequacy remain **HOLD**.

## Exact evidence and scope

The inspected S3 publication snapshot is
`dd03c0cbe08cc4dd01726ac8df5b165bc019b163`.
The original [training capsule](../hcsn-localization-trainer-20261108/hcsn-trainer-native-evidence.zip)
has SHA256 `27d4f684ba9df1b9dec5c518377c50f80239d2a3f4998045f88939593fa01bcc`.
Its `source-v1.zip` remains the executed model/trainer source. Published Python
layout was subsequently formatted; the parent's
[formatting receipt](../hcsn-localization-trainer-20261108/FORMATTING.json)
records byte differences and unchanged ASTs. This diagnosis used the original
model bytes `bb05d12c3919c1af9b4262dee8d02c7015a40c7b1bab9f173d4b36eb83478683`,
not a new training execution of the publication head.

The native read-only job `1a1bc49b8d9-138b0-16e` ran on desktop with the existing
pinned Torch/SpikingJelly environment. It made **90 frozen forward calls**:
two saved states times 45 ABC windows, or 11,520 input events. It used training
forward semantics inside `torch.no_grad()`, with fresh episode state each time.
Weights and source/input files remained unchanged. It made **0 backward calls,
0 optimizer steps, and 0 new training runs**. Post-processing job
`1a1bc4f0e17-138b0-192` loaded retained tensors and did no model forward.

[SUMMARY.json](SUMMARY.json) binds source, checkpoint, process and archive
identities. [readonly-evidence.zip](readonly-evidence.zip) retains complete
per-window/per-neuron spike counts, first-spike positions, charged-voltage
maxima, the original scripts, native launch/read/terminal receipts, optimizer
bounds, data denominators and a member manifest.

## Mechanism

The adapter computes a current from the input projection and previous **hard
spikes**, then applies the official PLIF membrane update. Both recurrent output
columns and the linear readout multiply those hard spikes. The ATan surrogate
supplies gradients to incoming weights and the membrane parameter; it does not
replace a zero presynaptic spike with a nonzero readout input.

The reset occurs once per 128-event window. There is no detach of the recurrent
spike sequence inside that loop. `detach_reset=True` applies to the membrane
reset term, not the readout or recurrent input. The nominal time constant was
2.0 initially and 1.9991264865609946 at the final checkpoint. These observations
do not establish that changing the 128-event horizon would fix the pilot.

| Retained parameter evidence | Scalars |
| --- | ---: |
| Recurrent matrix: 38 zero-moment columns times 82 rows | 3,116 |
| Readout matrix: the same 38 columns times 11 rows | 418 |
| Total changed with zero first and second moments | 3,534 |
| Scalars with positive retained second moments | 6,236 |
| Registered trainable real scalars | 9,770 |

No other entries of either output matrix have zero second moments. All input
weights, input biases, the PLIF membrane parameter and readout biases have
positive second moments. For all 3,534 zero-moment entries, multiplying their
initial values by `1 - 0.003 * 0.0001` sequentially 12 times reproduces the
final values bit for bit. Those changes are decay only.

The historical per-neuron spike trace was not saved. Historical silence of
these columns is a **mechanism inference**, with more support than zero moments
alone: seven output classes never occur in the 12 main windows. For an absent
class, the readout gradient is a sum of positive class weights, positive
softmax probabilities and nonnegative spikes, so it cannot cancel if a spike
occurs. The retained optimizer and clipping bounds put a nonzero spike's final
second moment above 1.99e-26, far above FP64 underflow. The derivation and its
assumptions are retained in `MECHANISM.json`; it is not a recorded per-step
neuron observation or a structural-disconnection claim.

## Frozen replay is separate from training history

Every cell below describes a fresh forward replay with one fixed saved state.
It does **not** report when the corresponding channel fired during an original
optimizer update.

| Fixed state | Original 12 main windows | Remaining 33 ABC windows | All 45 ABC windows |
| --- | ---: | ---: | ---: |
| Initial checkpoint: zero-moment channels that fire | 3 | 11 | 12 |
| Final checkpoint: zero-moment channels that fire | 7 | 15 | 15 |

The final-state 7 are channels `0, 3, 6, 40, 45, 70, 71`.
Across both endpoint states and all 45 windows, 19 of the 38 channels fire.
The other 19 were not observed firing at those two endpoints; their permanent
unreachability is not established. Time-varying intermediate states were not
reconstructed, and no optimizer operation was replayed.

## Actual exposure

The original 12 updates logged 1,089 spikes across
`12 * 128 * 82 = 125,952` neuron-events: **0.864615%**.
That aggregate firing rate is an original training observation. It cannot
identify which neuron fired at each update.

| Data scope | Events | Classes present |
| --- | ---: | --- |
| Original 12 main windows | 1,536 | 0, 3, 4, 6 |
| All 45 prepared ABC windows | 5,760 | 0, 3, 4, 5, 6 |
| Full ABC data used for frontend statistics | 89,216 | All 11 classes |
| Prepared D development windows | 1,920 | 0, 3, 6 |

Only five events of class 5 occur in the entire prepared ABC subset. Finishing
that subset alone therefore would not establish an adequate 11-class baseline.
The 16 diagnostic updates were restored before the main fit, and a fresh
optimizer was created; they do not supply moment evidence for the 12 main
updates. E/confirmation data was not interpreted.

## Smallest next step

No causal model implementation bug was found. Keep this pilot as an incomplete
development validation. A subsequent, separately budgeted adequacy run can use
the existing `prepare --selection all-development` route, a declared common
exposure/stop policy across arms, and class-coverage checks before interpreting
architecture differences. The present change starts no such run.

For that next run, retain per-neuron spike counts aligned with the phase,
update and pre-step model state, alongside per-parameter nonzero-gradient
counts. This is observability, not an acceptance rule requiring every scalar
to be nonzero. Existing `optimizer_step_completed` diagnostics contain the
preceding forward's spike fraction and tau; the tau field is not a fresh
post-step measurement. The final checkpoint remains the authority for final
parameters.

## Reproduction

`diagnose_readonly.py` is the byte-identical executed forward script. Its
historical absolute input/environment paths and create-only output directory
are retained intentionally. The archive also contains the executed
`postprocess.py` and the portable `inspect_denominators.py`.

To repeat the frozen forward analysis on the recorded host, copy the original
script and change only its `OUTPUT` directory to a fresh location before
running it with the Python executable recorded in `NATIVE_PROCESSES.json`.
A relocated environment must restore the original source/dependency files and
satisfy the script's source and input hash checks. Record the relocated script
identity as a new read-only run; do not overwrite the historical output or
relabel its native receipt. The script contains no loss, backward or optimizer
step and refuses to overwrite an existing output directory.

The full trace and original sources remain in the capsule. No new general
gate or model activation is introduced by this report.
