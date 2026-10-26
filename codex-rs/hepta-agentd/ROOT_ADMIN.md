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
It becomes inactive before serving returns, including unwinding. Holding a
capability cannot extend the service or its authorization lifetime.

Requests are at most 16 KiB, schema 1, strict typed JSON with an exact expected
instance. The one-request deadline is at most the original exchange timeout
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

Precise signed Notes effect/FinalUse revoke and confirmation through the
original authenticated observation/consumer synchronization are the next
stage. Writer revoke does not qualify those semantics. Ordinary schema and
weak-lifetime tests do not qualify actual Root, login or installed product
behavior; those need the explicit same-object privileged qualification.
