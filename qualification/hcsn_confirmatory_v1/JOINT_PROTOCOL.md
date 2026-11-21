# Joint dynamics/communication comparison, stage B

Status: source written; numerical gate, training and final evaluation await root's
source/resource admission. This is a separate stage and namespace from stage A.
No old final set or stage-A final can select these weights, rates or methods.

## Question and common mask

Can an actual assistant-written semantic weight program adapt a small HCSN's
dynamics and communication, and can it improve a subsequent bounded BP run?
The common eligible tensor mask is:

- flow.encoder.drive.weight/bias: observation-to-drift dynamics.
- flow.boundary.weight/bias: observation-to-boundary dynamics.
- flow.encoder.writer.weight/bias: bounded signed-content communication.
- readout.weight/bias: task output.

The existing input-only frozen finite-population law and physical constants are
unchanged. Numeric state is the probability/content tensor; normalization is a
train-only buffer fixed at the incumbent features. Matrix-exponential preparation
is recomputed after every outer edit. There is no stale operator cache, gradient
truncation across this eight-event window, or claim of fixed-memory training.

All methods get the same public task/source semantics and training/development
access. The base checkpoint is shared: the stage-A explicit semantic encoder
prior plus a ridge readout fitted on training examples. Its feature extraction and
solve are charged. This is an already fitted small incumbent, not a foundation
model or an assertion that its initial training was free.

| Method | Actual operation |
|---|---|
| conditional_direct | Keep that outer encoder and solve its readout. This baseline is closed form only conditional on fixed nonlinear features. |
| joint_bp | Starting at the incumbent, optimize every common-mask tensor with 12 full-batch Adam steps. |
| semantic_program | Apply the saved one-shot assistant program to the common-mask tensors, with no gradient, residual, candidate search or dev callback. |
| program_then_bp | Apply exactly the same program, then the same 12-step common-mask BP budget. |

Direct has permission to the common set but only implements a readout solve; it
does not solve the nonlinear optimum and is not presented as mathematically
equivalent optimization. For each proposed candidate retain actual edited tensor
names, complete candidate/selected state hashes, dev score and failures. The
candidate is used only if it improves over the same incumbent on dev; otherwise
the selected state is exactly the incumbent (NoUpdate). The direct baseline is
marked reference. All candidates are sealed before final.

The semantic program is newly authored from the source and public task rules:
physical drift linearization for first passage, sensitivity changes for bursts,
inverse-noise sensor fusion, and filtering distractor mark channels for association.
These are testable hypotheses, not established improvements. In particular, the
finite HCSN transport and teacher dynamics are different. The programmer has not
seen formal train/dev/final results while authoring these coefficients. The exact
joint_program.py is copied to the attempt. Assistant tokens, API bill and design
time are unknown; they must be reported separately from measured local rerun cost.

## Fresh task matrix and execution

Reuse the four independent generator definitions, NOT generated arrays, from the
stage-A protocol. A distinct root-assigned namespace starts
`hcsn-joint-confirmatory-v1/` and is at least 46 characters; seed derivation
includes the full namespace, task and split. First passage is an aligned
physical-law probe; burst, asynchronous sensors and associative recall are
separate signal/memory probes. They cannot be pooled into a single universal
capability claim. Holdout clock intervals remain disjoint from train/dev.

Pilot: four tasks × three paired seeds × four methods; 24 train, 12 dev and
24 final windows per clock regime, eight events per window, width four, four
spatial bins, two refractory phases. One-to-five seeds are permitted only as
explicitly frozen staging choices. CPU FP64; one thread; deterministic algorithms.
Learning rate .005, readout ridge .001, all-mask gradient norm clipped at 1.0.
Twelve steps define a bounded engineering pilot, not a fully tuned BP frontier.

```sh
python -m qualification.hcsn_confirmatory_v1.joint freeze --manifest NEW_JOINT_FREEZE.json --namespace ROOT_ALLOCATED_NAMESPACE --seeds ROOT_ALLOCATED_SEEDS
python -m unittest qualification.hcsn_confirmatory_v1.joint_tests -v
python -m qualification.hcsn_confirmatory_v1.joint fit --manifest NEW_JOINT_FREEZE.json --output NEW_ATTEMPT
python -m qualification.hcsn_confirmatory_v1.joint final --manifest NEW_JOINT_FREEZE.json --output NEW_ATTEMPT --selection-sha256 EXACT_SELECTION_SHA256
```

The numerical gate uses only a distinct toy namespace. Gate acceptance and its
cost must be retained against the frozen source before formal fit. Fit only
materializes train/dev. Final requires an external exact selection digest and an
exclusive consumed marker. Changes require a fresh freeze/namespace. No external
data/checkpoint input or automatic retry is supported.

The common CostLedger records initialization, every proposed candidate, every
optimizer step, all feature forwards, dev queries, failures and final evaluations.
The primary receipt's cost snapshot precedes its serialization; its cost sidecar
follows serialization/checkpoint and excludes its own write, stdout and exit,
which require root's external process meter. CPU capabilities/affinity, Torch
build/parallel backend, threadpools and runtime versions are frozen and checked.
The initial ceiling is 180 wall seconds shared across fit and final, plus the
frozen work ceilings. Operation-boundary checks are not an OS hard deadline.
Host watchdog, RSS and resource-allocation receipts belong to root admission.
The few-minute target is not a measured claim. Formal completion depends on
actual successful receipts, and exhausted/missing cells remain visible.

## Statistical reading and next stages

Keep task × clock × seed pairing, all example errors and failure denominators.
Report differences against conditional_direct and joint_bp per seed. With three
independent seeds, use descriptive ranges and no p-value or superiority claim.
Do not bootstrap individual timesteps/windows as if they were independent training
runs. A new adequately powered namespace is required for confirmatory inference,
predeclared primary contrasts and multiple-comparison control.

Training time includes the common incumbent construction, program discovery
amortization, program execution, all BP and evaluation, not just weight assignment.
Neither a NoUpdate result nor an aligned-law win supports replacing multimodal
pretraining. Accurate architecture baselines (GRU, official CfC, explicitly named
linear SSM, specified LIF-SNN and causal Transformer) are an independent next
stage with matched clock/information, capacity ranges and selection budget.

