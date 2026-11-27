# P0 HX first-passage F/G envelope: reproducible research patch

## Scope

This patch targets the **financial research reference** `experiments/hcsn_hx_unified_v3/hx.py` on exact parent commit `8a216c3d084680d79f2c491031e83271e1db62c5`, Git blob `b6afc3c957297ed9b37b4f0177e0343ee6607f83` (PR #4455). It does not modify SNN training, finance equations, Rust/CUDA, neural owner, permissions or CI settings.

Core defect: in the actual formula, `F` is a first-hit CDF and `G` is a discounted first-hit mass, so mathematically `0 <= G <= F <= 1` for valid inputs. The frozen binary64 witness instead gives `F=0.9999999999942438` and `G=0.9999999999942439`. The 110-dps independent mpmath reflection evaluation has `F-G=9.715164184...e-22` **positive**.

The patch introduces a common private `_first_passage_factors` numerical helper used by `bond_value`, `default_probability`, and `discounted_default_factor`, and rejects nonfinite/scalewise invalid or physically misordered F/G instead of clipping or silently accepting it. No proof of all-parameter f64 accuracy, no globally coupled He–Xiong obstacle solution, no low-precision kernel guarantee and no training superiority is claimed. Explicit refusals are not test accuracy passes.

## Files

- `p0_hx_first_passage_envelope.patch`: Git-ready patch to one existing source plus one new regression-test file.
- `test_hx_fpt_physical_envelope_repo.py`: copy of the new regression test with repository import (`.hx`).
- `hx_reproduced_slice.py`, `test_hx_fpt_physical_envelope.py`, `test_slice.py`: isolated, manually reconstructed numeric source slice and executed tests (NOT an exact clone of the upstream whole file).
- `independent_high_precision_oracle.py`: higher-precision diagnostic.
- `HCSN_P0_P5_GATE_LEDGER.md`: findings, evidence and unclosed gates.

## Local completed checks

Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0. On manually reconstructed HX F/G slice:

```sh
cd /mnt/data
python -m unittest -v hcsn_p0_hx_fpt_order.test_slice hcsn_p0_hx_fpt_order.test_hx_fpt_physical_envelope
python hcsn_p0_hx_fpt_order/independent_high_precision_oracle.py
```

Results: 6/6 unittest methods pass, 0 skipped. Seeded 20,000-input scan: 19,975 retained byte-identical accepted scalar F/G pairs, 25 explicit new ordering refusals, no inherited formula exceptions in that sample. The original formula silently accepts the frozen invalid F/G pair; this is an **isolated math/source-slice result**, not a full source-exact repository run. The patch separately passed `git apply --check` and bytewise equality verification **only on an exact-line-matched scaffold**, not against the full source checkout.

## To validate inside a real repository checkout

```sh
# Execute ONLY in a clean worktree at the frozen parent SHA or a verified byte-identical HX source.
git checkout -b review/hcsn-hx-fpt-order 8a216c3d084680d79f2c491031e83271e1db62c5
git apply --check /path/to/p0_hx_first_passage_envelope.patch
git apply /path/to/p0_hx_first_passage_envelope.patch
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_fpt_physical_envelope experiments.hcsn_hx_unified_v3.test_oracles
# Then run full relevant existing first-passage/HX numerical suites and frozen source/CI checks.
```

**GitHub state:** the named candidate branch was created, but GitHub source edits and test-file commits were blocked by the platform's safety check, so no PR exists. Do not infer that this patch is remotely merged or production-active. Do not loosen, clamp or relabel any rejection into a passing calculation.
