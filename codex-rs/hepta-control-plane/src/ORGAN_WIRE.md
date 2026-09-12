# Compiled body graph binding V2

This adapter admits only a host-approved graph for reviewed, compiled,
stateless, read-only `TrustedReadOnlyOrganV1` handlers. It is executable Rust
transport and host construction, with no code loading, I/O permission, state
transfer, authority minting or automatic admission of an arbitrary graph.

## V1 compatibility and trust

`docs/cns/ORGAN_PROTOCOLS.json` registers `BodyGraphSnapshotV1` fields but does
not define their canonical wire encoding or a manifest class mapping. Therefore
`BodyGraphBindingV1` is explicitly a projection, not a new definition or a
deserializable alias of that protocol. A trusted canonical producer supplies:

- The source snapshot digest, generation, complete ordered manifest identities
  and manifest digests, class-to-`OrganRole` projections, ordered input/output
  port identities, dependency/fallback edges and canonical initialization order.
- A full native `OrganGraphsV1`, including fields that the V1 projection cannot
  express: native ownership, terminal evidence, runtime port links, dataflow
  timing, complete feedback profiles and process/host failure domains.

Each manifest digest refers to the complete source manifest, including its
version, domain/authority declarations, resource envelope, health checks and
retirement/rollback policy. This adapter does **not** reconstruct or validate
those omitted source fields from a digest, and does not recompute the original
canonical snapshot digest. The trusted producer must verify the projection
against its canonical source; defining the canonical V1 codec is still the
protocol owner's work. This local V2 binding profile adds no new active
canonical lifecycle protocol to the registry.

The host independently provisions `CompiledOrganAdmissionV2` with the digest of
the **entire** V2 payload, expected generation and its own process/host identity.
It must never copy these values from the received payload. An attacker computing
the hash of a changed graph obtains no approval. Exact ordered encoding is the
identity: even reordering equivalent edges creates a different approved payload.
The digest is SHA-256 over the bytes `hepta.compiled-body-graph.v2` plus a zero
byte followed by the entire transport bytes. The source snapshot and manifest
digests are included in that identity along with every native graph field.

After digest verification the decoder checks all overlapping fields for exact
equality, including both generations, manifest count/order/IDs, mapped classes,
port count/order/IDs, both edge lists and canonical initialization order. It
rejects duplicate port identities within each direction. The native validator
still checks graph bounds, acyclic initialization/fallback, complete port
connections, synchronous safety dependencies, feedback SCCs and evidence bounds,
fallback exits and complete failure-domain membership. All effect scopes must
be empty and every placement must match the host's single process and host.
These placement names are trusted deployment configuration, not OS attestation.

`VerifiedCompiledBodyGraphV2` has private fields. Consuming it with `into_host`
checks each `CompiledOrganHandlerV2` against its manifest ID/digest, then delegates
to `OrganHostV1::new` for exact handler count/identity/uniqueness. This catalog is
trusted compiled host code; its digest does not attest machine code or sandbox
a handler. No lifecycle callback occurs during decoding or failed construction.
Successful construction is only Registered; the caller explicitly starts the
host. Dispatch retains the existing one-hop and `AuthorityPosture::DENY_ALL`
semantics. There is no generic remote loader attached to the product daemon.

## Native handoff registry admission

`decode_compiled_body_graph_v2` remains the low-level digest and structural
decoder. A runtime composition that crosses the native handoff seam must call
`admit_compiled_body_graph_v2` instead. That entry point first matches the
caller-supplied `NativeHandoffProtocolAdmissionV1` against the host-owned
`NativeHandoffProtocolRegistryV1::canonical()` entry (`BodyGraphSnapshotV1`,
profile `hepta.compiled-body-graph.v2`, version `2`, and a fixed schema
digest). It then performs the independent payload digest, generation and
placement checks before returning a `NativeHandoffReceiptV1` and the verified
graph. Registry admission is therefore a real native producer/consumer seam,
while the receipt remains an observation with `AuthorityPosture::DENY_ALL`;
it cannot mint a lease, select a candidate, or open an external effect.

Unknown protocol IDs, profile versions, schema digests, malformed graphs and
host mismatches fail before handler construction. The registry is deliberately
in-memory and host-owned: durable state-handoff migration, authenticated
witnesses and production deployment qualification remain separate gates.

## Fixed encoding

All integers are unsigned big-endian. Counts, organ/port indexes and identifier
byte lengths use `u16`; generations and timing/gain/saturation values use `u64`;
queue capacity uses `u32`; digests are exactly 32 raw bytes. Identifiers are
1–128 ASCII bytes accepted by `StableId`. There are no maps, optional extension
bags, nested graph records or recursively encoded values.

| Order | Record | Fields in encoding order |
| --- | --- | --- |
| 1 | Header | Eight bytes `HEPTAORG`, version `u16=2`, execution profile `u8=0` (compiled/stateless/read-only), authority mask `u8=0` (all eight flags false) |
| 2 | V1 binding | Generation, source snapshot digest, manifest list, dependency edges, fallback edges, initialization order |
| 3 | Manifest binding | Organ ID, complete manifest digest, role tag, input ID list, output ID list |
| 4 | Native graph | Generation, organ list, initialization edges, runtime links, feedback profiles, fallback edges, failure domains |
| 5 | Native organ | ID, owner ID, role tag, input ID list, output ID list, effect count `u16=0`, terminal tag and applicable digest |
| 6 | Edge | Source organ index, target organ index |
| 7 | Runtime link | Output organ/port indexes, input organ/port indexes, timing tag |
| 8 | Feedback profile | Ascending distinct member indexes, reference generation, period/delay/jitter, queue capacity, max gain/saturation, gains-and-saturation/operating-region/stability-analysis/perturbation-test digests, exit organ index |
| 9 | Failure domain | Organ index, process ID, host ID |

Role tags are Cognitive=0, LocalSafety=1, Other=2. Timing tags are Buffered=0,
Synchronous=1. Terminal tags are None=0 (no digest), SafeState=1 and
HumanTakeover=2 (each followed by a digest). Every list begins with its element
count. Unknown version, profile, authority flag, enum tag, extra/trailing byte,
truncated field or noncanonical feedback member order is rejected.

The decoder rejects inputs over 2 MiB **before copying or decoding**, then checks
each collection count before allocation: at most 128 organs/manifests/domains/
profiles/member indexes/order entries, 1,024 edges or links per list, and 32
ports per direction per organ. Identifier lengths are checked before allocating
a string. Non-empty effect lists are rejected without allocating them. Nested
iteration is bounded by these fixed counts; native reachability is bounded by
128 nodes. The encoder first validates the in-memory graph and matching
projection, then verifies the final byte limit.

## Verification and remaining limits

`organ_wire_tests.rs` covers a full graph round trip (including feedback,
placement, terminal evidence and both timing kinds), construction of the real
host and a real one-hop handler dispatch. Adversarial cases cover every truncation
offset, every payload byte under an independent fixed digest, overlong input and
declared counts, unsupported versions/profiles, positive authority, trailing
fields, source/native projection disagreements, stale generation, missing
feedback/placement, invalid ports/timing, catalog manifest mismatch and duplicate
handlers. Malformed-input tests also use matching expected hashes so digest
rejection cannot conceal missing structural validation.

These are software boundary tests. Feedback profiles remain declarations and
evidence references; the adapter does not validate experimental evidence, run a
periodic/real-time scheduler, enforce OS resource/isolation guarantees, or prove
biological stability. The host's compiled-handler review obligation remains.
Canonical V1 producer integration, production boot wiring, dynamic artifact
qualification, signed remote provenance, stateful handoff, quiescence, I/O
capabilities and durable generation cutover require their own actual consumers
and tests. None is marked complete by this adapter.
