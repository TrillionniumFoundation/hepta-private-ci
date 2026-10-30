# Conservative acceleration of the HCSN distributional model

This continuation addresses a measured computational bottleneck in the existing
HCSN content model. It preserves the registered finite probability/event
operator while changing its evaluation order and explicitly enabling the
already-audited conservative probability profile in the whole network.

The motivating experiment is not evidence of a broad architecture advantage:
the completed content002 matrix and its independent follow-up reported no
registered mechanism or content win. Increasing the number of experiments
without improving the cost/quality tradeoff would not close that gap.

## Deliverables

| File | Role |
| --- | --- |
| `CONTRACT.md` | Probability/value/first-event/count definitions; oracle and trained-model distinction; reset, refractory and execution semantics |
| `SOURCE_BASELINE.json` | Exact parent source identities and remote publication parent |
| `kernel.py` | Positive-coefficient augmented Poisson polynomial backend |
| `validation.py`, `kernel_tests.py` | Independent dense exponential, physical generator, gradient and long-stream checks |
| `model.py`, `model_tests.py` | Drop-in whole-model reference/accelerated and raw/stable profiles |
| `runtime.py`, `runtime_tests.py` | Persistent streaming, restoration, real native KEEP/STOP execution and whole-model measurements |
| `PROTOCOL.json`, `study.py`, `analyze.py` | Source-bound training registration, paired experiments, retained evidence and independent metric recomputation |

The original packages are dependencies and remain unchanged. This package adds
no fitted parameter to an HCSN reference/accelerated pair. Its two numerical
backends must satisfy the fixed-update fidelity gate before their speed is
interpreted as acceleration of the same trained computation.

## Registered comparison

The primary design contains selective copy and MQAR, three fresh seeds, five
models, and both fixed-update and fixed-training-CPU families: 60 jobs. Ten
descriptive fixed-update jobs add irregular timing and existing actor-disjoint
CREMA-D audio/video features. Controls are the existing parameter-matched
ordinary two-gate network, Transformer and LIF SNN. One common learning rate is
fixed before training; this short engineering comparison is not a replacement
for the previously completed tuned architecture matrix.

The runner retains every selected and losing checkpoint, validation and test
logits, minibatch hash prefix, parameter-group gradient, initial-state identity,
access chronology, CPU receipt, and failure. It never reads test arrays before
a validation selection is durable. Fixed training CPU and full worker CPU are
reported separately. The small number of fresh seeds permits descriptive
paired estimates, not confirmatory superiority or equivalence claims.

## Reproduction order

Use Python 3 with NumPy, SciPy and CPU PyTorch. The implementation was exercised
with PyTorch 2.8.0+cpu and one numerical thread per worker. Run the relevant
`*_tests` modules and the independent validation first, then the train-only
preflight. Register only after all participating source bytes are final. A
public source/protocol commit is required by the formal runner before launch.
The registered output records the exact commands and all source/data hashes.

Keep frozen registrations and failed attempts. Changes to source, objective,
tolerance, budgets or selection policy require a new registration; successful
later audits never overwrite an earlier failure.

## Interpretation

The local boundary remains the boundary of an affine regenerative surrogate.
Joint cross-entropy gradients do not make it the optimal classification QVI
boundary. The dual channels remain its own-policy value and intervention value,
not literal financial Call and Put prices. No GPU or energy measurements are
available on this host, and expected counts are not physical energy readings.
See `CONTRACT.md` for the exact distinction between these objects.
