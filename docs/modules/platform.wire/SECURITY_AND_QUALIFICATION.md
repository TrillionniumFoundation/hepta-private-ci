# platform.wire production security and qualification

This document defines the production-facing security composition added above the frozen HPTA V1/V2 framing contracts. It does not turn source code, a pull request, or a passing generic CI run into deployment authority.

## 1. Immutable registry and policy snapshot

Production sessions use `FrozenSchemaRegistryBuilder` and `FrozenSchemaRegistry`, not a process-global mutable `SchemaRegistry`. Each `SchemaPolicy` binds one schema descriptor to:

- an explicit bounded producer allowlist;
- an explicit bounded runtime-role allowlist;
- the minimum effective negotiated capabilities;
- wire-version and payload ceilings inherited from `SchemaDescriptor`.

The builder is bounded to `MAX_FROZEN_SCHEMA_ENTRIES` and rejects conflicting reuse. `freeze()` creates a read-only registry and a deterministic `snapshot_digest`. The digest includes every schema identity, version range, payload limit, capability requirement, producer and role in canonical sorted order. A session therefore cannot silently observe a later registry mutation.

## 2. Negotiation and channel binding

`NegotiationTranscript::from_offers` re-runs negotiation and rejects a supplied result that does not equal the result implied by the ordered initiator/responder offers. Its digest binds:

1. both canonical HPTN offer byte strings in role order;
2. selected wire version;
3. effective, common-advertised and required capabilities;
4. frozen registry snapshot digest;
5. an authenticated transport channel binding.

The channel binding must contain 16–512 bytes. It should be a TLS exporter, Noise handshake hash, mutually authenticated local-channel binding, or an equivalently authenticated value supplied by the transport owner. A hostname, socket address, bearer token string, or unverified peer claim is not an acceptable channel binding.

`WireSession` derives a stable session identifier from the transcript, registry snapshot and selected posture. It couples typed encoding/decoding to the negotiated version, runtime role, admitted producer and schema policy.

## 3. Direction-separated authenticated record format

`AuthenticatedWireSession` provides an optional transport-neutral HMAC-SHA-256 record layer for transports that do not already provide equivalent per-record authentication and replay ordering.

The public constructor requires a `SessionEndpoint` (`Initiator` or `Responder`) and one 32-byte `SessionMacKey`. The master key is never used directly as a record key. Two disjoint keys are derived with HMAC-SHA-256 over:

- the domain `HPTA-AUTHENTICATED-RECORD-KEY-V1`;
- the immutable `WireSession::session_id()`;
- exactly one direction label: `initiator-to-responder` or `responder-to-initiator`.

An initiator transmits with the first direction and receives with the second; a responder uses the inverse mapping. Send and receive counters are also independent. A valid outbound record therefore cannot be reflected to the same endpoint and accepted as inbound traffic. Same-endpoint peers fail MAC verification.

Record V1 layout:

| Field | Width | Meaning |
|---|---:|---|
| magic | 4 | ASCII `HPTM` |
| format | 2 | unsigned big-endian `1` |
| session ID | 32 | transcript/registry/session posture digest |
| sequence | 8 | unsigned big-endian, starts at 1 independently in each direction |
| frame length | 4 | bounded encoded HPTA frame length |
| frame | variable | exact HPTA V1/V2 frame selected by the session |
| tag | 32 | HMAC-SHA-256 over domain separator and all preceding record bytes, using the direction-specific key |

The MAC covers the exact frame bytes, session identity and sequence. Verification uses a constant-work byte comparison. Wrong session, sequence, length, format, tag, direction or admitted frame poisons both directions of the connection-local authenticated session. Sequence state is never reset in place; reconnect and renegotiate instead.

`SessionMacKey` is exactly 32 bytes, rejects the all-zero value and redacts its debug representation. Key creation, storage, rotation and destruction remain responsibilities of the authenticated transport/secret owner. Keys must not enter generic evidence, logs, prompts or learning artifacts.

## 4. Security boundaries and nonclaims

HPTA V1 and V2 digests remain unkeyed integrity digests. V2 prevents undetected metadata drift when the expected digest is trusted, but it does not authenticate a producer. Producer identity becomes meaningful only after the transport channel and session transcript are authenticated and the frozen policy admits that producer.

The authenticated record layer proves possession of a direction-derived session key and ordered record integrity. It does not mint final-use authority, authorize a domain effect, replace revocation checks, or prove that a remote operator accepted deployment.

A transport that already supplies equivalent authenticated encryption, direction separation and replay ordering may omit the HPTM wrapper, but it must still construct the same negotiation transcript and bind the selected session posture to that transport channel. That equivalence must be documented and independently reviewed.

## 5. Error and resource semantics

Production-facing errors carry the session identifier and, where known, the byte offset. Length failures report actual and maximum or expected values. Registry failures identify the rejected schema, producer, role or capability mask. These diagnostics are safe identifiers and bounds; secret key bytes and payload contents are not included.

The existing `StreamingDecoder` remains header-first, bounded and terminally poisoned after protocol/resource failure. The authenticated layer additionally caps records at `MAX_AUTHENTICATED_RECORD_BYTES`, verifies record bounds before frame decode and poisons the bidirectional public session after a terminal record error.

## 6. Evidence-derived lifecycle

Lifecycle state is generated by `scripts/platform_wire_status.py` and fails closed:

- **Designed** requires the normative and module design documents.
- **Implemented** additionally requires all declared native source components, including the frozen policy, secure session and direction-separation modules.
- **Qualified** additionally requires source-consistent schema-v2 receipts for exact head, deterministic synthetic merge and the protected target host.
- **Accepted** additionally requires two source-consistent acceptance receipts: one independent semantic/security reviewer and one operations approver. The approvers must be distinct and neither may equal the implementation author named by the receipt.
- **Released** additionally requires an accepted state and a source-bound release receipt with an artifact digest.

Exact-head and synthetic-merge receipts are produced by the Lane A workflow. Target-host evidence is produced only by `.github/workflows/platform-wire-target-host.yml`, which checks out `github.sha`, requires an operator-supplied SHA to equal that dispatched SHA, uses a fixed self-hosted label and runs in the `platform-wire-target-host` environment. The environment must be protected by independent required reviewers, and the runner image must provide the pinned/offline Rust and Python dependencies before execution. Arbitrary input refs and arbitrary runner labels are not executed.

Target-host execution, independent review and operations acceptance cannot be self-attested by the implementation author or generated merely because tests passed. A normal GitHub review without a matching source-bound acceptance receipt is review context, not lifecycle acceptance.

### Receipt schema v2

All lifecycle receipts use `hepta.platform-wire.receipt.v2` and bind a lowercase 40-hex `source_sha`, `tested_sha`, kind and status. Workflow receipts additionally bind workflow/ref, run ID, attempt, event and generation time. Exact-head and target-host receipts require `tested_sha == source_sha`; a synthetic-merge receipt requires a distinct tested merge SHA plus its base SHA. Acceptance receipts bind approver identity, approver role, implementation author, approval time and GitHub evidence URL. Release receipts bind a release ID, approving identity, GitHub evidence URL and lowercase SHA-256 artifact digest.

Malformed, legacy, source-inconsistent or self-attested receipts are rejected before lifecycle evaluation.

## 7. Required qualification evidence

The exact-head and synthetic-merge jobs retain command records even when the wider Lane A lane fails. Their minimum-test floors must match the current named suites; zero-test or stale-filter success is not evidence. The target-host job uses a temporary `CARGO_TARGET_DIR`, offline locked dependencies and removes build products after evidence upload.

The three qualification receipts, two acceptance receipts and release receipt remain separate artifacts. Combining them into one self-issued document is prohibited. Release automation consumes them; source code does not manufacture reviewer or operator acceptance.

## 8. Required tests

The native suite must cover:

- registry entry and subject ceilings;
- snapshot stability across registration order;
- conflicting policy rejection;
- selected-version, effective-capability, producer and role denial;
- envelope-coupled typed round trips;
- transcript mismatch and channel-binding bounds;
- frame tamper, MAC tamper, replay, sequence gap and cross-session replay;
- reflected outbound record rejection and same-endpoint direction mismatch;
- terminal poison behavior across both directions;
- bidirectional Rust/Python framing and strict payload rejection;
- exact-head, synthetic-merge, protected target-host, independent-reviewer and operations receipt validation.

Any change to the HPTM layout, transcript material, registry digest, direction labels, key derivation, sequence semantics or MAC algorithm requires a new version and cannot reinterpret V1 bytes in place.
