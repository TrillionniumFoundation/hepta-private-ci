# Original live Root administration

`PreparedHostAuthoritySession::enable_root_admin(&mut self)` creates one opaque
`RootAdminCapability` after the original owner/proof/physical login checks.
It creates neither a service nor an issuer, clock, registry, lease or image.
The capability contains a one-entry synchronous request sender and a weak
reference to this Prepared session's serving lifetime. It is not Clone or
deserializable and exposes no Arc, descriptor or constructor.

The original ready callback still follows the five fixed listener binds. Only
after that callback succeeds does the route become active. A scoped worker
borrows the final original service, registration and held owner pidfd; it checks
the actual Root UID, current Root boot/PID/birth/episode nonce, original owner
credentials/birth/pidfd, original physical login, registered native UI and all
original issuer/writer/human expiry bounds before and after each operation.
It becomes permanently inactive before serving returns, including unwinding;
the same capability cannot be reactivated by another retained serve call. Holding a
capability cannot extend the service or its authorization lifetime.

Requests are at most 16 KiB, schema 1, strict typed JSON with an exact expected
instance. The caller supplies the same absolute deadline used for its transport; the
one-request deadline is clamped to that deadline, the original exchange timeout
and one second. There are no retries. A timeout after a revoke is an unknown
outcome: inspect the original registry instead of resending a mutation.

The first implementation provides:

* `observe`: the complete original writer lease/revocation, registry frontier,
  original FinalUse head and, while the writer remains live, the independently
  verified physical Current. A revoked writer has no fresh Current assertion.
* `revoke_writer`: the same original registry's durable CAS revoke of its fixed
  writer, with an exact expected original revision and nonzero reason digest.
  It returns the original receipt/frontier. It does not stop a process or claim
  that one precise effect/grant was revoked. Repeating the same original
  revision/reason is idempotent; different binding/reason/version is refused.

Observation DTOs and instance metadata are selectors/evidence, never authority.
No ordinary Agentd or model wire gains access to the administrative capability.
The Desktop adapter must retain it only in the actual original Root launcher
and authenticate its separate Root-only local lane. It must connect to that
already-live instance, never open another service from paths.

Root enable also installs one bounded volatile observer on the SAME fixed
Notes admission. It mirrors only the actual SignedFinalUseGrant returned by
the original issue call; its exact JSON bytes, ID/epoch/nonce/binding/signature
are preserved. Other routes, denied issues and disabled observations add no
artifact. Capturing uses try-lock and does not block/change/retry issuance.
The ring has at most 16 slots and a 64 KiB stored-byte/slot budget; no file,
authority owner or durable grant/operation ledger is created.

`observe_issued_notes_grant` selects exact ID or latest observation attempt.
Capture failures advance a volatile attempt counter, so a lost newer capture
cannot turn an older retained item into a successful latest result. Missing,
evicted, busy or restarted observations are explicitly Unknown. Captured data
does not prove delivery/effect and is never accepted as a permission source.
An administrator may export the actual existing artifact; revocation must
independently verify its signature, own key/epoch/time, exact existing lease
and fixed Notes policy. It must not sign a replacement or trust this ring.

`revoke_original_notes_grant` accepts the actual existing SignedFinalUseGrant,
the original effect lease revision, the complete issuer-head revision and a
nonzero reason digest. The same original issuer verifies the strict canonical
signature with its own key, current epoch, canonical issued sequence and current
time. The same fixed Notes admission derives the original lease ID from the
complete binding and retained writer proof; it reads and compares the existing
lease, policy, epoch, payload, scope, principal, destination and time bounds.
Missing leases never cause creation, renewal or replacement.

The worker rechecks its full borrowed Root/owner/lifetime context immediately
before the original effect-lease CAS, then again before the original issuer's
exact complete-head CAS. The second store can fail after the first succeeds;
this remains partial/unknown, with no compensation, retry or replacement grant.
The known receipt is evidence rather than authority. A deadline failure after a
durable write remains unknown and must be resolved through original observation.

After both original CAS operations return, the worker only reads the two already
registered protected consumer frontiers. It never applies an unsigned reply head
to FinalUseAuthority or advances either frontier. Only the existing authenticated
Root observation and `synchronize_consumers` path can advance them. Both actual
frontiers must confirm the same original issuer epoch/revision while that issuer
head remains unchanged; otherwise the response explicitly says Pending within
the same cumulative deadline. Writer revoke does not qualify those semantics. Ordinary schema and
weak-lifetime tests do not qualify actual Root, login or installed product
behavior; those need the explicit same-object privileged qualification.

Each backend mutation also receives an internally constructed borrowed request
context containing the same service/config/registration/held owner/instance and
absolute end. It has no outside constructor or object/descriptor getter. Its
checks are repeated after slow reads and immediately before each original CAS.
One atomic Prepared/Serving/Closed phase prevents close/reactivate races, and
worker exit permanently closes the route even if the outer service is unwinding.

The late-owner/lifetime regression uses actual self pidfd/boot/birth reads and
real isolated original registry/issuer stores with SystemAuthorityClock. On the
old check-then-operation sequence both late checks entered both original CAS
methods and advanced the frontier/head; the corrected sequence must make zero
CAS calls and preserve the actual JSON state bytes. These negative fixtures
confer no actual-Root qualification.

Both administrative lease paths use the original registry's `revoke_before`.
It rejects a busy original state mutex rather than waiting beyond authorization,
and rechecks the same absolute end after clock reads, after obtaining state and
immediately before its original persistence boundary. Bounded issuer signature
and exact-head operations similarly try the same original request mutex. The
existing unbounded owner revoke API retains its previous semantics. Durable IO
begun while authorized may finish after the deadline; its outcome is Unknown
rather than compensated.

`observe_original_notes_grant` independently verifies the same original signed
artifact and fixed Notes policy, then reads the existing exact effect lease,
revocation and protected lease frontier. The frontier is checked before/after
the lease reads; changed observations are unavailable, never retried. It returns
the original independent issuer head and consumer synchronization observation,
so a lost revoke reply can be reconciled without repeating either mutation.
No receipt is reconstructed and no missing record is initialized.

This read-only path can identify an expired, correctly signed original artifact
within the current issuer epoch, and labels `grant_expired` explicitly. It does
not extend the Root, original owner, writer, human or issuer lifetime. Mutation
preparation always repeats strict CURRENT grant-time verification and the live
writer check; the saved cumulative end is also conservatively clamped from a
trusted-clock sample to the original signed grant's own expiry. A retained
observation/DTO can never enter a CAS as an authorization.
