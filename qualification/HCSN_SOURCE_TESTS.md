# HCSN source fixture CI

`.github/workflows/hcsn-source-fixtures.yml` runs on pull requests touching its
explicit core paths or the new confirmatory Python modules, and by manual
`workflow_dispatch`. It checks the exact PR head (or dispatch commit), uses a
read-only token without persisted checkout credentials, and has a ten-minute
job limit. It is a source check, not a replacement for existing merge gates.

The runner is Ubuntu 24.04 with Python 3.12.3, CPU PyTorch 2.8.0, NumPy 2.3.5,
official `ncps` 1.0.1 and `threadpoolctl` 3.6.0. BLAS and PyTorch thread counts
are one. Direct dependencies are pinned; this is not a transitive lockfile or
a reproduction of any frozen experiment environment.

The workflow explicitly loads `finite_control_tests`, `impulse_execution_tests`,
`uniformized_flow_tests`, `fixed_delay_reference_tests`, `batched_flow_tests`,
and the confirmatory `tasks_tests`, `joint_tests`, `architecture_tests`,
`ablation_tests` and `boundary_control_tests`. Import failures, empty modules,
test failures and skipped tests fail the job. Official CfC must import before
the suite starts, so its optional-dependency fallback cannot hide an absent
baseline. Test fixtures use independent toy namespaces and fixed toy rewards.

No experiment CLI, freeze, fit, final evaluation, kernel benchmark, N256,
C2 or HPCA job is called. Results establish only the exercised numerical and
software invariants; they do not establish task accuracy or training speed.

For a local replay, install the same dependencies and run the inline Python
test block from the workflow at the repository root, with its thread settings.
Use the workflow file as the single authoritative module allowlist.
