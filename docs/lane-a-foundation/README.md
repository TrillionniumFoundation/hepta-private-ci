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
receipt status. [`PROTOCOL_REGISTRY_V1.json`](PROTOCOL_REGISTRY_V1.json) indexes
the current Lane A executable protocol surfaces and their non-authority
boundaries. `qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json`
overrides the historical Lane A rows in the repository-wide native-source
snapshot with exact current-source blobs. `scripts/verify_lane_a_foundation.py`
validates those links and writes exact-source receipts.

## Internal blocker guards

The exact candidate additionally guards the implementation-truth defects that
would otherwise survive document-only validation:

- reference authority-witness digests bind operation, payload, generation and
  expiry, and every authorization replay revalidates the live tuple;
- acknowledged outbox state retains the owner-generation fence as well as the
  acknowledgement digest;
- incomplete or mismatched evidence migrations are documented and implemented
  as fail-closed;
- the pull-request tuple parser and the PR body use the same exact-subject
  schema version;
- the exact source receipt binds candidate HEAD/tree and the native-binding
  manifest; the manifest digest and every declared blob must match the current
  path, while its historical commit field is explicitly non-authoritative
  provenance rather than acceptance evidence.

## Closure boundary

Repository-controlled current-contract documentation, source/test traceability
and drift checks are closed only when the verifier and native qualification jobs
pass for the exact source and synthetic merge candidate.

This package deliberately does **not** claim completion of target-only
implementations, production activation, operator acceptance, promotion, release,
distributed anti-rollback, durable operations, durable AuthBus policy/quota, or
any external effect not proven by an exact-candidate receipt. Remaining
implementation and external gates are listed in
[`REMAINING_GATES.md`](REMAINING_GATES.md).
