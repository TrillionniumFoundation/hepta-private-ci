# runtime.codex product intent payload V3

## Scope

`hepta.codex-operation-intent.v3` is the current product-bound payload schema
for the registered `ModulePort::platform.wire::runtime.codex` port. It is
carried inside an HPTA frame with frame version `2` and canonical producer
`runtime.agentd`.

Payload-schema version V3 and HPTA frame version 2 are independent. V3 does not
modify the frozen HPTA byte layout or the historical
`hepta.codex-operation-intent.v2` payload contract.

## Compatibility boundary

V2 remains an authority-free, product-unbound compatibility DTO. It rejects an
intent that contains `app_server_binding`; a binding is never silently dropped.
A normal inference-worker product request uses V3, where the binding is
mandatory.

Consumers reject an unknown schema, a producer other than `runtime.agentd`, a
wire version other than HPTA V2, missing fields, duplicate struct fields,
unknown fields, invalid identifiers, zero digests, an expired/zero deadline or
an incomplete/invalid App Server binding.

## Canonical payload

The V3 payload is canonical JSON produced from this closed structure:

```text
CodexOperationIntentWireV3 {
  operation_id: string,
  thread_id: string,
  method_id: string,
  payload_digest: lowercase Digest32 text,
  lease_payload_digest: lowercase Digest32 text,
  deadline_ms: nonzero u64,
  app_server_binding: {
    source_admission_digest: lowercase Digest32 text,
    agent_generation: nonzero u64 equal to the HPTA frame generation,
    session_id: string,
    client_user_message_id: string,
    user_input_digest: lowercase Digest32 text,
    protocol_id: string,
    app_server_version: string,
    codex_home_digest: lowercase Digest32 text,
    connection_id: nonzero u64
  }
}
```

All identifier strings must construct a canonical `StableId`. The HPTA frame
generation must equal `app_server_binding.agent_generation`; an intent cannot
be replayed under another Agent generation by replacing only frame metadata.
Both payload digests must be nonzero and equal. `protocol_id` must equal the registered App
Server V2 protocol identity. `app_server_version` is nonempty, bounded by the
domain adapter's maximum, and contains no ASCII control characters.

## Semantic binding

After typed decode, the adapter reconstructs the native
`CodexOperationIntent` and recomputes the existing domain request digest. That
digest uses domain `hepta.codex.adapter.request.v6` and includes every common
intent field and every App Server binding field. `adapt_product_wire_v3`
rejects if the request digest before and after the wire boundary differs.

The HPTA frame digest independently binds the schema, producer, frame
generation, encoded lengths and payload bytes. It is an unkeyed integrity
digest, not peer authentication.

## Authority boundary

The V3 payload carries identity, currentness and correlation facts. It does not
serialize `VerifiedUseToken`, `EnteredUseToken`, a signing key, provider secret
or another consumable authority object.

The normal `hepta-infer-worker-host` path is ordered as follows:

1. Build the complete `CodexOperationIntent` from the current Agentd/App Server
   connection and admitted request.
2. Run `adapt_product_wire_v3`, including HPTA encode/decode, schema admission,
   producer pinning and request-digest parity.
3. Claim final-use authority from the existing authority owner.
4. Persist/dispatch the durable native operation.
5. Revalidate current owner/cognitive facts.
6. Enter the verified use and perform physical App Server `turn/start`.
7. Observe or reconcile the terminal result through the existing durable path.

Wire admission never substitutes for steps 3 through 7.

## Failure and recovery

A V3 schema, producer, digest or binding failure rejects before final-use claim
and before physical `turn/start`. No external effect has been authorized by a
successful decode alone.

After physical `turn/start`, transport loss remains indeterminate and follows
the existing same-operation reconciliation path. It is never converted into a
new request solely because the V3 bytes can be re-encoded.

## Verification sources

- `codex-rs/hepta-codex-adapter/src/wire_tests.rs` verifies complete binding
  round trip, domain request-digest parity, V2 non-dropping behavior and V3
  mutation/unknown-field rejection.
- `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs` verifies
  wire admission precedes final-use claim and physical `turn/start`.
- `codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs` remains the named
  product execution path; exact-candidate execution is a separate receipt.

## Non-claims

This schema does not provide authenticated transport, target-host
qualification, operator acceptance, deployment activation, promotion or
release. Those gates remain external to the codec and payload adapter.
