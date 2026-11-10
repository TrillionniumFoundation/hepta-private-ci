# HPCA-MEM reference identity namespace correction — 2026-11-10

**Verdict: reference-selector regression fixed; scientific and production `HOLD_NO_GO`.**
This is an isolated stacked change on [#5832](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5832), pinned to parent `51a6b83cfd60785614133800718c75d9d2c39db0`. Neither #5739's original 16-seed microqualification nor existing FP64 development fits were rerun.

## Concrete defect

An event with no explicit `logical_id` is supposed to be a distinct implicit object keyed by `event_id`. The old selector grouped it by `e.logical_id or e.event_id`, allowing an unrelated tombstone with an *explicit* `logical_id` equal to that event ID to erase the implicit record. Matching text was silently treated as proof of matching object identity. This caused a false negative for exact-key, uniform and stratified retrieval, without proving that any production owner permitted such an erase.

The reference selector now groups by a **tagged identity pair**, `("logical", logical_id)` versus `("event", event_id)`. Explicit revisions with one registered logical ID still consolidate; tombstones and revocations still deny older/later versions of that logical object. A bare matching query key remains insufficient to join objects.

## Exact reproducibility and original local evidence

- Frozen parent source: `51a6b83cfd60785614133800718c75d9d2c39db0`; pre-change study Git blob `9effb949537966042a69e944be9e4adc2c8d8a0e`; test blob `ef760c7639274b75640232e9546ff57fa3089903`.
- On the ROG operator host, the added case against **unmodified parent selector** failed for all three policies (expected red): durable job `1a1c6fbbb92-5074-2d7`, underlying Python unittest `exit=1`; the outer diagnostic wrapper exited 0 because it verified the expected failure. No baseline tests or source artifacts were overwritten.
- The exact patched study+test bytes passed **23/23** Python 3.14.4 unittests, including all existing 22 and the new three-subtest case; durable job `1a1c6f8979c-5074-2cc`, `exit=0`, 0.046551 s child wall time and 23,088 KiB child peak RSS (Linux `ru_maxrss`). stdout/stderr recorded by heptaruntime.
- Patched file SHA-256 observed by the green host job: `study.py` = `17be26e57baf4eaf8524966f4e5e88b2a136ed6ab0beb7c56eedd48adaff609e`; `test_study.py` = `77320ac1e2d0c2d00fd0da8fc77e0ad4569d305876e07039c5c14e1a2390a150`. Only these two Python files were copied into the temporary isolated test directory.
- Test input: three explicitly constructed `MemoryRecord` values (`keep`, `delete`, `other`); fixed selector seed `fixed`; policies `exact`, `uniform`, `stratified`; `now_sequence=5`, `max_items=10`. There is **no trained model**, no real-world dataset, no independent scientific seed, no API effects, and no production owner input.

## Limits and unclosed gates

This verifies only a **local, self-declared identity contract** and is not source/signer attestation, deletion against durable production stores, rollback safety, independent evaluation or measurable neural value. A malicious source might lie about either string identity; an external owner authority must independently bind scope and object identity. No timestamps beyond a synthetic logical sequence, full-service CPU/energy/network costs, operator-recovery receipts or baseline task utility were measured. All actual-model, train A → independent B → signed NoUpdate/Adopt → distinct task C → cold recovery, old-task/OOD, NDU 2×2 and full-cost prospective outcome gates remain **HOLD_NO_GO / DENY_ALL**. No selected weights, owner capability, adoption state or deployment were changed.

CI for this PR must be separately inspected at the final remote HEAD before claiming a hosted pass.
