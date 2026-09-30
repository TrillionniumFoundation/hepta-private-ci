# control.runtime

`control.runtime` owns bounded planning, durable decision publication, exact-attempt execution state, runtime-module lifecycle admission, and the guarded organ-host profile.

## Authoritative reading order

1. `ARCHITECTURE.md` — production responsibility chain and component boundaries.
2. `API_CONTRACTS.md` — public production entry points and reference-only surfaces.
3. `SECURITY_MODEL.md` — trust boundaries, final-use checks, and residual risks.
4. `JOURNAL_FORMAT.md` — semantic journal and durable execution-store rules.
5. `OPERATIONS.md` — startup, restart, backup, recovery, and generation fencing.
6. `TEST_MATRIX.md` — exact-head, synthetic-merge, failure, and external evidence gates.
7. `IMPLEMENTATION_MAP.json` — source-object mapping.
8. `STATUS.json` — CI template; exact SHA and source digest are generated as workflow artifacts.

`TECHNICAL.md` and `docs/readiness/CONTROL_RUNTIME_EXECUTION.md` remain design background. Where wording conflicts, the production API and the files above govern the current candidate.

## Current candidate boundary

Implemented candidate capabilities include:

- semantic replay of planner journal records;
- crash-consistent append store with exact-attempt restart recovery;
- one production owner for canonical producer admission, decision durability, authority consumption, dispatch, and terminal reconciliation;
- owner-controlled monotonic time with final-use freshness checks;
- externally anchored generation fencing;
- transition-bound module promotion evidence;
- guarded synchronous acyclic OrganHost dispatch with panic containment, budgets, and per-target receipts.

The following remain external qualification gates and are not implied by source completion:

- hard preemption of a blocked in-process handler;
- HIL and physical-device qualification;
- independent security acceptance;
- activation approval;
- release approval.
