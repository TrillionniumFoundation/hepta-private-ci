# Conservative HCSN acceleration comparison

Post-baseline engineering comparison. Fresh synthetic episodes and model seeds; existing CREMA-D actor split is a descriptive reevaluation. No task-optimal stopping, whole-SNN, foundation-model, GPU or energy claim.

Audited jobs: 7/70. Complete: False. Primary fixed-update fidelity: False. Engineering speed gate: False.

| Family | Task | Model | n | Test accuracy | CE | Updates | Training CPU s | Whole-worker CPU s |
|---|---|---|---:|---:|---:|---:|---:|---:|
| fixed | selective_copy | two_gates | 1 | 10.84% | 2.081205 | 32.0 | 0.80 | 4.76 |
| fixed | mqar | two_gates | 1 | 13.57% | 2.079992 | 32.0 | 0.50 | 3.99 |
| fixed | mqar | transformer | 1 | 15.43% | 2.083974 | 32.0 | 0.39 | 3.88 |
| fixed | mqar | lif_snn | 1 | 12.40% | 2.081776 | 32.0 | 1.01 | 4.71 |
| fixed | cremad | two_gates | 1 | 16.67% | 1.793461 | 16.0 | 0.50 | 4.23 |
| cpu | mqar | transformer | 2 | 100.00% | 0.000002 | 2655.5 | 30.00 | 34.03 |

## Scope

- Shared-host CPU observations; wall time contention is uncontrolled.
- One common learning rate and short training do not establish each architecture's optimum.
- Classification gradients adapt physical parameters; the affine stopping reward remains a local surrogate.
- CREMA-D uses an observed actor split, offline fixed features and shared-head arithmetic late fusion.
- No measured energy, GPU cost, long-context content quality or foundation-model scaling evidence.
