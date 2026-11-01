# Content and baseline validation

This bounded synthetic CPU study extends the raw-input tasks and renewal gate
from #4529. Exact upstream source bytes and their commit/Git/SHA-256 identities
are recorded in `UPSTREAM.json`. The real LIF, continuous RNN, official ncps CfC,
Mamba-1 reference and PyTorch SDPA blocks come from #4159. Mamba is a serial CPU
reference, not Mamba-2 or a fused accelerator implementation.

The matrix has two tasks, three fitting seeds, two frontend-training modes and
eight dynamic cores: 96 task fits plus six common frontend donors. Donors train
only current/previous-frame reconstruction on the training split. Frozen mode
freezes this encoder; it still trains the dynamic core and new task readout.
Joint mode trains all three. The common frontend has no global attention or
symbolic key/value lookup. All models receive the same raw observations and
causal clocks. Three dual-gate families have exactly equal active parameters and
initialization; other baselines use nearest active-parameter matching, with
actual counts and gaps retained. No unused padding parameters are added.

`analytic` preserves #4529's complete finite renewal count gate with fixed drift,
noise, reset and positive refractory duration. The recurrent wrapper adds one
ordinary write head to every paired family. This is not a full financial
Call/Put neuron, an independently varying risk channel, or end-to-end optimized
He–Xiong free boundary. Its kernel runs in FP64 internally, then returns the
content dtype. The same gate/slope and a dual-head step match the original NumPy
operator, and a complete recurrent loss is independently finite-differenced.

The recall task imports #4529 raw token generation without a supplied posterior
or computed address. The binding task reuses its raw modality support, presenting
two keyed symbol/waveform pairs in random order and a delayed key query. Four
signal combinations per nuisance/order context make either missing-modality
input exactly class-balanced. This is controlled synthetic relational binding,
not natural synchronized audio/video. Paired stress domains retain source
bindings while adding delay, blank retention, clock changes or query swaps.

## Execute

Use Python with torch 2.8.0+cpu, ncps 1.0.1, NumPy and SciPy; each worker sets one
Torch thread. From the repository root, create a new output path:

```bash
python -m experiments.hcsn_validation_r12_20261031.content.validate --output /new/validation.json
python -m experiments.hcsn_validation_r12_20261031.content.study freeze --output /new/study
python -m experiments.hcsn_validation_r12_20261031.content.study worker \
  --protocol /new/study/PROTOCOL.json --job recall_s12031_donor
```

Execute the six donor jobs before their dependent fits. All job identifiers are
in `PROTOCOL.json`; a failed attempt retains `FAILED.json`, logs and existing
files, and a mechanical retry uses `--attempt 2` rather than overwriting it.
Every completed worker retains initial/selected/final parameters, optimizer and
RNG snapshots, batch indices, losses, gradients, validation selection and raw
validation predictions. Step zero is eligible and is reported when selected.

After every fit, freeze **all** candidates, then open test data:

```bash
python -m experiments.hcsn_validation_r12_20261031.content.study candidates --protocol /new/study/PROTOCOL.json
python -m experiments.hcsn_validation_r12_20261031.content.study evaluate \
  --protocol /new/study/PROTOCOL.json --job recall_s12031_joint_analytic
python -m experiments.hcsn_validation_r12_20261031.content.study profile \
  --protocol /new/study/PROTOCOL.json --job recall_s12031_joint_analytic
```

The parent study supervisor must meter every fresh process and run the final
profiles serially after other work ends. Internal training/body timing is nested
inside these receipts. Profiling reports cached raw-tensor input through the
complete encoder/core/readout and output copy; source loading and initialization
are included only in the outer process receipt. CPU seconds are not Joules.

No positive result is assumed. All seed/domain scores, step-zero selection,
counterfactual failures and parameter discrepancies must accompany any proposed
quality/cost claim. The three fitting seeds do not establish foundation-model
scaling, population AV generalization or GPU performance.
