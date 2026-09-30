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

The channel binding must contain 16–512 bytes and must not be all zero. This syntactic check does not prove that the transport supplied an authentic value. It should be a TLS exporter, Noise handshake hash, mutually authenticated local-channel binding, or an equivalently authenticated value supplied by the transport owner. A hostname, socket address, bearer token string, or unverified peer claim is not an acceptable channel binding.

`WireSession::new` returns `Result` and rejects a registry snapshot or negotiated posture that differs from the immutable transcript. `NegotiatedSession` is an alias for this checked type. Session-identity derivation profile V2 (`HPTA-WIRE-SESSION-V2\0`) includes the length-prefixed runtime admission role as well as the transcript, registry snapshot and selected posture. Both endpoints must agree on this shared admission role; it is not the local initiator/responder direction. Deploy this profile with fresh sessions at both endpoints. Identity-profile V1 peers fail closed; there is no in-place counter reset or fallback. Frozen HPTA framing and the HPTM record field layout are unchanged. It couples typed encoding/decoding to the negotiated version, runtime role, admitted producer and schema policy.

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

The MAC covers the exact frame bytes, session identity and sequence. Verification uses the standard `hmac` crate `Mac::verify_slice` API, with SHA-256 supplied by `sha2`, instead of a handwritten authenticator. The RFC 4231 test-case-one tag is a native regression vector. Wrong session, sequence, length, format, tag, direction or admitted frame poisons both directions of the connection-local authenticated session. Sequence state is never reset in place; reconnect and renegotiate instead.

`SessionMacKey` is exactly 32 bytes, rejects the all-zero value and redacts its debug representation. Owned master and directional key arrays use `zeroize::Zeroizing`; terminal poison clears both directional keys, managed poison drops key-bearing state immediately, and retirement drops the session. Rotation consumes the previous owner, requires a fresh session identifier and preserves the frozen registry, negotiated posture and shared runtime role. A policy change requires an explicitly new admission, not key rotation. Upstream key creation, durable storage, entropy and destruction of copies outside these owners remain responsibilities of the authenticated transport/secret owner; this is not a claim that all compiler-created or caller-owned copies are erased. Keys must not enter generic evidence, logs, prompts or learning artifacts.

## 4. Security boundaries and nonclaims

HPTA V1 and V2 digests remain unkeyed integrity digests. V2 prevents undetected metadata drift when the expected digest is trusted, but it does not authenticate a producer. Producer identity becomes meaningful only after the transport channel and session transcript are authenticated and the frozen policy admits that producer.

The authenticated record layer proves possession of a direction-derived session key and ordered record integrity. It does not mint final-use authority, authorize a domain effect, replace revocation checks, or prove that a remote operator accepted deployment.

A transport that already supplies equivalent authenticated encryption, direction separation and replay ordering may omit the HPTM wrapper, but it must still construct the same negotiation transcript and bind the selected session posture to that transport channel. That equivalence must be documented and independently reviewed.

## 5. Error and resource semantics

Production-facing errors carry the session identifier and, where known, the byte offset. Length failures report actual and maximum or expected values. Registry failures identify the rejected schema, producer, role or capability mask. These diagnostics are safe identifiers and bounds; secret key bytes and payload contents are not included.

The existing `StreamingDecoder` remains header-first, bounded and terminally poisoned after protocol/resource failure. `StreamingDecoder::finish`, `NegotiatedStreamingDecoder::finish` and `WireSessionDecoder::finish` consume the decoder at EOF. A retained partial header or body yields `UnexpectedEof`; previously delivered prefix frames are never retracted. These APIs frame HPTA streams, not an unparsed HPTM stream. The authenticated layer additionally caps records at `MAX_AUTHENTICATED_RECORD_BYTES`, verifies record bounds before frame decode and poisons the bidirectional public session after a terminal record error.

## 6. Evidence-derived lifecycle

Lifecycle state is generated by `scripts/platform_wire_status.py`. The script is the executable lifecycle authority; this document, `CURRENT_IMPLEMENTATION.md` and the generated `STATUS.md` use the same fail-closed definitions:

- **Designed** requires the normative and module design documents.
- **Implemented** additionally requires every declared native source component, including the frozen policy, secure session, direction-separation, bounded managed ingress and hardened canonical-codec facade.
- **Qualified** additionally requires all three source-consistent qualification axes for one immutable source candidate: (1) the exact-head and deterministic synthetic-merge receipts, (2) the current-source three-target fuzz campaign, and (3) the protected target-host receipt. The target-host profile includes authenticated record/session behavior, frozen schema-policy admission and the selected product/transport path. Performance, deployment observation, reviewer approval and release are not inferred from `Qualified`.
- **Accepted** additionally requires four same-source acceptance families: a passed five-path paired performance receipt, a passed eight-scenario production-composition receipt, an independent semantic/security reviewer receipt and a distinct operations approver receipt. The human approvers must be different identities and neither may equal the implementation author named by the receipt.
- **Released** additionally requires `Accepted` plus a source-bound release receipt, artifact digest and the separately governed canary/promotion facts required by the release procedure.

Exact-head and synthetic-merge receipts are produced by the Lane A/exact workflows. The three-target fuzz workflow must execute `decode_frames`, `managed_records` and `policy_admission` at the same exact source SHA; creating a harness, initializing a receipt or skipping a target is not qualification. Target-host evidence is produced only by `.github/workflows/platform-wire-target-host.yml`, which checks out `github.sha`, requires an operator-supplied SHA to equal that dispatched SHA, uses a fixed self-hosted label and runs in the `platform-wire-target-host` environment. The environment must be protected by independent required reviewers, and the runner image must provide the pinned/offline Rust and Python dependencies before execution. Arbitrary input refs and arbitrary runner labels are not executed.

Target-host execution, paired benchmark measurements, production deployment observations, independent review, operations acceptance and release cannot be self-attested by the implementation author or generated merely because repository tests passed. A normal GitHub review without a matching source-bound acceptance receipt is review context, not lifecycle acceptance. Missing, queued, running, skipped, cancelled, stale or malformed evidence remains false.

### Receipt schema v2

All lifecycle receipts use `hepta.platform-wire.receipt.v2` and bind a lowercase 40-hex `source_sha`, `tested_sha`, kind and status. Workflow receipts additionally bind workflow/ref, run ID, attempt, event and generation time. Exact-head, fuzz, target-host, performance and production receipts require the source identity selected by the lifecycle evaluator; a synthetic-merge receipt additionally binds its distinct tested merge SHA and fixed base SHA. Performance and production receipts bind their registered producer, immutable plan/report identities and reduced path/scenario outcomes. Acceptance receipts bind approver identity, approver role, implementation author, approval time and GitHub evidence URL. Release receipts bind a release ID, approving identity, GitHub evidence URL and lowercase SHA-256 artifact digest.

Malformed, legacy, source-inconsistent, not-run or self-attested receipts are rejected before lifecycle evaluation. Workflow success is not permission for a workflow to issue a fact owned by another evidence producer.

## 7. Required qualification and acceptance evidence

The exact-head and synthetic-merge jobs retain command records even when a wider Lane A lane fails. Their minimum-test floors must match the current named suites; zero-test or stale-filter success is not evidence. The fuzz campaign must retain per-target command, engine/sanitizer, budget and non-zero execution statistics. The target-host job uses a temporary `CARGO_TARGET_DIR`, offline locked dependencies and removes build products after evidence upload.

Qualification evidence is partitioned into three independent axes: exact source/integration, current-source fuzz and protected target-host execution. Acceptance then adds four independent same-source families: five-path performance, eight-scenario production composition, independent reviewer and operations approval. Release evidence remains separate from all seven earlier families. Combining those facts into one self-issued document, borrowing a historical pass or treating tree equivalence as execution is prohibited. Release automation consumes independently owned evidence; source code does not manufacture benchmark, deployment, reviewer, operator or release acceptance.

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
- exact-head, synthetic-merge, three-target fuzz, protected target-host, five-path performance, eight-scenario production, independent-reviewer, operations and release receipt validation.

Any change to the HPTM layout, transcript material, registry digest, direction labels, key derivation, sequence semantics or MAC algorithm requires a new version and cannot reinterpret V1 bytes in place.

## 9. Current remediation and deployment boundary

See [REMEDIATION_20260928.md](REMEDIATION_20260928.md) for exact source changes and verification distinctions. An in-process product codec round trip does not prove a remotely authenticated ingress. No live TLS exporter, independently authenticated peer admission, target-host recovery, rolling upgrade or external acceptance is asserted by these source changes.
