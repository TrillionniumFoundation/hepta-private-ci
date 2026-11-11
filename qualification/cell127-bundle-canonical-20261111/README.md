# Cell 1+2+7 experimental Bundle canonical identity boundary

**Disposition: DRAFT / HOLD_NO_GO.** This scoped Python producer/qualification
change does not authorize native owners, production adoption or model efficacy.

## Exact frozen source

- Parent: [#5928](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5928)
  at head `021ae99f060e9ce33a7c0b3dcfb94a97e22e155a`, cloned with
  `--filter=blob:none --depth=1` into an isolated `ai395` working directory.
- Target: `scripts/hepta_cells/bundle.py`, baseline SHA-256
  `cde2cff0bed4d441eb6bbf0321fb1a05c543641ff31a3bf6dfc9eddd4c218e7d`.
- The existing native-compatible `Bundle.canonical_bytes` and
  `validate_local_update` are reused; no new compatibility framing or
  successor relation is introduced.

## Reproduced problem before the patch

The experimental Python helper accepted `str` subclasses with hostile
`__eq__`/`__ne__`/`__hash__`. A candidate could report an unrelated
`rollback_predecessor` on the wire while impersonating the actual current
source digest at the comparison site. The direct successor validator returned
success. Disguised component/lineage keys also bypassed the nominal field-set
comparison and produced inconsistent wire versus in-memory field names.

- Original red control: heptaruntime `ai395` durable job
  `1a1c91d0b85-135c4-3f5`, **exit 1**, four test methods, six failures,
  after fixing the test-only deepcopy fixture; no application source changed.
- Original red control deliberately failed; failures are **not** successful
  qualifications. Earlier fixture job `1a1c91c66aa-135c4-3f4` also failed,
  but its three deepcopy errors were fixture defects, not program findings.

## Scoped fix

- Require exact built-in `str` for stable IDs and digest hex before Python
  equality can impersonate a different value.
- Require exact built-in `dict` and exact string field keys for component
  and training lineage maps.
- Require exact `Bundle` and scope strings in the local successor validator.
- Preserve the native Bundle byte framing and existing valid update paths.

## Qualification and remaining gates

The following original `ai395` jobs were completed on this source stack
before the final test consolidation:

- `1a1c91e40ff-135c4-3fc`: initial four focused regressions PASS.
- `1a1c9210eaa-135c4-407`: existing Bundle 5/5 and lifecycle 20/20 PASS.
- `1a1c923f072-135c4-416`: Population owner 10/10,
  Partition identity 3/3 and temporal 3/3 PASS.
- `1a1c9231c0a-135c4-412`: Population plan 11/11 PASS;
  the subsequent owner-test import failed only because the initial sparse
  checkout omitted `scripts/hepta_pred1`. The missing dependency was restored
  in the same isolated checkout for the succeeding job above.
- Final exact-source consolidated job `1a1c9275b11-135c4-429`:
  **57/57 PASS across seven suites, zero failures**. Full original stdout/stderr
  is retained in [`final-tests.log`](final-tests.log); machine-readable suite
  counts and SHA-256 values are in [`SUMMARY.json`](SUMMARY.json).
- Environment: Python 3.14.4; disposable venv with NumPy 2.5.4 where required.

Reproduce with `PYTHONPATH=scripts .venv/bin/python -m unittest discover
-s scripts -p 'test_hepta_cells_bundle_canonical.py' -v`, plus corresponding
existing suite filenames. Retain the original red control and completed
source-bound execution receipts; `git diff --check` should be clean.

**Still open:** exact-head GitHub required checks, native Rust owner/Bundle
authority, signed independent evaluation and original StageOwner receipts,
ordinary A→Training→B→Adopt/NoUpdate→distinct C→cold recovery, held-out
PRED/VERIFY retention, real CPU/GPU/RAM/transport/recovery cost, and
pre-registered net-benefit comparisons. HCSN remains independent and not a
prerequisite. No code in this branch changes production admission.
