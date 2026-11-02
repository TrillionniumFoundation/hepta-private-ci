# V9 AV / mechanism / cost continuation

This directory continues only v8 PR #4567 at
`059b43a0b20ad07654880c155cc49799e0bb8858`.
Read `REPORT_ZH.md` and `ACCEPTANCE.json` for final scope. Other HCSN research
branches are not interchangeable sources or evidence for these four priorities.

The original scientific adoption gates are unchanged. Historical AV development,
finite synthetic service-risk experiments and controlled process fixtures have
separate scopes. No production activation is performed.

## Restore inherited inputs

Use the commands in
`../hcsn_v8_execution_20261101/REPRODUCE.md` to restore v3 archives under
`recovered/v3` and the eight v8 raw evidence files. Both restorers verify exact
hashes. These historical assets do not restore v6 or new independent recordings.
The baseline was independently audited again without refitting; its receipt is
`baseline/V8_INDEPENDENT_AUDIT.json`.

## Runtime

The executed numerical workers use Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and
Torch 2.15.0+cpu. Torch is a task-local read-only installed runtime, distinct
from the old v8 fit runtime. See component runtime/source receipts. No claim
of cross-version numerical identity or production qualification follows.
For reproduction, use an interpreter with those dependencies, the repository
root on its import path, and one numerical thread. The published worker
CONFIG.json files retain every actual command and argument.

## Component entry points

- `frontend/README.md`: read-only prerequisite verification; expected current
  result is exit 2 / HOLD, not a successful front-end admission.
- `persistent_av/REPORT_ZH.md`: persistent GRU/SSM versus a direct-cache
  ordinary reference, actual common-head execution, original failed run,
  repaired fresh run, weights and source/input identities.
- `mechanisms/REPORT_ZH.md`: new service-risk task, separately refitted
  count-shape models, real failed READs, closed-loop and fixed-action records.
- `economics/REPORT_ZH.md`: actual capability probe and short-lived/adopted
  descendant counterexample; complete family memory and energy remain null.
- `review/REPORT_ZH.md`: independent checks of raw records and interpretations.

Every executable worker must use a new output destination. Preserve old
successful and failed directories, protocols and source snapshots. The outer
v8 `economics.worker_cost` meter can wrap these commands. Charge its enclosing
CPU once; its inner process counters are already included. None of these
receipts recovers missing pretraining, decoding or historical preparation cost.

The included source and raw artifacts are enumerated in `BUNDLE_MANIFEST.json`.
Python bytecode caches and locally reconstructed inherited bytes are excluded;
their original committed transport archives remain the recovery source.
