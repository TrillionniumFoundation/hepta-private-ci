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

The original staged producer now has an explicit policy-update caller:
[`root_notes_startup.rs`](src/root_notes_startup.rs) consumes the authenticated
reservation, then the same retained service enters
[`authority_host_notes_startup.rs`](src/authority_host_notes_startup.rs). Root's
existing private launch profile may declare `expected_notes_policy` with the
complete predecessor `target` and `lifetime_ms`. The actual successor is taken
only from that reservation. Both lifetimes must be between 1 and 300,000 ms and
the successor cannot exceed its predecessor. A missing declaration preserves
the previous exact-preinstalled-policy requirement; it never initializes a
missing slot. The existing issuer key, writer, human scope and original model
registration must already exist independently of this declaration.

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

The service checks its original retained writer proof before the Root-only
replacement, then uses the existing exact admission factory. The original
Agentd process identity is checked before and after this composition; Session
liveness and sealing retain their existing checks. If any later read,
admission, liveness check, seal or handoff fails, the policy CAS may already be
durable. No rollback, replacement target, new issuer or renewed lease follows.
An authorized retry checks the same actual target and lifetime under the same
live original writer. The original CAS accepts an already-retained exact
successor without writing again; it cannot establish an unobserved ACK or
revive an expired writer. A genuinely different successor needs a newly reviewed
explicit predecessor and its own actual Session reservation.

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

## Startup regression commands and scope

The added regular regressions use the existing ordinary-owner fixture and
inject a failed clock read after durable CAS or during subsequent admission.
They compare the full original issuer state and Registry frontier, retry the
same successor without a new signature/lease, and reject an expired writer.
These are component failure cuts, not an installed product or a human session.

```sh
just test --locked -p codex-hepta-agentd --lib -E 'test(root_profile_) or test(notes_policy_)'
```

The existing explicit Root test now also enters the new service caller, rejects
stale or widened policies, abandons the service before any handoff/ACK, retries
the same target and reopens the original protected issuer. It requires the
actual user-built test ELF and a new isolated Root-owned protected parent in
`HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT`. The selected parent and ELF
must be independently verified by the Root runner; no production state directory
is an acceptable fixture. Invoke that exact ELF as Root with:

```text
--exact deployment_issuer::notes::tests::deployment_notes_actual_root_clock_registry_and_canonical_issuer_issue_distinct_payloads --ignored --nocapture
```

The test creates and removes only its private `notes-exact-root-*` subtree,
uses the original protected clock/Registry/issuer, and runs the existing UID60001
read-denial child. Its Notes identities are explicitly synthetic. It neither
starts a real Session nor claims actual lost-packet, human/model or device
qualification. These new source tests remain unexecuted until the final source
is built and the named commands actually finish; the historical receipt above
does not cover the new caller.
