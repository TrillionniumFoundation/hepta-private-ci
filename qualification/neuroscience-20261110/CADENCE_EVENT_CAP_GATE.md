# Hepta neuroscience seven-lineage clock raw admission — independent shadow-only gate

**Result: bounded reference clock input repaired; full scientific and production qualification HOLD_NO_GO / DENY_ALL.**

## Boundary, identity and overlap
- New isolated host worktree on the exact PR #6088 HEAD `a0875971e7b552ecfd44a1af2e7aee6b7fff96d2` (parent), no branch force-push or changes to original Owner code.
- Existing #5811, #5739, #6025–#6026, #6056, #6086 and #6088 were reviewed first; this is **not** their time credit, MEM or paired-evaluation iterator repair.
- On the same base, three forensic entrypoints already rejected raw inputs above 65,536, but the fourth seven-lineage `cadence_gate(events,...)` accepted unbounded iterators and accumulated an unbounded output list. An untrusted non-`UpdateOpportunity` also leaked Python `AttributeError` instead of a typed refusal.

## Exact local before/after
- Added `test_cadence_raw_event_budget.py` with three newly executed cases: (a) hostile 65,537-record one-shot stream that raises on item 65,538; (b) exactly 65,536 valid clock-denied records, which must remain `NO_UPDATE/DENY_ALL`; (c) wrong-type input rejected with `ContractError`.
- Original parent reference, RED: 3 tests executed, 1 passed, 1 failed and 1 errored. The excessive iterator was drained beyond the advertised budget, triggering its sentinel `AssertionError` (not a `ContractError`); wrong type raised `AttributeError`. Original failure preserved without relabeling.
- Corrected version: `enumerate(events)` rejects on item 65,537, never requests item 65,538; non-canonical event type rejected before field access. Exactly 65,536 records remain accepted without review/adoption.
- GREEN focused: 3/3 passed; GREEN complete Python shadow suite: **98/98 passed**. No original native Rust or production Owner test was rerun in this local host execution.
- Same actual ai395 host Python 3.14.4 and CPU, as captured in `CADENCE_EVENT_CAP_ENVIRONMENT.log`; RED process wall=0.10 s, user=0.08 s, RSS=45,712 KiB; GREEN focused wall=0.11 s, user=0.09 s, RSS=45,488 KiB; GREEN full wall=0.17 s, user=0.15 s, RSS=45,368 KiB. These measure tiny reference tests, not real model training, production service capacity or end-to-end learning cost.

## Fixed experiment manifest
- Model and weights: **none**. No training, inference, adoption, deployment, modification of Cell owner, or scientific benefit.
- Data: deterministic synthetic adversarial iterator and exactly-boundary event stream, no independent real tasks.
- Test generation seed: not applicable (deterministic).
- Explicit clocks: PERC=16, MEM=1, PRED=8, CTRL=4, VERIFY=8, ACT=16, LEARN=16 logical opportunities.
- Input raw upper bound: 65,536 events, with limit+1 observation only to reject overflow.
- Full raw logs: `CADENCE_EVENT_CAP_RED.log`, `CADENCE_EVENT_CAP_GREEN.log`, `CADENCE_EVENT_CAP_FULL_GREEN.log`; source/log SHA-256 in `CADENCE_EVENT_CAP_SOURCE_SHA256.txt`.

## No-go gates that remain
Owner-signed action, feedback, source and trained-weight timestamps; Q24 production candidate validation and independent NoUpdate; equal-cost actual seven-lineage training; ACT/CTRL dense/sparse delayed feedback and real terminal outcomes; MEM exact RAG and revocation over real stores; independent frozen B and C, original Agentd Adopt/NoUpdate and restart; old-task/OOD retention; multi-seed error control and Core×NDU 2×2. No simulation, syntax hash, source check or passing CI is counted as scientific efficacy.
