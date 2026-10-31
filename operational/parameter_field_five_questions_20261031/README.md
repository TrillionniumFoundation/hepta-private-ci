# Five-question operational checks

This directory adds engineering checks for the ordered action, label, state,
net-benefit and architecture questions. It does not replace the registered
fullstudy or amend any existing scientific completion record.

Base research commit: `c27e1b2c291dc213b4a34bb41360235013c909e0`.
Existing execution registration: `bc4e757f5c90f6365f383c1127be710d2ded874a`.

## Components

| Component | Purpose | Activation |
| --- | --- | --- |
| `finite_head_guard.py` | Reject invalid heads and nonfinite decisions before a training transition; preserve the original finite-domain choice and receipt. | Explicit context manager only. A new operational integration/freeze is required. Not active in execution06. |
| `postseal_analysis_coverage.py` | Re-enter the original source/seal gate, check B/C effect arithmetic and recorded cost coverage. | Read-only, after an actual externally pinned original postseal completion. |
| `test_finite_head_guard.py` | Synthetic overflow, normal-behavior and binding-integrity tests against exact frozen `heads.py`. | No scientific assets or Torch model loading. |
| `test_postseal_analysis_coverage.py` | Synthetic aggregate and coverage tests. | No held-out endpoint access or scientific inference. |

Read `P1_P2_NUMERIC_GUARD_REVIEW.md` and `USAGE_COVERAGE.md` for the exact
scope and prerequisites. Real execution status is recorded in
`reports/parameter_field_five_questions_20261031/EXECUTION_STATUS.zh-CN.md`.

## Scientific interpretation

The original postseal supplement already verifies bank labels against their
baseline and bound NPZ arrays. These additions do not create a second label
algorithm, change calibration, open an endpoint early, or rerun a bootstrap.

Successful synthetic tests establish engineering behavior. A cost-coverage
check cannot award efficacy, net benefit, Hepta-specific benefit, or global
optimality. A positive interaction also needs both simple effects and each
arm's costs to be interpreted; less harm is not necessarily a positive benefit.

The original B experiment is conditional on three fixed models in the same
MNIST image/caption task. Its fresh endpoint pairs and training schedules do
not provide cross-task or pretrained-model-population generalization. The C
factorial concerns the registered matched temporal cells, not the complete
production Rust Hepta neuron/DecisionCell runtime.

All additional checks consume real compute and must enter the appropriate
engineering or operational cost ledger if used. Existing failed work, missing
cost observations and negative results remain part of the evidence.
