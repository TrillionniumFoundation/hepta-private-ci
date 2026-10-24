# Frozen pandas5 diagnostic actions

This protocol extends the completed source qualification without changing its
immutable build protocol. The build protocol SHA256 is
`92103727ab3965afd386200d45cce636c1178ec25ac583605cd1481411af983d`.
Pandas bug5 and the pandas project remain TRAIN/development. No heldout project,
Encoder extraction, model fitting, selection or calibration is authorized here.

## Fixed source and input identities

The target is `https://github.com/pandas-dev/pandas`. The base is
`4f4282f8a7c1033fc3efe9f4eab5368a70ae5041`, tree
`0542b21d0666daab58537301aa0c2649391d4f4b`; the candidate is
`0babe10f1f3f19bb6183b6fb4cc958583c6860c8`, tree
`153f7ddd9022b6b6d33e7defd6f27d767bfa32ee`.

The original metadata patch text describes another indexes change. It remains
retained as metadata evidence; the exact Git revision pair defines the supplied
implementation change. Its actual production difference is in
`pandas/core/groupby/groupby.py`.

Under `/tmp/hepta-cell-next-20261024/pandas-pilot/prepared-actions/`:

- `inputs.json` SHA256:
  `754d1fb808c040cdc2679c1e802c8caf9177dd6c48b282803d4f172c878973df`.
- `case.json` SHA256:
  `00ad2b168674dffc8505aaee3645b3a172b7cb91a55bbfa6912358b36a4e20d1`.
- The four complete input texts are source-only, all `split=train` and all
  `action_usefulness` labels are null before this execution.

## Commands and fixed overlay

The primary command is the unchanged metadata command
`pytest pandas/tests/groupby/test_function.py::test_ops_not_as_index`.
Three comparators are existing same-file test nodes, sorted by
SHA256(`bugsinpy/pandas/5` + newline + node) before any execution.
No candidate or comparator was selected using a pass/fail result.

| Action key | Role | Literal pytest arguments |
|---|---|---|
| `773a5f7b593a4cde0615` | Comparator | `-q pandas/tests/groupby/test_function.py::test_median_empty_bins` |
| `7f12347b92eb23b26627` | Primary | `pandas/tests/groupby/test_function.py::test_ops_not_as_index` |
| `b13d6fe65f1b9db92e03` | Comparator | `-q pandas/tests/groupby/test_function.py::test_non_cython_api` |
| `be336392289c9606fef6` | Comparator | `-q pandas/tests/groupby/test_function.py::test_frame_describe_tupleindex` |

Execute in the table's action-key order, base then candidate per action: at most
eight benchmark subprocess launches. Add `--assert=plain` uniformly through
the previously qualified observer; Python assertions remain enabled. Do not
run collection separately or rerun a benchmark to choose a preferred result.

Both revisions receive the candidate's complete fixed test overlay: 1,172
original files, with complete names/bytes/SHA256 in the execution plan. Replace
the `pandas/tests` and `scripts/tests` trees before applying that overlay.
The candidate `pandas/tests/groupby/test_function.py` is 33,144 bytes, SHA256
`1fc2aba5c935356b9b9aab557ecf8317f2bd70c611824ff8d43a3c0ee97cd1ac`.
The unchanged project/conftest/setup files remain bound by each original source
inventory. No test body, fixture or assertion is rewritten.

## Runtime, native artifacts and fresh workspaces

Use the existing isolated CPython3.8.20 environment and its exact resolved hash
lock; the upstream Python3.8.3 difference remains disclosed. Its dependency
inventory, complete build reports, original source inventories and generated
extension hashes enter a separate immutable `execution-plan.json`.

Qualification history is explicit: one complete base native build, one candidate
build interrupted by the frozen free-disk guard, then controlled reuse of three
missing extensions (574,032 bytes). The accepted equality audit SHA256 is
`47e460e86c5f0d238607f8394770055dcaada17769ab8d26a77d7d92f7f5c34b`.
It verifies 1,964 identical remaining original/generated source files, including
139 native inputs, the same frozen runtime/compiler/ABI/flags, and 38 candidate
extensions already byte-identical to the base. The reuse manifest and a fresh
candidate import of all 41 extensions must qualify before execution. Preserve
the failed build's measured costs; there were not two complete independent
successful builds. No third native compiler launch is part of this recovery.

For each invocation, create one fresh workspace from the recorded original
source files, apply the fixed overlay, then copy that revision's qualified
native extensions. Validate every copied source/extension SHA256. Never copy
compiler caches or unlisted generated files, use an installed target wheel, or
run the old `git clean -ffdx` workflow over a compiled source tree.

Only one workspace and one benchmark subprocess run at a time; delete the owned
workspace after its process group is confirmed stopped. Quarantine it if owned
descendants remain. Retain original source/Git, native artifacts and all logs.
The same runtime and original artifacts are rehashed after the execution.

Use the existing phase-aware prospective observer. Per invocation: 45 seconds
wall, 40 seconds CPU, 1,610,612,736 bytes address space and 2,097,152 bytes per log
file. NumPy/BLAS/OpenMP thread limits remain one. Preserve the build-stage
750MB source/2GB runtime-and-work bounds and a 1GB free-disk reserve. A resource
preflight failure creates an unknown observation and cannot count as a test
failure. Store the exact command, environment, framework phases and return code.

## Label and failure rules

An ordinary command outcome requires at least one recorded test-call pass or
failure, no collection/setup/teardown failure, no uncaught dependency/resource
error, no timeout, and a matching child return code. Skip-only/no-test/expected
failure results remain uninformative. Any recorded skipped or expected-failure
call makes the paired label unknown. These are observed call records, not a
claim that every possible parametrization or code path was exercised.

Require the same multiset of ordinary test-call identifiers on both revisions.
Only base test-failure plus candidate pass yields `action_usefulness=1`.
Other matched pairs of ordinary pass/test-failure outcomes yield zero. Any
missing, infrastructure, uninformative or mismatched pair yields a null label.
Do not infer labels from the upstream bug designation or expected patch effect.
All eight frozen invocations are attempted independent of earlier outcomes;
resource or integrity failures remain preserved and do not authorize selection.

Freeze the execution plan only after both revision artifact qualifications are
complete. It pins this protocol, source/input/runtime/build manifests and every
execution module. Root commits the protocol/code, then supplies the exact plan
SHA to `pandas_pilot_execute.py run`. Validate those pins before and after the
run. Preserve failed attempts and their costs. Inclusive execution wall/CPU
contains nested command/setup receipts; do not add them again.

The result is at most one executed TRAIN bug group and four action labels.
It establishes neither n128 support, a second decision task, nor learning
quality. Authority stays `DENY_ALL`, and remote CI is excluded.
