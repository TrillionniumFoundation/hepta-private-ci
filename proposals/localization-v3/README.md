# Temporal-core study, development stage

This is an executable continuation on the real UCI localization data. It uses
all 89,216 A/B/C training events and all 31,952 D development events, split into
the existing nonoverlapping 256-event windows. Original gaps and each final
short window are retained. E has no training, tuning or scoring entry point.

## Isolation and fair opportunity

The primary regime freezes both the deterministic normalized 25-feature input
and the same `25 -> d` projection/tanh and `d -> 11` output head. The latter two
have identical actual initial weights for a given seed, independent of how
many RNG draws each temporal-core constructor consumes. They remain frozen
throughout optimization; every epoch and final receipt verifies their hashes.
Only the temporal core learns. `--train-shared` is an explicitly separate,
secondary regime and cannot be mixed into this comparison.

The cores are PyTorch GRU, pinned official CfCCell, pinned official recurrent
PLIF, an analytic event-time LIF reference, pinned official S4D-Lin, causal
PyTorch Transformer, and existing HCSN. CfC receives actual elapsed times; the
Transformer uses cumulative elapsed time in its positional features. PLIF and
S4D remain event-indexed and receive elapsed time in the common input. This CPU
FP64 study does not qualify an optimized GPU Transformer or GPU efficiency.

Same common dimensions do not imply equal parameter count, state size or work.
Receipts separate common frozen parameters from each core, count complex
parameters as two real scalars, and retain source/dependency hashes. No padding
weights create a fictional parameter match. The declared opportunity roster
applies equal learning-rate choices, seeds, full-data exposure limits and
per-attempt wall/RSS limits. Each arm's failures remain in that roster.

The original raw-output regime also has an interface limitation: GRU, the pinned
default-mode CfC, and spike outputs are bounded, whereas S4D and HCSN include learned output amplitude
or coordinates. A fixed random common head can expose this difference. Its
results are retained as an interface diagnostic, not a fair mechanism ranking.
The next regime applies `--learn-core-adapter` to **every** arm: an identical
`Linear(d,d)` initialized to identity with zero bias. This map belongs to the
trainable temporal-core cost; the actual common frontend and final head remain
frozen. Its initial map is the identity; an added matmul can change a strided
S4D output's layout and the head's last-bit FP64 reduction order. A same-budget
memorization pilot tests this interface change before further training. This
does not prove that any class was unreachable with the original head: independent
feasibility checks found strict-argmax witnesses for all eleven classes in the
declared output domains for all three seeds. These algebraic witnesses do not
prove that each recurrent system can dynamically reach those outputs. At width
16 the common adapter contributes 272 trainable parameters per arm. With the
observed full-row-rank frozen head, the adapter makes the effective linear
classifier learnable; that readout capacity and its cost are disclosed for
every arm.

The fresh PLIF arm explicitly selects a filtered spike readout. Its complete
configuration travels in the plan and in every checkpoint payload, including
the Python-valued threshold that a bare tensor state dict does not restore.
The selected configuration is `init_tau=2`, `threshold=1`,
`input_weight_gain=1`, `readout="spike_trace"`, and `trace_decay=.75`.
The update is `trace = .75*trace + .25*spike`, with an exact discrete e-folding
time of `-1/log(.75) = 3.4760595` event steps. Four event steps is the reciprocal
injection scale, not the e-folding time. The recurrent state still consists of
actual surrogate-gradient spikes. The original binary-spike and analog-membrane
readout attempts remain separate evidence and are charged as tuning.

## Event derivative and HCSN qualification boundaries

`event_time_lif` integrates a leaky integrate-and-fire model exactly under
piecewise constant current, threshold 1 and reset 0, without refractory delay.
It analytically sums all spikes within the interval into an exponential trace;
its output is membrane plus trace. AD differentiates event times inside a fixed
event-count active set. No surrogate spike derivative is used. Grazing events
and event-count changes are nonsmooth, and this is not an implementation or
validation of the published EventProp algorithm. More than one million events
in one interval is rejected as outside the reference's declared numeric domain.
Stable `log1p` expressions avoid cancellation at large current. Tests compare
all smooth inputs' AD derivatives with finite differences, as well as direct
multi-spike summation and the no-spike limit.

Optional `--micro-batch-size` bounds the autograd working set while keeping the
declared effective batch unchanged. It retains every window's complete padded
time axis, sums class-weighted CE numerators, divides each slice by the target
weight sum over the entire effective batch, and clips/steps exactly once after
all slices. The same implementation is available to every arm. Tests compare
the full batch's independent CE loss, all learned gradients and one Adam update
against accumulated GRU and HCSN runs with nonuniform weights and padding.
Microbatch forward calls and their extra compute remain visible in the journal.

HCSN uses frozen physics, the existing probability/content network and explicit
fresh state at each training window. Its construction is not numerical
admission. Tail padding has zero duration and is passed with `observed=False`
and `valid_mask=False`; it cannot create extra observation conditioning. A
development trace records actual posteriors before optimizer steps and excludes
padding. Truncation, unsupported physics, failed physical error limits or
missing independent audit keep HCSN scientific admission at HOLD. A changed grid
requires a fresh initialization and separately bound numerical receipt.

The HCSN CLI requires `--hcsn-grid-json` with all seven `GridSpec` fields:
`active_cells`, `endpoint`, `phase_cells`, `refractory`, `tail_rate`,
`quadrature_order`, and `initial_log_std`. Missing or extra fields are rejected.
The run records the full network/operator configuration, probability and
content coefficient counts, their FP64 state payload, and per-gap matrix size.
Those payload bytes exclude autograd, parameter snapshots and temporary work;
measured peak RSS is the separate process-level memory result. A constructor
accepting a grid does not certify it. The 128/4.8 candidate failed the original
one-percent limit on a 32-gap real continuation and remains a retained negative
result. The fresh training configuration uses 256 active cells, endpoint 4.8,
16 phase cells, refractory .2, tail rate 1, quadrature order 32 and initial log
standard deviation .08. Bounded actual-posterior and finite-schedule evidence
supports investigating this configuration. Tiny-gap infinite-repeat pressure
tests still fail, including two records from the independently audited width-16
two-update probe. Passing the probe's real finite burst/long continuation
fixtures does not qualify every training state or a later trained checkpoint.

`--cache-frozen-tables` optionally reuses exactly equal frozen-physics tables
within one fit. Its key includes the complete physical tensor bytes, exact
float64 duration, grid/reward configuration, dtype/device and fixed buffers.
It performs no time rounding or interpolation, rejects differentiable physical
parameters, and clears the cache whenever a checkpoint is loaded. Each fit
starts cold. Table construction/rebuild wall time, hit/miss counts, tensor
storage bytes and process RSS remain part of the measured cost. Tests require
bitwise equality of probability/content transports, network outputs and learned
parameter gradients against the original uncached operator. Cache equality
does not establish continuous-model accuracy or a hardware performance claim.

## Training, evidence and costs

Each fit first runs a training-only memorization diagnostic, restores every
initial tensor, and creates a fresh main optimizer. The fresh plan gives every
arm at most 1,024 updates, evaluates at each 64th update, and stops at the first
observed checkpoint with accuracy at least .95 and present-class macro-F1 at
least .9. A first passing observation is not an exactly localized crossing
time. The diagnostic model and its curve are retained before restoring the
initial tensors. A complete epoch visits
every ABC event exactly once. The permutation is seeded identically across
cores. The normal plan requires at least 30 epochs, plus the declared D plateau
and successful diagnostic before reporting training adequacy. An epoch cap,
wall cap or incomplete process is not convergence. No interrupted fit is
resumed automatically; retained partial checkpoints are inspection artifacts,
not an exact-resume promise.

Epoch weighted cross entropy is aggregated by the sum of target class weights
over the whole epoch. Earlier immutable sources recorded an event-count average
of batch-normalized objectives; their original journals remain unchanged.

`campaign.py` reads a frozen JSON plan, records each subprocess's argv and full
elapsed time including import/startup, and keeps stdout/stderr and outcome even
on failure. Workers retain initial/best/last model and optimizer checkpoints,
development logits, complete update journals, source hashes, per-epoch curves,
measured CPU time and peak RSS. A source change forces a failing result and
removes adequacy credit. Same-quality time uses a predeclared D macro-F1 target;
it records the first observed complete evaluation above that target, not the
unobserved crossing between evaluations. Fresh epochs include cumulative process
wall time and CPU time, so matched-resource views can be extracted without
treating varying co-tenancy as equal execution speed. Energy and unmeasured VRAM stay
null. The Linux campaign enforces a declared address-space limit before Torch
loads, plus a subprocess wall deadline; measured RSS has a separate soft limit.

The first frozen `run-source-v1` campaign retains its original checkpoint rule:
it saves improvements larger than `plateau_delta`, so its selected checkpoint
need not be the strict development-set argmax. Its first-observed threshold
time and selected checkpoint quality must be reported separately. The next
source stage saves every strict score improvement and uses `plateau_delta`
only for the stopping counter. Historical snapshots and receipts are unchanged.

## Retained experiments and the fresh campaign

The original raw-interface campaign completed all 36 development fits
(six baseline cores, three seeds, two learning rates), with 30--40 full epochs
per fit. Independent review reproduced all 36 saved metric sets and six fresh
core forwards and verified the frozen common tensors. Only two of the 36 fits
passed that campaign's diagnostic-plus-plateau rule. This reproduces the result;
it does not turn the raw interface into a fair mechanism ranking.

The uniform-adapter pilot passed the same 256-update memorization diagnostic
for five baseline cores. Binary-output PLIF did not pass after 1,024 updates;
an eight-configuration initialization grid also produced no passing completed
trial and retained one timed-out attempt. Two fresh analog readout trials were
then run for 256 and 1,024 updates. The selected spike trace's first observed
passing checkpoint was the predeclared 768-update observation; membrane's was
the 1,024-update observation. These are training-only results on one 256-event
window, not full data convergence or independent generalization. All extra opportunities,
source snapshots, checkpoints and costs remain in the evidence ledger.

Frozen source capsule v8 and `campaign-v2-plan.json` launch 42 fresh fits:
seven cores, seeds 101/211/307, and learning rates .001/.003. The same frozen
interface, effective batch 32, 30--100 complete epochs, .002 plateau tolerance,
10-epoch patience, one CPU thread, eight-GiB address-space ceiling,
six-GiB RSS ceiling and nominal four-hour per-fit wall ceiling apply to every arm.
HCSN uses microbatch eight and starts from a cold table cache. Six HCSN fits
are dispatched first, with up to nine total simultaneous fits on the same
recorded 48-CPU host. The plan separately declares process-wall and process-CPU
quality snapshots at 300, 900 and 1,800 seconds. The live campaign is exploratory;
completion, adequate training, numerical admission and scientific benefit must
each be established from its own final receipts.

The original controller also has a 15,000-second campaign deadline. At dispatch
it sets each actual hard wall ceiling to the smaller of 14,400 seconds and the
remaining campaign time. Fits dispatched after 600 seconds therefore receive
less than four hours. The immutable original plan/source and these actual
outer receipts govern cost comparisons; the nominal ceiling must not be
reported as an identical granted budget. A matched-resource view must verify
that its selected common budget lies within each fit's actual opportunity, and
retain any earlier censoring. This limitation is not repaired retrospectively.

The campaign is a development study. Three seeds and two learning rates do not
complete the larger twelve-configuration/five-confirmation-seed protocol.
Historical data preparation, prior unknown cloud reservations and complete
physical energy are not silently counted as zero. Confirmation, full HCSN
domain admission, real multimodal tasks, physical-mechanism superiority and
production adoption remain separate gates.

## Explicit continuation after an epoch cap

Some observed baseline fits were still improving at the original 100-epoch
limit. A separate C1 phase can continue a verified, fully completed epoch-cap
attempt from its original `last.pt`; it never resumes an interrupted update.
This extension was added after observing capped runs. It keeps the same seed,
learning rate, diagnostic result, optimizer and original actual total wall
envelope (at most four hours), while adding explicitly recorded optimization
steps and process cost.
It is not retrospectively described as the original 100-epoch protocol.

`continuation_state.py` verifies the original plan, result, outer process
receipt, source, data identity and all required checkpoint hashes. It derives
the complete model configuration independently from the original plan,
including non-tensor PLIF dynamics. `continuation.py` restores model, optimizer,
Torch RNG, sample-order RNG, complete-epoch and update counters, and the plateau
anchor/stale state. It retains the inherited best checkpoint until a strict
development improvement occurs. The original source and run directories are
immutable; each continuation uses a new frozen source and output directory.

The native C1 controller waits until the original 36 baseline attempts
are terminal and admits only their complete epoch-cap results. It permits at
most three continuation workers, with at most 400 cumulative epochs. Each
worker receives its original actual wall ceiling minus the parent's complete
outer wall time, the original 8-GiB address-space limit, and the original 6-GiB RSS
limit. Imports, cold caches, all new evaluations and failed continuations count
toward costs. The original nine-worker campaign itself has no separate baseline
semaphore: six HCSN fits are first in its roster, so the initial baseline
concurrency is three, but it may grow when HCSN workers terminate.

The delivery capsule passes the existing 13 core tests and 11 continuation
tests. Five cores compare split and uninterrupted training with exact full
model/configuration, optimizer and RNG-state equality on synthetic fixtures;
tampering, missing or partial evidence and exhausted parent budgets fail closed.
This validates continuation implementation and packaging. It does not grant
training adequacy, numerical-domain admission or scientific benefit.

The parent's final fit CPU counter excludes imports. C1 reports its own full
process CPU separately; an exact cumulative full-process CPU cost must not be
invented by summing incompatible counters. Independent review must bind both
phases, all three seeds, every attempted learning rate, failures and separately
measured setup/tuning/qualification costs before drawing matched-resource or
resource-to-quality conclusions.
