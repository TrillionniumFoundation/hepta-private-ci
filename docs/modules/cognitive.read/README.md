# cognitive.read development entry point

## Reviewed source, 2026-10-01

The current audit starts from the 2026-09-30 production-convergence source
`8a2f9256102a7bf36fbab4f22152573ba8fb91ad`. The accompanying
`IMPLEMENTATION_MAP.json` binds the revised source parent and exact source blobs;
it is the authoritative identity manifest. Historical preparation runs and
earlier source-parent hashes are not execution receipts for this revision.

Detailed technical development documentation exists. Read these documents
together:

- `TECHNICAL.md`: module placement, ownership, APIs, authority, failure semantics
  and qualification. The full-scope compatibility owner API remains available.
- `CONTRACT_LIMITS.md`, `COMPATIBILITY.md` and `STRUCTURAL_REUSE.md`: compiled
  limits, canonical bytes, request-local structural reuse and construction costs.
- `SELECTED_OWNER_CUT.md`: exact-ID materialization, indexed owner witness,
  validity boundaries, startup audit and selected ancestry limits.
- `FINAL_USE_CLOSURE.md`: publication integrity and freshly reacquired final-use
  observations immediately before the native worker's physical `TurnStart`.
- `DELIVERY_EVIDENCE.md`: preparation, dispatch, acceptance, unknown outcomes and
  the persisted operation handoff still required by automatic learning.
- `CONSUMERS.md`, `CONSUMER_POLICY.json` and `CONSUMER_EXECUTION.json`: the seven
  consumers' distinct source, product and migration states.
- `QUALIFICATION_CLOSURE.md` and `OPERATIONS.md`: exact execution gates,
  measurement boundaries, operational diagnostics and external acceptance.
- `ADVERSARIAL_AUDIT_20261001.md`: reproducible findings, repairs, verification
  and the remaining completion boundary.

## Current completion boundary

| Area | Reviewed implementation state |
| --- | --- |
| Read port | Stateless, deny-all exact-ID projection; V1/V2 compatibility bytes retained. |
| Construction | Borrowed current-head selection; result count and complete V2 frame budgets precede result cloning. Whole-snapshot integrity validation retains its separate bounded cost. |
| SQLite owner | Exact-ID materialization uses the existing owner's scope witness and indexed validity boundaries. Reopen verifies witness schema and recomputed content. Derived witness identities and revisions cannot be replaced or regressed. |
| Ordinary retrieval | Agentd read, publication fence and the native worker's fresh final-use check are source composed. A check is an observation, not a future mutation lease. |
| Learning preparation | Ordinary reads receive independent identities from the existing durable ledger. Historical explicit RPC replay remains separate; the ordinary client still needs a persisted preparation-to-native-attempt handoff. |
| Compaction | The public owner API constructs an authority-free candidate. No non-test product caller or durable checkpoint publication is claimed. |
| Context compiler | Legacy product composition exists; revision-bound V2 ingress is implemented locally and has no normal provider-bound product caller. |
| Qualification | Parser/source checks, focused package execution, complete source/merge qualification, target-host evidence and independent acceptance are distinct states. See the audit for the checks actually executed. |

`productionImplementation`, `productExecutionProved`, `independentAcceptance`,
`activation` and `release` remain false. Package tests and candidate APIs cannot
elevate these independently governed states.
