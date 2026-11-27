# Cell 1+2+7 population contract — retained engineering evidence

## Result and scope

The existing shared semantic and GRU/diagonal producers now have an optional,
persisted seven-lineage population policy in the existing experimental SQLite
owner. The reference allocation opens MEM private-head and PRED recurrent/head
updates; other instances remain frozen. The policy caps logical plastic update
points, validates actual component families, retains exact budgets and rule
identities, and enforces observation cadence when adopting a version.

**70 tests passed, 0 failures, 0 errors and 0 skips** on clean frozen source
`d1dc9dfdd30aafa708fa15ed0bd44be7fa87b683`. Of these, 18 cover population schema and
owner integration and 3 cover the new temporal numerical audit. The other 49
exercise inherited shared serving, semantic training, temporal state, bundles,
replay, recovery, limits and deterministic components.

This is an engineering implementation and numerical diagnostic. It does not
establish seven learned competencies, general multimodal quality, independent
task improvement, native daemon adoption or RSI. The LEARN numerical fixture
computes evaluation summaries; it is not a complete training coordinator.

## Exact sources

| Cut | Commit | Meaning |
| --- | --- | --- |
| Parent | `a8df34d5da7562a9e54905b95d7487816c991039` | PR #5626, one common-framework source; no branch-history amalgamation |
| Schema | `a331a8fe0` | Frozen seven-lineage plan and bounded logical instances |
| Owner integration | `58d4112c9` | Retained adoption policy, transactional cadence and logical fences |
| Numerical audit | `66e2e7edf` | Actual post-training BPTT and checkpoint/optimizer checks |
| Tested source | `d1dc9dfdd30aafa708fa15ed0bd44be7fa87b683` | Includes fresh-process next-task recovery test; clean before and after execution |
| Formatted source | `5dec927e912ea3017a80783e006a72a0cc5a348b` | Repository `just fmt`; all Python normalized ASTs identical |

`final-tests/protocol.json` retains every selected Python source SHA256 and
normalized AST digest before the final suite. `final-tests/result.json` and
`final-tests/tests.log` retain the complete test names and original output.
`format-verification.json` maps the tested source bytes to the final formatted
bytes. The formatting check returned 0. Tests were not repeated after formatting,
following the repository's AGENTS.md; hosted CI on the final branch is a separate
observation. No Rust source or workflow was changed by this implementation.

The initial 60-test run is also retained in `initial-60-tests.log`; it preceded
the new owner integration cases and is not the final suite count.

## Runtime behaviors actually exercised

- Plans contain all seven responsibilities, distinct logical Cell IDs, an
  explicit family/kernel, initial identity, local objective, frozen update and
  evaluation profile identities, and per-run budgets. Default cap is two plastic
  logical Cells; this initial schema permits at most three.
- Reopening the raw owner without a supplied plan retains the original plan.
  A different plan, absent admission rows or missing original policy is refused.
  Existing unplanned databases remain supported; silently installing a policy
  over their already admitted cells is refused.
- Actual semantic private-head and GRU parameter updates are adopted only from
  the current source, with an immediate successor bundle and permitted component
  changes. The host qualification callback remains required.
- Replayed receipts, temporal prediction, over-budget results and lifecycle
  operations cannot manufacture committed observations. Observation consumption,
  owner state transition and logical version advancement commit atomically.
- Independent review reproduced an A-to-B-to-A bug during development. The fixed
  implementation increments a monotonic logical epoch on both adoption and
  rollback. An old A run cannot adopt after rollback restores A, and its old
  epoch observations cannot satisfy a fresh run's cadence.
- Injected SQLite history failure and exhausted owner capacity leave the current
  logical version and consumed observations unchanged. Rollback retains actual
  work expenditure and consumed evidence.
- A separate Python process restores an actual adopted GRU checkpoint, reads the
  retained population without a supplied plan, starts a new run at the current
  logical epoch and consumes a fresh observation. The old run's hidden state is
  restored accurately but is not reused in the new task.

The policy governs adoption, not arbitrary trainer calls outside the owner. A
digest of a declared optimizer rule does not prove that optimizer execution
occurred. Real source custody, truthful costs and independent evaluation remain
host duties; the permissive evaluator in refusal tests is an intentional negative
control, not a scientific evaluator.

## Numerical diagnostic

`temporal-reference/result.json` retains four actual post-training configurations
using the unchanged PRED-1 forward/backward/Adam implementation: GRU and diagonal
recurrence, seeds 41 and 67, hidden width 4, eight five-event episodes and four
initial updates. Each case also executes two independent one-update continuation
paths to compare resumed optimizer behavior. Parameter counts differ, so equal
update counts are not equal parameter or compute budgets.

| Kernel | Seed | Coordinates checked | Maximum absolute derivative error |
| --- | ---: | ---: | ---: |
| GRU | 41 | 134 | 8.2143e-11 |
| Diagonal recurrence | 41 | 58 | 1.0796e-10 |
| GRU | 67 | 134 | 1.1002e-10 |
| Diagonal recurrence | 67 | 58 | 1.0765e-10 |

All **384 coordinates** satisfy the retained finite-difference tolerances. This
does not mean every coordinate has a nonzero gradient: each GRU has 130 nonzero
analytic derivatives in this diagnostic. Maximum streamed-versus-batched error is
`1.1102230246251565e-16`; checkpoint state, subsequent continuation and the resumed
next Adam update agree exactly in all four cases. Parent state is unchanged.

The four NPZ files are actual immutable checkpoints, with SHA256 values retained
in the original report. Independent review verified all four checkpoint hashes
and the four original numerical-source hashes. The report source is the numerical
implementation before formatting; the exact bytes are present at the tested cut.
The protocol hash establishes content identity, not independent preregistration.
The deliberate wrong-gradient test is rejected; no HCSN fit is launched or counted.

## Reproduce

```sh
git checkout d1dc9dfdd30aafa708fa15ed0bd44be7fa87b683
python3 -m pip install -r scripts/hepta_cells/requirements.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python3 -m unittest discover -s scripts -p 'test_hepta_cells_*.py' -v
```

To reproduce the four numerical configurations into a new directory:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=scripts python3 - <<'PY'
import json
from pathlib import Path
from hepta_cells.temporal_qualification import run_temporal_reference_probe

output = Path('new-cell-temporal-reference')
output.mkdir(exist_ok=False)
result = run_temporal_reference_probe(output)
(output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
assert result['passed']
PY
```

Existing stem-cell workflows already discover these `test_hepta_cells_*.py`
modules. The common native-framework workflow names a smaller explicit Python
subset; its success alone would not establish this new population coverage.

## Remaining acceptance boundaries

Ordinary native daemon assembly, original external effect/evaluation custody,
cross-version hidden-state migration, authenticated training/adoption, independent
real-task gain, negative-transfer-driven specialization and complete shared
serving costs remain separate work. HCSN remains a research candidate. This PR
does not promote a synthetic numerical result to a production or RSI gate.

`SUMMARY.json` records the local delivery observation; its whole-CI field is false
because no complete required-check pass had been observed when this evidence was
written. Later GitHub Actions results must be read from the exact current head.
