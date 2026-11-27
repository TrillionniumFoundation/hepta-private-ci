# Canonical stable-ID and digest negative control — Cell 1+2+7

**Disposition: DRAFT / HOLD_NO_GO.** This addresses the experimental Python contract only; it does not establish native Rust owner authentication or model efficacy.

## Reproduced before the fix

- Original parent: `05d8104df8d5b22d99eac12e418eee88eed13cfd` (Draft #5922), checked out in an isolated heptaruntime `ai395` directory.
- One negative-control module was added without modifying the original implementation. On that parent, three unittest methods produced **10 failing subtests** (exit 1) after `__reduce_ex__` preserved the forged string across dataclass deepcopy.
- Malicious `str` subclasses overrode equality/hash while retaining different wire values. They were accepted as principal/agent/Cell/run IDs, `ComponentIdentity` values, and SHA-256-like digests whose actual value was 64 zero characters.
- Original red job: `1a1c902de57-135c4-372`; local source log `/tmp/hepta-cell127-partition-a11/red-canonical.log`.

## Fix and green evidence

- `scripts/hepta_cells/component_types.py`: `_token` and `_hex` now require exact builtin `str` before regex/equality.
- Tested component implementation SHA-256: `a0e3b4568f75911fa1db606b3e684b730c54d29d0273c820fb76088229b4cecf`.
- Tested new regression module SHA-256: `9507c16b813217592ff68e6be883fb8db2ecfddb32fd5b31c4b4d0dd8f3233c6`.
- Same isolated source, only these two files changed: **new canonical tests 3/3 PASS**, **original Population Plan tests 11/11 PASS**, **Population Owner tests 10/10 PASS**, including cold-process recovery.
- Original green/cold-recovery job: `1a1c90c6679-135c4-3a7` (exit 0); Python 3.14.4, NumPy 2.5.4 in a disposable venv. Python compilation and `git diff --check` also passed.
- One earlier owner-test attempt failed because its subprocess replaced `PYTHONPATH` and could not import NumPy; it is not counted as a success.
- Uploaded source and test bytes were compared exactly against the host-tested contents.

## Reproduction

```bash
python3 -m unittest discover -s scripts -p test_hepta_cells_partition_identity_canonical.py -v
python3 -m unittest discover -s scripts -p test_hepta_cells_population_plan.py -v
# Requires NumPy in the actual Python interpreter for the cold subprocess:
python3 -m unittest discover -s scripts -p test_hepta_cells_population_owner.py -v
```

## Remaining gates

GitHub exact-head required CI, native original Bundle/CellStatePartition authority, signed independent Evaluation, actual A→Training→B→Adopt/NoUpdate→distinct C→cold recovery, PRED/VERIFY held-out retention and full CPU/GPU/RAM/transport/recovery cost are **not established by this patch**. HCSN remains an independent numerical research candidate, not a prerequisite. No production activation, safety test bypass, or model benefit claim.
