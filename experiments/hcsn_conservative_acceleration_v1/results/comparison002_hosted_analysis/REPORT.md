# Conservative HCSN acceleration comparison

Hosted engineering replication after comparison001 aborted in a shared local environment. Seven completed local jobs already evaluated heldout data. Repeat all 70 jobs under the same mathematical, objective, data-seed, optimizer, budget and gate design; report the previous cohort separately and never fill or pool the new cohort with its results. This is not fresh-test confirmation. No task-optimal stopping, whole-SNN, foundation-model, GPU or energy claim.

Audited jobs: 70/70. Complete: True. Primary fixed-update fidelity: True. Engineering speed gate: True.

| Family | Task | Model | n | Test accuracy | CE | Updates | Training CPU s | Whole-worker CPU s |
|---|---|---|---:|---:|---:|---:|---:|---:|
| fixed | selective_copy | hcsn_reference | 3 | 13.44% | 2.087591 | 32.0 | 16.44 | 23.02 |
| fixed | selective_copy | hcsn_accelerated | 3 | 13.44% | 2.087591 | 32.0 | 8.38 | 13.36 |
| fixed | selective_copy | two_gates | 3 | 12.01% | 2.080650 | 32.0 | 0.48 | 3.92 |
| fixed | selective_copy | transformer | 3 | 17.12% | 2.055940 | 32.0 | 0.28 | 3.69 |
| fixed | selective_copy | lif_snn | 3 | 12.63% | 2.081932 | 32.0 | 0.57 | 4.17 |
| fixed | mqar | hcsn_reference | 3 | 13.25% | 2.085644 | 32.0 | 16.71 | 23.43 |
| fixed | mqar | hcsn_accelerated | 3 | 13.25% | 2.085644 | 32.0 | 8.30 | 13.29 |
| fixed | mqar | two_gates | 3 | 13.15% | 2.081008 | 32.0 | 0.46 | 3.84 |
| fixed | mqar | transformer | 3 | 18.39% | 2.036171 | 32.0 | 0.28 | 3.69 |
| fixed | mqar | lif_snn | 3 | 12.60% | 2.082043 | 32.0 | 0.54 | 4.00 |
| fixed | irregular | hcsn_reference | 1 | 80.47% | 0.524647 | 16.0 | 8.38 | 15.01 |
| fixed | irregular | hcsn_accelerated | 1 | 80.47% | 0.524647 | 16.0 | 4.35 | 9.40 |
| fixed | irregular | two_gates | 1 | 89.84% | 0.234392 | 16.0 | 0.25 | 3.84 |
| fixed | irregular | transformer | 1 | 69.92% | 0.639922 | 16.0 | 0.14 | 3.53 |
| fixed | irregular | lif_snn | 1 | 84.77% | 0.425908 | 16.0 | 0.29 | 3.85 |
| fixed | cremad | hcsn_reference | 1 | 17.50% | 1.790754 | 16.0 | 9.87 | 19.42 |
| fixed | cremad | hcsn_accelerated | 1 | 17.50% | 1.790754 | 16.0 | 5.42 | 12.19 |
| fixed | cremad | two_gates | 1 | 16.67% | 1.793461 | 16.0 | 0.41 | 4.00 |
| fixed | cremad | transformer | 1 | 20.83% | 1.791399 | 16.0 | 0.19 | 3.70 |
| fixed | cremad | lif_snn | 1 | 16.67% | 1.796334 | 16.0 | 0.54 | 4.18 |
| cpu | selective_copy | hcsn_reference | 3 | 21.55% | 2.016415 | 59.0 | 30.24 | 36.90 |
| cpu | selective_copy | hcsn_accelerated | 3 | 35.29% | 1.657145 | 112.0 | 30.17 | 35.46 |
| cpu | selective_copy | two_gates | 3 | 99.06% | 0.034310 | 2016.0 | 30.01 | 33.74 |
| cpu | selective_copy | transformer | 3 | 44.73% | 1.429930 | 3368.0 | 30.00 | 33.82 |
| cpu | selective_copy | lif_snn | 3 | 13.57% | 2.088071 | 1812.0 | 30.01 | 33.63 |
| cpu | mqar | hcsn_reference | 3 | 16.60% | 2.039821 | 58.7 | 30.13 | 36.77 |
| cpu | mqar | hcsn_accelerated | 3 | 33.50% | 1.670667 | 112.0 | 30.15 | 35.34 |
| cpu | mqar | two_gates | 3 | 19.73% | 2.922528 | 2043.0 | 30.01 | 33.66 |
| cpu | mqar | transformer | 3 | 100.00% | 0.000001 | 3373.3 | 30.00 | 33.82 |
| cpu | mqar | lif_snn | 3 | 12.89% | 2.165755 | 1795.3 | 30.01 | 33.67 |

## Scope

- Shared-host CPU observations; wall time contention is uncontrolled.
- One common learning rate and short training do not establish each architecture's optimum.
- Classification gradients adapt physical parameters; the affine stopping reward remains a local surrogate.
- CREMA-D uses an observed actor split, offline fixed features and shared-head arithmetic late fusion.
- No measured energy, GPU cost, long-context content quality or foundation-model scaling evidence.
