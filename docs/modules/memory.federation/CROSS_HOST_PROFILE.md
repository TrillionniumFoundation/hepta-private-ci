# memory.federation authenticated cross-host profile

**Profile:** `hepta.memory-federation.cross-host.v1`
**Status:** `specified_not_implemented`
**Owning work package:** `ASM-4-FEDERATED-ORGAN-ENROLLMENT`
**Authoritative owner:** `runtime.fleet` / `fleet-runtime`
**Co-owners:** `memory.federation`, `kernel.authority`
**Qualification class:** `physical`

This profile is the implementation contract for carrying the existing read-only
`memory.federation` V2 semantics across a process or host boundary. It does not
activate a network service, enroll a host, issue a credential, select a transport,
or turn the current in-process Rust structs into a wire protocol by convention.
The current product path remains the local, read-only owner-store composition.

## 1. Ownership and authority boundaries

`runtime.fleet` owns explicit host enrollment, host lifecycle, quarantine,
retirement, host-scoped leases and the mapping from an authenticated physical peer
to a registered Agent/owner generation. `kernel.authority` owns admission of the
operation-bound authority and current revocation view. `memory.federation` owns
only the bounded read/query/result semantics after those inputs are authenticated.

The profile must not add any of the following to `memory.federation`:

- a second peer or host registry;
- private-key, certificate or credential storage;
- host enrollment or lease issuance;
- remote mutation, write forwarding or training consent;
- an internal retry queue or fallback to the legacy federation path;
- self-authentication of a response by its own digest.

The allowed implementation roots remain those declared by
`ASM-4-FEDERATED-ORGAN-ENROLLMENT`, including
`codex-rs/hepta-fleet/src/assimilation/**` and
`codex-rs/hepta-memory-federation/src/assimilation/**`. Any broader owner change
requires its own work package and review.

## 2. Required existing primitives

The profile consumes, rather than replaces, the existing repository primitives:

- `hepta-wire` V2 framing, version negotiation and `SchemaRegistry` admission;
- `hepta-authbus::SignedMessage` plus trusted `IssuerRegistration`, key epoch,
  expiry, replay fields and live revocation;
- `hepta-contracts::IdentityBinding` for node/service/Agent identity, process
  generation, owner epoch, launch nonce, audience, operation and fencing token;
- the current `FederatedQueryV2`, `FederatedLeaseV2`,
  `RemoteFederatedResponseV2` and result validation semantics;
- an independently authenticated owner-cut witness supplied by the owning memory
  host. The local exact-scope revision count is not that witness.

`WireEnvelopeV2.frame_digest` is an integrity digest, not a MAC, signature or peer
identity proof. A frame is not admissible until the signed message, enrolled peer,
lease and identity binding have all been independently checked.

## 3. Negotiation and registered schemas

A cross-host session must negotiate `WireVersion::V2` and require all of:

```text
METADATA_BOUND_DIGEST | SCHEMA_ADMISSION | STREAM_DECODING
```

No downgrade to V1 is permitted for this profile. The following stable schema
identities must be registered before a payload is decoded:

```text
hepta.memory-federation.cross-host.query.v1
hepta.memory-federation.cross-host.response.v1
hepta.memory-federation.cross-host.cancel.v1
hepta.memory-federation.cross-host.cancel-receipt.v1
```

Each schema has an explicit byte limit no greater than the repository wire limit.
Unknown schemas, unknown critical fields, duplicate fields, unsupported versions,
non-canonical encodings and over-limit payloads reject before domain decoding.

## 4. Authenticated request binding

The canonical query payload must bind at least:

- profile and schema version;
- exact enrolled source host, source Agent/owner and consumer Agent identities;
- fleet enrollment identity, host lifecycle generation and host-lease identity;
- host-lease epoch, operation, effective time, expiry and fencing digest;
- exact `FederatedQueryV2` fields and `query_binding_digest`;
- capability identity, generation, revision, scope and consumer-workspace digest;
- purpose, request payload digest, query nonce and absolute deadline;
- expected owner epoch and the required owner-cut witness profile;
- AuthBus issuer, key epoch, message identity, sequence and expiry through the
  enclosing signed claims.

The trusted host reconstructs the expected scope and payload digests locally. A
caller-provided digest is not accepted as the expected value. Enrollment, issuer,
identity binding, host lease, capability authority and deadline are all checked
before a physical request is dispatched.

## 5. Authenticated response binding

A successful terminal response must bind at least:

- the exact request/query binding and message identity;
- enrolled source host, source Agent/owner and current host lifecycle generation;
- current owner epoch and fencing digest;
- canonical owner-cut witness profile and witness digest;
- exact source frontier/cut represented by that witness;
- the complete `RemoteFederatedResponseV2` semantic payload;
- response completeness, terminal observation and effective expiry;
- the responding issuer/key epoch and signed payload digest.

The receiver verifies the response signature and live issuer registration, the
fleet enrollment and host lease, peer identity, owner epoch/fence, query binding,
cut witness, V2 response digest and post-I/O capability authority before exposing
any item. A response digest alone proves none of the external identities.

## 6. One-attempt and retry semantics

One admitted query nonce authorizes exactly one transport attempt. Cancellation or
deadline drops the in-flight attempt and cannot imply that the remote side did not
execute. No automatic retry occurs. A separately authorized retry requires a new
message identity, sequence, query nonce and attempt identity while retaining the
same logical request lineage.

Unknown delivery or response state remains explicit indeterminate coverage. It is
never converted into a successful empty result. The product caller may degrade to
its declared local-only result with failed remote coverage; it may not silently
reuse cached remote evidence or the legacy federation path.

## 7. Revocation, recovery and non-resurrection

Admission and final use must each observe current state for:

- Fleet enrollment and host lifecycle;
- host-scoped lease and fencing epoch;
- AuthBus issuer/key registration and replay frontier;
- capability grant/revocation/generation;
- owner generation and authenticated owner-cut witness;
- response and query expiry.

Writable owner recovery, host replacement, retirement, quarantine, key rotation,
owner-epoch advancement or lease revocation fences predecessor responses. A
predecessor host, old credential, old owner cut or retained response cannot become
current again after restart or rollback. Recovery of local memory state does not
restore a retired remote enrollment.

## 8. Resource and privacy requirements

The current local bounds remain semantic ceilings, not a cross-host SLO:

- at most 16 admitted peer slots per product request;
- at most 512 evidence identities per canonical peer result;
- no unbounded queue, retry loop or per-peer timeout multiplication;
- deterministic ordering and explicit omitted/truncated/failed coverage.

The selected deployment profile must publish measured connect, authentication,
first-byte, total, cancellation and overload budgets. Credentials, signatures,
private keys, raw certificates, memory contents and denied-record existence do not
enter general logs. Operational events use stable IDs or digests and distinguish
unavailable, timed-out, rejected, revoked, stale-generation, integrity and
transport failures.

## 9. Required two-host fault matrix

Physical qualification uses two independently running enrolled hosts and covers at
least the following cases:

| Case | Required result |
| --- | --- |
| Valid enrolled read | Authenticated response is query-, lease-, peer-, owner-cut- and expiry-bound. |
| Unknown or retired host | Reject before dispatch; no implicit enrollment or fallback. |
| Wrong physical peer / identity binding | Reject even if the payload and frame digest are otherwise valid. |
| Revoked or rotated issuer/key | Reject the predecessor key and accept only a current registered epoch. |
| Replayed request/message sequence | Reject without a second read or attachment. |
| Host lease expiry or fence advance | Reject predecessor traffic before dispatch and at final use. |
| Owner recovery / owner epoch advance | Reject old host responses, old cuts and prepared attachments. |
| Query/response field tamper | Signature, schema, payload or V2 digest validation rejects. |
| Version/capability downgrade | Negotiation fails closed; V1 is never selected for this profile. |
| Partition before dispatch | Explicit unavailable/timed-out coverage; no remote execution assumption. |
| Response loss after remote execution | Indeterminate; no blind replay under the original nonce. |
| Cancellation in flight | No attachment; terminal attribution is retained when observable. |
| Quarantine/drain/retire | New reads stop, in-flight state reconciles, evidence remains interpretable. |
| Overload / peer cap | Bounds hold and healthy peers remain isolated from the failing peer. |
| Restart with old enrollment snapshot | No resurrection of retired host, key, lease, epoch or cut. |

Tests must run against exact source and the current-main deterministic merge
candidate, record both host identities/generations and preserve transport and
resource measurements. In-process fixtures do not satisfy this matrix.

## 10. Rollback and activation

Rollback disables the cross-host profile and retires/quarantines its host leases;
it may leave the current local read-only federation profile available. Rollback
must not reinterpret cross-host failure as a successful empty read, restore an old
credential/enrollment, or automatically select the legacy compatibility path.

Activation remains blocked until all of the following are external facts:

1. `ASM-4-FEDERATED-ORGAN-ENROLLMENT` is source-implemented and independently
   reviewed by its owner/deputy;
2. schema registrations, signed request/response admission and live revocation are
   composed by a named runtime host;
3. the two-host matrix and target-host capacity/backpressure qualification pass;
4. operator acceptance, canary, promotion and release are separately authorized.

This specification changes no current claim: cross-host implementation,
`productExecutionProved`, independent acceptance, activation and release remain
false.
