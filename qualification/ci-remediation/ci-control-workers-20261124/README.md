# CI control and summary workers

The obsolete `ebe2737b4014c9b45ad995adccc53eb71e718f3d` architecture and
blocking workflows retained queued `always()` summaries after their actual
work had terminated. They required ordinary cancellation followed by one
official force-cancel each. Their original results remain in the workflow
history. The replacement architecture source lane on `ubuntu-24.04-arm`
actually started at 2026-11-24T18:39:09Z, while the replacement x64 control
jobs were still queued. This observation does not establish GitHub's queue
cause or guarantee future runner availability.

This candidate changes exactly five `runs-on` values to `ubuntu-24.04-arm`:

| Workflow | Job |
| --- | --- |
| blocking-ci | scope |
| blocking-ci | required |
| hepta-architecture-convergence | required |
| rust-ci | results |
| bazel | test-windows summary |

These jobs run checkout, Bash, Python, or dependency-result checks. Complete
parsed workflow comparisons confirm that every other value is unchanged:
required check names, `always()` conditions, dependencies, permissions,
timeouts, commands, and all native build/test matrices. No failed or
cancelled prerequisite becomes an allowed skip.

## Actual local validation

- The existing four scope, dependency, readiness, and fast-feedback unittest
  modules ran 78 tests successfully. Their original output is retained.
- Seven invocations of the unmodified `check_ci_results.py` accepted success
  and an explicitly scoped skip, and rejected an unscoped skip, failure,
  cancellation, an absent result, and empty needs.
- `just fmt` and `git diff --check` passed.
- actionlint 1.7.12 passed the blocking, architecture, and Rust workflows.
  The Bazel workflow has two pre-existing `matrix.runs_on` diagnostics at
  lines 359 and 446. Baseline and candidate output and exit code are identical;
  no suppression was added. This is not an all-workflow actionlint pass.

`receipt.json` binds the before/after workflow hashes and the observed gate
results. At preparation time the five edited jobs have not executed in
native CI. Their actual execution remains a required follow-up; the existing
Arm architecture lane does not qualify these edited jobs.

## Original run identities

- Obsolete architecture: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45445479938>
- Obsolete blocking CI: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45445480207>
- Replacement architecture: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458388978>
- Replacement blocking CI: <https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458387224>
