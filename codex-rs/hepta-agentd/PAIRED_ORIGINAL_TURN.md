# Paired verification on the original protected owner

This increment adds a read-only, in-process entry to the existing required Notes
thread owner. It does not add a socket, executable, dynamic tool, alternate
catalog or a caller-selected Core route. The original sealed thread seed and
held Session lifetime remain prerequisites of that owner.

After installing the original Notes owner, the trusted composition can call
`AgentdConfig::with_original_paired_turn_verifier`. It receives the updated
configuration and an `AgentdPairedTurnVerifier` handle. Run the actual Agentd with
that configuration; the handle cannot create or replace its owner. Capacity is
one waiting request and each request has a ten-second deadline. A full lane,
owner shutdown or expired deadline produces an error, with no reconnection or
automatic replay. A restarted owner requires a new handle from its composition.

`verify(PairedTurnRequest)` constrains the exact original turn, AuthBus delivery,
study, purpose and expected Root principal. The original task then:

1. Reads the original Core user item from its existing physical connection.
2. Resolves the admitted AuthBus message and its retained acknowledgement after
   synchronizing the replay checkpoint.
3. Uses the existing kernel-authenticated Root lane to verify the original human
   text, current owner, fixed route, permission revision and lifetime.
4. Uses Core `ReconcileOnly` to confirm the same payload in the same persisted
   original turn; it never queues another input.
5. Requires the exact `PairedLearningDataUse::consent_text(study)` bytes and the
   expected principal and delivery. A training statement cannot substitute for
   evaluation, consumer use or outcome reporting, or vice versa.
6. Rechecks current Root authorization, replay readiness and writer generation
   before returning its observation.

The returned `VerifiedPairedTurn` has private fields and implements neither
deserialization, serialization nor cloning. It records the verified request,
fixed route, permission revision, expiry and statement digest. This is an
observation at verification time; it is not durable admission, a portable grant,
an execution result or a settlement instruction. No code in this increment
consumes a data-use authorization, opens a private task, trains a model or sends
an external effect. A wrong purpose or principal does not spend the legitimate
original turn.

## Next native handoff

The native intake/consumer must be installed by the same trusted composition.
At its actual data-use boundary it must reverify through this owner, independently
bind enrollment and the frozen material, and acquire a durable exclusive record
for the original delivery and requested operation before an irreversible use.
That record must survive restart and revocation; unknown effects must reconcile
their original record. Passing copied observation fields or exporting JSON to
the legacy Python verifier cannot substitute for this handoff.

`hepta-paired-consent` remains statement-only and its legacy verification mode
still refuses with `ORIGINAL_TURN_VERIFIER_REQUIRED`. Python `owner_intake`
remains closed. Their historical receipt namespaces have not been changed.

The accompanying tests cover bounded transport, owner death, cancelled callers,
and composition of the actual original-ingress and Core-reconciliation checks
with paired purpose matching using explicit signed protocol fixtures. They do
not fabricate a `VerifiedHumanTurn`, registered person or live Root result.
Full compilation and a live original-owner integration run are separate gates;
this source increment alone does not qualify production authorization or A→B.
