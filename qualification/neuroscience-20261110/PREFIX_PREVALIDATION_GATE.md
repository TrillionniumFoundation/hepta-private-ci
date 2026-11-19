# Frozen-input prevalidation — 2026-11-11

**Qualification:** SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. The change fixes an input-validation noninterference contract in a Python research comparator. It does not authenticate owner timestamps, authorize a Q24 candidate, train a model, test real tasks, or qualify production.

## Source and prior gates
- Precise immediate parent: PR #6011 `46a30d0ced27d1cd8c074b22de11bb2fe22fa534`; base tree `b96662237c4695bf7d91f6e7d169eceb007eebd0`.
- PR #6010 remains a sibling, **not** included in this branch; avoid counting its generation-review fix as merged here.
- GitHub PR #5811 HEAD was `3e17e081ed13a89526c3dadebfaf25bac00fd8d8`, main `732e934ba496d90fbe042b8d41d479ef901643e5` in this run.
- The parent `frozen_credit_view(time_aligned_credit(...))` projects away future-only output fields, but full forensic validation still raises on a future receipt targeting an unknown action or duplicating an observed digest. This makes the existence of a frozen view depend on post-cutoff validation.
- New `frozen_credit_from_prefix` selects only feedback with strictly typed, nonnegative declared availability at or before cutoff **before** calling the unchanged forensic validator; observed invalid feedback and non-integer timestamps still fail closed. The full forensic path is unchanged.

## Local execution, source and resource evidence
- HeptaRuntime authorized operator host: `ai395`, isolated materialized research directory `/home/qq/work/neuro4-turn7-prefix-prevalidation-20261111`.
- RED: `python3 -m unittest -v test_prefix_prevalidation` exits 1 with the new API absent (import error), preserved in `PREFIX_PREVALIDATION_RED.log`.
- GREEN: `python3 -m unittest discover -p 'test_*.py' -v` **61/61 PASS**, no model/owner/production calls, preserved in `PREFIX_PREVALIDATION_GREEN.log`.
- Independently repeated directly through the HeptaRuntime durable process interface: host job `1a1cc3dce98-2564-eb4`, terminal exit 0, 61/61, 0.04 s wall, 0.03 s user CPU, peak RSS 22,576 KiB, no swaps.
- SHA-256 source `study.py`: `e69b944660d33f4e681f52e4483c18f8ae62775c3ec3179d26ce14f3e1e929e4`.
- SHA-256 `README.md`: `360c3ffffdeeefb881ec9bde7bef1b9774af71dcc44deabb5e44fcde2842834f`.
- SHA-256 new test `test_prefix_prevalidation.py`: `2451d73bee42ae779ed04ad0be89c5ad5f996540a995489cb51c809c225e8009`.
- SHA-256 RED log: `9f24f4dbeea1974606e921b46edc8a2c70b4754bba70af10bbd759190a99d272`.
- SHA-256 GREEN log: `f597076f93b3cc735ac098e8be4e3fbf263e522b8f44b9a483b7bcdeb1154b3e`.

## Test contract and explicit hold
Six tests cover: same behavior as the full valid-prefix audit; future orphan receipts; future duplicate and malformed modulators; in-prefix invalid feedback rejection; bad availability type rejection; frozen output omits future forensic counters. This is a bounded, synthetic contract regression, **not** evidence of learning benefit.

**OPEN / HOLD:** original owner-attested source/action/feedback time, Q24 native production candidate, prospective independent B, NoUpdate/Adopt to different C, cold recovery, seven-lineage resource-matched training, MEM ablations and deletion, and independent Core×NDU 2×2 outcomes. Do not merge/adopt or deploy based on these tests.
