# Lane A foundation: current implementation truth

This directory is the source-checked current-contract surface for the seven Lane A
foundation modules:

1. `platform.types`
2. `platform.wire`
3. `kernel.authority`
4. `kernel.operations`
5. `kernel.evidence`
6. `auth.authbus`
7. `secrets.heptabao`

Read [`BOUNDARY_POLICY.md`](BOUNDARY_POLICY.md) before interpreting any status.
The stable `docs/modules/*/TECHNICAL.md` guides describe target architecture and
ownership. The module documents here describe what the checked-in native source
implements at the exact candidate. Target design is never promoted into current
capability merely because it appears in a guide or execution dossier.

`MODULE_TRUTH_MATRIX.json` records six orthogonal status axes and
`CAPABILITY_EVIDENCE_MAP.json` maps every current capability to public symbols,
source anchors, positive tests, negative tests, durability, activation and
receipt status. `qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json`
overrides the historical Lane A rows in the repository-wide native-source snapshot
with exact current-source blobs. `scripts/verify_lane_a_foundation.py` validates
those links and writes exact-source receipts.

## Closure boundary

Repository-controlled current-contract documentation, source/test traceability
and drift checks are closed when the verifier and native qualification jobs pass
for the exact source and synthetic merge candidate.

This package deliberately does **not** claim completion of target-only
implementations, production activation, operator acceptance, promotion, release,
distributed anti-rollback, durable operations, durable AuthBus policy/quota, or
any external effect not proven by an exact-candidate receipt. Remaining
implementation and external gates are listed in
[`REMAINING_GATES.md`](REMAINING_GATES.md).
