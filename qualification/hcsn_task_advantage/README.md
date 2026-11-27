# Training-task continuation advantage pilot

This separate experiment leaves the frozen `hcsn_adaptive` campaign unchanged.
It asks a limited question: can a causal estimate of an actual task-loss
contrast improve one continuous boundary decision under a common frozen
encoder and readout? It does not solve the financial free boundary, a Bellman
fixed point, or global neural-network training.

## Frozen mechanism and teacher

The default task is the independently generated `future_return` dataset.
The input has a known regular 0.1-second clock. Its scalar target is mean
utility over six hidden steps after the visible window. The planning horizon
`H=4` is the last four **visible** intervals; it is separate from that target
horizon. Irregular or substituted mean clocks are rejected by this pilot.

A fixed partition uses 32 training windows to fit a common affine ridge
readout on last-step and mean flow features under `b=0`. The other 32 train
windows supply the teacher. At the predefined decision `t=T-H`, two branches
reuse the identical complete population/content/phase state and prefix
summary. One branch pulses `b=-0.25`, the other `b=+0.25`, for one interval.
Both then restore `b=0` through the remaining common training suffix. The
actual finite flow backend performs all conservative remaps. Expected events
include boundary-jump hits and events caused by the return to zero boundary.

With a readout frozen before the teacher is generated, the target is

`A = task_MSE_low - task_MSE_high - 0.01 * (events_high - events_low)`.

A train-only affine ridge critic regresses this target from the full current
probability/content/phase tensor, current causal input, prefix feature mean,
boundary and known clock fractions. Its input has no future suffix or label.
Future **training** inputs and training labels may generate teacher targets;
neither development nor final labels are used to generate teachers.

Deployment uses
`b=-0.25+0.5*sigmoid((predicted_A/train_A_std-offset)/temperature)`.
This continuous policy does not inherit endpoint-teacher optimality. Its
intermediate actions are a fitted policy hypothesis evaluated on development
data. The finite-volume remap remains piecewise differentiable. The recorded
FD/AD check concerns the continuous causal state/input-to-boundary map; it is
not an end-to-end optimization guarantee. The backend has separate derivative
and conservation qualification tests.

## Comparisons, accounting and selection

Three seeds `[11,29,47]` share the same predeclared train partition. Within a
seed all four arms use byte-identical encoder/readout weights and readout
normalizers: always-zero, fixed pulse, normalized-current-input pulse, and
task-advantage pulse. Controller parameter counts differ and are reported;
these are not equal-total-parameter comparisons. Fixed pulses use nine values
in `[-.25,.25]`; input pulses use three gains by three offsets; task pulses use
three temperatures by three offsets. Each arm includes the shared zero-boundary
NoUpdate reference. Development selects the minimum task MSE plus declared
event cost, with strict improvement required over NoUpdate.

Ridge objectives are scalar `mean MSE + lambda/N * ||non-bias weights||²`,
with train-fitted feature normalization and unpenalized bias. The readout and
critic have separate, fixed lambda values. No encoder gradient training is
performed. One backward call per seed is a paid derivative diagnostic.

Each seed has a shared 120-second operation-admission ceiling; each policy
arm has a separate common 120-second ceiling and at most nine new dev queries.
These are soft wall ceilings: an admitted operation can overrun, and its full
elapsed cost remains charged. They are not strict deadline or matched-FLOP
claims. Shared ridge fitting, paired teachers, zero reference and diagnostics
are deduplicated once per seed. Every failed candidate remains in its journal.
For standalone method costs, the paired teacher/critic work belongs to the
task-advantage arm; the zero, fixed and input controls do not require that work.
Storing the teacher in a common immutable artifact is experiment bookkeeping,
not a claim that these methods have equal training costs. Operation names and
the shared receipt retain this attribution.
Forward counts include readout/critic examples; encoder-event counts mean
sample-interval updates, not measured FLOPs. Final inference and outer process
overhead are reported separately.

Checkpoints include model/normalizers, controller, optimizer (empty for the
closed-form fit), Python/NumPy/Torch/CUDA/batch-generator RNG and a settled
cost-journal prefix. A pending unclosed operation fails closed on resume.
Every declared trial must finish or record a failure before sealing. All
selected bytes and training records are bound by the seal; one exclusive
claim precedes each final test evaluation. No training or reselection can
resume after sealing. A global coordinator must also freeze the other
campaigns before permitting their common test to open.

## Commands

Run from the repository root in the same declared Torch environment:

```bash
python -m unittest qualification.hcsn_task_advantage.task_advantage_tests -v
python -m qualification.hcsn_task_advantage.campaign freeze --config qualification/hcsn_task_advantage/formal_config.json --manifest /path/task-advantage-manifest.json
python -m qualification.hcsn_task_advantage.campaign run --manifest /path/task-advantage-manifest.json --output /path/task-advantage-results
python -m qualification.hcsn_task_advantage.campaign seal --manifest /path/task-advantage-manifest.json --output /path/task-advantage-results
```

The run and seal commands do not load final targets. Only after the global
campaign selection set is frozen, run:

```bash
python -m qualification.hcsn_task_advantage.campaign finalize --manifest /path/task-advantage-manifest.json --output /path/task-advantage-results
```

Use `run --resume` for a settled incomplete checkpoint. An interrupted final
claim is unavailable and cannot be retried. The small isolated tests use
different generated fixture data and seeds, never the formal test split.
