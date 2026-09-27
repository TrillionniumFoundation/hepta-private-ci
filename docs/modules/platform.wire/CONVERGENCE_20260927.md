# platform.wire convergence record — 2026-09-27

This record is the current developer-facing delta for the `platform.wire`
convergence branch. It supplements `TECHNICAL.md`,
`SECURITY_AND_QUALIFICATION.md`, the Lane A protocol specifications and the
machine-generated lifecycle status. It does not replace evidence receipts and
must not be used to promote a source-only result to production acceptance.

## Source subject

- repository: `TrillionniumFoundation/hepta-private-ci`
- branch: `codex/platform-wire-final-convergence-20260925`
- source baseline: `a126987b84737dbc2ee2592442a314117bddb4a2`
- convergence commits added in this review:
  - `61573a303d9a32c66ca382cef99b78f3ea87ac2e`
  - `174dd5a5187507a9f215b62a69710f57a3433c36`
  - `9ad13f918dbceddf9944c7311498a569d7ad99ad`
  - `04041150da3253247405a579e84e5612dc1bb97d`

The final subject for qualification is the commit containing this record and
must be read from the exact-head workflow receipt rather than copied from this
file.

## Closed protocol P0s

### Negotiated session enforcement

`NegotiatedStreamingDecoder` rejects a frame whose HPTA version differs from
the selected HPTN version at the fixed-header boundary. `WireSessionDecoder`
adds frozen schema, producer, role, generation and capability admission. The
normal `runtime.codex` V3 product path now decodes the exact `WireEnvelopeV2`
type and does not dispatch through the compatibility any-version decoder.

The generic `decode_frame` and unbound `StreamingDecoder` remain compatibility,
qualification and migration surfaces. They are not the product admission
boundary.

### Lossless incremental failure semantics

Every incremental `push` API returns a must-use batch containing both:

1. the valid prefix completed before the fault; and
2. the terminal error observed later in the same feed.

No compatibility `Result<Vec<_>, _>` entrypoint remains that can return an
`Ok(valid_prefix)` while hiding a latched terminal error in decoder state.
After a terminal protocol, resource or policy error, the decoder is poisoned;
partial bytes are discarded and the old connection/session cannot continue.

### Codec semantic identity

`PayloadCodecBinding` and `BoundPayloadCodec` bind a typed codec to the exact
`schema_revision` and `CanonicalizationProfile` frozen into the session
registry. `verify_codec_binding`, `encode_bound_typed_envelope` and
`decode_bound_typed_envelope` reject a descriptor, revision or canonicalization
mismatch before typed serialization/deserialization.

This closes the gap where a codec could reuse an admitted schema identifier
while silently changing semantic revision or canonical bytes.

### Authenticated session lifecycle

`ManagedAuthenticatedWireSession` owns an explicit lifecycle:

- `Active` — authenticated records may be sealed/opened;
- `Poisoned` — a terminal authenticated-session error occurred;
- `Retired` — key-bearing state was destroyed and cannot be reused.

Key rotation consumes the old owner, preserves initiator/responder direction,
and requires a newly negotiated session identity. Reusing the same transcript
and channel binding to reset sequence numbers under a new key is rejected.

## Protocol-control closure

### Version-scoped capabilities

HPTN offer construction validates version/capability coherence. Negotiation
keeps the following concepts separate:

- capabilities advertised by each peer;
- capabilities common to both offers;
- capabilities effective for the selected version;
- capabilities explicitly required by the caller.

A V1 result cannot report the V2 metadata-bound digest as effective.

### Frozen admission policy

A frozen schema policy binds:

- schema identifier and supported wire-version range;
- maximum payload size;
- semantic schema revision;
- canonicalization profile;
- allowed producers and runtime roles;
- generation policy;
- required effective capabilities.

The registry snapshot digest is included in the negotiation transcript. A
consumer cannot silently substitute a different registry after session
establishment.

### Three distinct forms of negotiation

The implementation and documentation use separate names for three separate
operations:

1. **HTTP representation negotiation** — the loopback gateway parses all
   `Accept` fields, quality weights, media-range specificity, parameter order,
   quoted version values and JSON fallback. This chooses the response format
   only.
2. **HPTN protocol negotiation** — peers advertise coherent wire versions and
   capabilities, and select one effective protocol result.
3. **Authenticated session establishment** — the HPTN transcript, registry
   digest, roles and an externally supplied channel binding produce a session
   identity and directional record keys.

An HTTP `Accept` result is never evidence that an HPTN or authenticated session
exists.

## Verification surfaces

The source tree now contains:

- canonical positive HPTA V1, HPTA V2 and HPTN vectors;
- `NEGATIVE_CONFORMANCE_V1.json`, consumed by Rust tests and bound to stable
  rejection classes;
- good-good-bad and valid-prefix-plus-terminal-error regressions;
- deterministic chunk-boundary and partition coverage;
- near-limit payload and long-stream throughput qualification;
- PR fuzz smoke and scheduled sustained fuzz workflows;
- Rust-to-Python and Python-to-Rust raw binary session qualification;
- exact-source, synthetic-merge and target-host receipt schemas;
- generated lifecycle status that fails closed on absent or inconsistent
  receipts.

The negative vectors include malformed magic/version/identity/generation,
length and digest faults, V1 after a V2 negotiation, HPTN reserved bytes,
unknown capability bits and noncanonical version ordering.

## Product execution boundary

The named `runtime.codex` V3 source path carries the complete App Server request
binding, checks frame generation against the domain generation, preserves the
request digest and enters the existing domain adapter only after exact V2 typed
admission. The host still requires its independently validated source,
authority, lease and App Server gates before any effectful execution.

No HPTA frame, HTTP header, schema object, transcript or session record mints
model/provider/effect authority.

## Qualification and activation truth

The following states are intentionally distinct:

| State | Meaning | Current rule |
|---|---|---|
| designed | specifications and security boundaries exist | source-derived |
| implemented | required native source files exist | source-derived |
| exact-head qualified | tests/lint/commands passed on the exact source SHA | workflow receipt required |
| synthetic-merge qualified | same qualification passed on the generated base merge | workflow receipt required |
| target-host qualified | protected target-host workflow passed on the exact SHA | external receipt required |
| independently accepted | distinct reviewer and operations approvals exist | two independent receipts required |
| activated | approved product/runtime configuration admits the path | externally governed |
| released | accepted source and artifact digest are in a release receipt | externally governed |

At the time this record is authored, source implementation is present. The
current exact-head, synthetic-merge and target-host results must be read from
new workflow artifacts for the final subject commit. Independent acceptance,
activation and release remain false until their external evidence exists.

## Remaining externally governed work

The repository cannot self-produce any of the following:

- a trusted TLS exporter, production signing key or production MAC root;
- protected target-host execution evidence;
- rolling-upgrade and mixed-version observations from the deployment fleet;
- independent reviewer and operations acceptance;
- deployment activation or release authority.

Test keys, synthetic channel bindings and repository-authored receipts are not
substitutes for those controls. Production booleans must remain false until the
corresponding external receipts are admitted by `scripts/platform_wire_status.py`.
