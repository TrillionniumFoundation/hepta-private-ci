# platform.wire hardened production session

Status: source contract for the current implementation. This document defines
repository-controlled semantics only. It does not issue target-host,
performance, production-observation, reviewer, operations, activation or
release evidence.

## Purpose

The production path has one key-bearing owner and one typed ingress path:

```text
HardenedManagedWireSession
    -> HardenedRecordStream<C: BoundPayloadCodec>
    -> C::Value
```

This composition closes the former gap between three parallel facilities:
canonical/bound payload handling, managed terminal lifecycle, and bounded
record streaming. A production-only build cannot import the raw authenticated
session, raw managed owner, raw record stream or `WireSession`.

Wire validity is still not authority. A typed value returned by this path has
passed transport/session admission; the product effect owner must independently
revalidate and consume its final-use grant immediately before an irreversible
effect.

## Build surfaces

`codex-hepta-wire` defines three Cargo features:

| Feature | Purpose |
| --- | --- |
| `production` | unique bound and lifecycle-owning production surface |
| `protocol-tooling` | raw protocol, migration, fuzzing and qualification compatibility surface |
| `legacy-migration` | explicit alias enabling `protocol-tooling` for staged migration |

The default remains `protocol-tooling` so existing repository callers can be
migrated without a flag-day break. Production integration must use:

```toml
[dependencies.codex-hepta-wire]
path = "../hepta-wire"
default-features = false
features = ["production"]
```

The production-surface verifier compiles a positive fixture and requires
negative fixtures to fail for:

- importing `WireSession`, `AuthenticatedWireSession`,
  `ManagedAuthenticatedWireSession` or `ManagedRecordStream`;
- obtaining a full session from the final owner;
- sealing a raw `DecodedEnvelope`;
- passing an ordinary `PayloadCodec` where `BoundPayloadCodec` is required;
- cloning `SessionMacKey`.

## Establishment

`HardenedManagedWireSession::establish` takes:

1. ordered initiator and responder `NegotiationOffer` values;
2. required capabilities;
3. the runtime role;
4. one immutable `FrozenSchemaRegistry` snapshot;
5. an authenticated transport channel binding;
6. a non-zero connection-local master MAC key;
7. the local endpoint role.

The owner internally performs negotiation, constructs the ordered transcript,
binds the registry snapshot and channel, derives the immutable session
identity, and derives direction-separated record keys. It never returns the
intermediate `WireSession`.

`WireSessionMetadata` is the only diagnostic view. It contains the session ID,
endpoint, role, negotiated posture, registry digest and transcript digest. It
contains no registry object, codec, sequence state, transport handle or key.
Metadata remains readable after retirement without permitting session reuse.

## Lifecycle state machine

```text
                    explicit retire / consuming EOF
             +------------------------------------------+
             |                                          v
Active -- terminal admission/auth/canonical error --> Retired
  |                                                    ^
  +--------------------> Poisoned ---------------------+
```

The public state values are `Active`, `Poisoned` and `Retired`.

Internally, the final owner stores:

```text
Option<HardenedWireSession>
```

and the hardened child stores:

```text
Option<AuthenticatedWireSession>
```

A terminal error takes and drops both option layers immediately. The wrapper
does not merely set a Boolean while retaining replay counters and directional
keys. Subsequent operations return an inactive/poisoned error and cannot
recover a lower-level owner.

The following failures are terminal:

- invalid session identity, sequence or MAC;
- replay, gap, direction or record framing failure;
- frozen-registry admission failure;
- codec descriptor, semantic revision or canonicalization-profile mismatch;
- typed decode failure;
- canonical re-encode failure;
- received payload bytes differing from canonical re-encoding;
- record, allocation or configured resource-limit failure;
- partial-record EOF;
- caller use after poison or retirement.

A new connection requires a fresh authenticated channel, transcript, session
identity and keys. The implementation exposes no reset operation.

## Bound egress

`seal_bound_typed` accepts only `C: BoundPayloadCodec`. Before authentication it
proves that the codec descriptor, semantic revision and canonicalization
profile exactly match the policy frozen into the session registry. It then:

1. admits schema, version, producer, role, generation and capability metadata
   before invoking the codec;
2. encodes the typed value and checks its payload length;
3. constructs and admits the complete HPTA envelope;
4. authenticates the exact HPTA bytes with the endpoint-specific HPTM key and
   next outbound sequence.

Metadata denial therefore does not run payload serialization or hashing. The
encoded payload still requires its own bound check; metadata preflight cannot
predict the codec's output size.

No production method accepts a caller-constructed `DecodedEnvelope`.

## Bound ingress

`open_bound_typed` performs, in order:

1. HPTM length and fixed-prefix validation;
2. session-identity comparison;
3. exact expected inbound-sequence comparison;
4. constant-time MAC verification;
5. HPTA frame decode and frozen-registry admission;
6. exact codec binding verification;
7. typed decode;
8. canonical re-encoding;
9. byte-for-byte comparison with the authenticated payload.

Only after all nine stages succeed does the method return `C::Value`. Raw
`DecodedEnvelope` is not an output of the production owner or stream.

## Hardened record stream

`HardenedRecordStream<C>` consumes the final owner and owns the exact bound
codec. Codec binding is verified during stream construction, before any bytes
are accepted.

The stream preserves three independent caller-owned budgets:

- accepted source bytes;
- complete authenticated-record attempts;
- complete serialized HPTA frame bytes.

`HardenedRecordStreamBudget` is neither `Clone` nor `Copy`. A frame-work budget
shortage yields with `bytes_consumed == 0` for the blocked record and reports
the required frame bytes. The caller retains and resubmits the unconsumed
suffix. Fragmented headers and bodies are staged only after bounded admission.

A `HardenedRecordStreamBatch<C::Value>` may contain a valid typed prefix and a
terminal suffix error. Consumers must deliver the prefix exactly once before
closing the connection. A later failure cannot erase already authenticated and
admitted values, and it cannot cause the failed suffix to be replayed.

Idle staging retention remains bounded. Small allocations may be reused;
excessive empty capacity can be released explicitly or by the configured idle
ceiling. Active fragments, transport queues, caller-retained output,
connection count and whole-process RSS remain obligations of their respective
owners.

## Rotation

`rotate` consumes the old final owner. The replacement must retain:

- endpoint role;
- runtime role;
- negotiated version and effective/required capabilities;
- frozen-registry digest.

It must produce a different session identity. Reusing the same transcript and
channel binding is rejected even when a different master key is supplied. Once
rotation begins, the old owner is consumed and its key state is dropped. A
record from the old session fails against the rotated owner and makes that
connection terminal.

## Secret ownership

`SessionMacKey` stores bytes in `Zeroizing<[u8; 32]>`, rejects an all-zero key
and redacts debug output. It is not cloneable from a production-only build.
Compatibility cloning exists only on the tooling/test surface during migration.
Derived send and receive keys are domain-separated by immutable session ID and
direction. Each direction owns an independent monotonic sequence.

A valid outbound record cannot be reflected and accepted inbound. Peers using
the same endpoint role derive incompatible send/receive directions and fail
closed.

## Compatibility boundary

The raw protocol APIs remain useful for:

- frozen-vector generation and compatibility inspection;
- fuzz targets and malformed-input qualification;
- offline multi-version frame tools;
- staged migration of current repository callers.

They are not production authority and are excluded from the production-only
public surface. New product integrations must not enable `protocol-tooling`.
Existing callers should migrate by constructing the final owner at their
authenticated transport boundary and carrying only typed values beyond it.

## Verification inventory

Focused regressions cover:

- bound canonical round trip;
- non-canonical authenticated payload rejection;
- wrong codec revision rejection before sealing;
- canonical re-encode failure and immediate child-owner destruction;
- final-owner bound round trip;
- terminal failure dropping the only child owner;
- fresh-session-identity rotation requirement;
- old-session record rejection after rotation;
- fragmented hardened record delivery;
- valid typed prefix before a terminal suffix;
- full-frame work-budget yield without input consumption;
- partial-record EOF;
- production-only positive and compile-fail API fixtures.

Repository CI additionally runs the ordinary crate suite and production-only
`cargo check`. `actionlint` statically checks every GitHub Actions workflow for
syntax, expression and context errors.

## Evidence and release boundary

The source implementation can establish only `Implemented`. Qualification and
release remain fail-closed until the same immutable candidate has all required
receipts:

1. exact-head;
2. deterministic synthetic merge;
3. protected target host;
4. exact-source fuzz campaigns;
5. registered five-path candidate/gRPC performance evidence;
6. registered eight-scenario production-composition evidence;
7. independent security/semantic review;
8. independent operations acceptance;
9. release receipt and artifact digest.

An empty producer registry means no external producer is accepted. Local
fixtures, loopback tests, ordinary cloud runners and historical receipts must
not be promoted into production, reviewer, operations or release evidence.
