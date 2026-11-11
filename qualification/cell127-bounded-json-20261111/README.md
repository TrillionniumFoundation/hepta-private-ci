# Canonical Python JSON input for experimental Cell receipts — 2026-11-11

**Status: DRAFT / REVIEW_ONLY / HOLD_NO_GO.** This is a bounded Python
experimental interface correction, not a native authorization fix or a proof of
model benefit. It is stacked on the **unchanged** PR #5928
at parent `021ae99f060e9ce33a7c0b3dcfb94a97e22e155a`, not on the main branch.

## Exact repro

The parent `scripts/hepta_cells/component_types.py` GitHub blob is
`ffc9afc3dd2fddf1404c046cc40ba0af46d49ddb`. In `_bounded_json`, `isinstance(item, list)` accepts a
`list` subclass whose `__iter__` hides entries. The object can have
`len(value)==1` and `value[0]` present, while `json.dumps(value)` yields
`[]`; the original checker accepts it and `digest` commits to the collapsed
wire representation. Analogous dictionary and string subclass boundaries were
also accepted. This is a Python in-process value/wire consistency gap.
It does **not** demonstrate compromise of a signed production owner.

## Fix and regression

`_bounded_json` now requires exact built-in `bool`, `str`, `int`,
`float`, `list`, `dict`, or `None` and exact built-in `str` mapping
keys. It preserves the original finite-number, depth, node and byte limits
and unchanged canonical bytes for previously valid built-in JSON values.
`scripts/test_hepta_cells_bounded_json_canonical.py` tests virtual list,
mapping, value and key subclasses, built-in round trip, and original bounds.

**Original heptaruntime ai395 process** `1a1c961989a-2564-b3`:
CPython 3.14.4, standalone exact parent module and patched successor,
both evaluated against the same seven-test suite. Parent exited 1 with
**four failed tests**, successor exited 0 with **7/7 passed**, outer native job
exit 0, full terminal stdout retained by runtime. Tests ran in disposable
temporary Python packages; there was no native daemon or effectful task.
The test harness used unchanged original module bytes from GitHub and the
three exact textual substitutions published in this PR.

## Still not accepted

Required: exact-head hosted CI (including full existing Cell tests),
cross-platform compatibility, full original signed A→Training→independent
B→Selection→different NextUse→cold recovery, measured end-to-end costs,
held-out learning/retention and matched GRU/SSM/attention/CfC/HCSN comparisons.
No production model adoption, auto-splitting or mainline merge is authorized
by this patch. In particular, this does not prove subclass-free inputs in
other API boundaries; those need separate source-pinned review.
