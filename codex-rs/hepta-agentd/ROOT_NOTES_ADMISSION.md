# Root exact Notes admission

This module lets the one canonical Root signer authorize each exact Notes
payload after trusted startup registers its actual Notes target. It does not
create another signer, counter, grant provider or consumer journal. It supplies
no session choice or path field over the client wire.

## Ownership and setup

`RootNotesGrantAdmission::from_registered_notes` is Root-only and non-serializable.
It retains the original `AuthorityLeaseRegistry`, complete registered writer,
canonical issuer proof and one exact Notes policy. Its registry verifier must
belong to the same original canonical owner. The service accepts it only when
its installed registered writer has the identical proof and binding.

Trusted startup must derive the Notes target from the real Session Reserved
capability and install the matching finite text schema. An arbitrary target
string or a payload digest is not proof of that provenance. Those launcher and
actual five-lane deployment steps remain unqualified.

## Per-request flow

1. Match the complete target destination and scope. Hash the domain, original
   writer proof and complete `FinalUseBinding` into the bounded effect lease ID.
2. Outside the joint dispatch lock, install only a previously absent exact
   revision1 lease with the original Registry CAS. Read back a concurrent winner
   through that same Registry. An absent pruned ID cannot be recreated.
3. Validate the complete retained record, original writer interval and bounded
   effect lifetime. Obtain fresh opaque writer and effect tokens.
4. Under the original joint dispatch boundary, compare both full records and
   the retained writer proof, then use the original issuer lock, key, head and
   shared sequence. The final expiry is the shorter retained lifetime.

The installed Notes profile does not fall through to a Device policy on a
non-matching Notes request. Uncertain Registry/issuer I/O is never converted
into permission to sign. A known missing or changed writer record returns
`PermissionDenied`; uncertain storage retains its original error path.

## Target replacement and recovery boundary

The Root-only policy replacement uses the same original full issuer-state CAS.
Exactly one Notes slot for the registered subject must exist. Its predecessor
must match the entire expected policy. Every Objective and other policy retains
its original bytes and position, and the original signer/counter continues.
An already-installed exact successor still checks the post-I/O writer deadline.
Duplicate Notes slots fail closed without state change.

Old binding leases cannot authorize the successor target. Revoked effect or
writer leases cannot be reset, renewed or resurrected through this module.
Signer restart must reopen the retained original state and key. Cold writer
adoption, physical checkpoint material and actual Notes side-effect recovery
remain separate mandatory steps.

## Actual verification

Frozen b6a22e155 passed 56 scoped tests without retry and one real Root test using
the original protected SSD clock, Registry and canonical issuer. The regression
checks Objective2 → Notes3/4 → exact policy CAS → Objective5 → new Notes6, with
all unrelated policy bytes preserved. It covers wrong predecessor, duplicate
slot, expiry, revoked writer/effect and no lease reset. Root verified key custody
against actual UID60001 and reopening the same retained signer.

The original negative Objective composition and the first positive 55/56 error
classification failure are preserved. Scoped fix and explicit range formatting
passed after semantics; no test was repeated after that finish phase. These are
component results, with synthetic Notes identity, not full Session/Host, native
deployment, physical Prepare/Commit or crash-recovery qualification.

See [original receipts and logs](acceptance/2026-10-23-dynamic-notes-admission/README.md)
and [the Root client contract](ROOT_AUTHORITY_CLIENT.md).
