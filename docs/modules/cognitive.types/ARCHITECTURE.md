# cognitive.types architecture

**Status:** source hardening and canonical-consumer convergence candidate  
**Owner:** `cognitive-platform`  
**Deputy:** `kernel-contracts`  
**Authority posture:** pure contract library; no SQL, daemon, network, model, effect, promotion or release authority

## 1. Purpose

`cognitive.types` owns bounded, versioned Rust representations for cognitive records, HNMF assets, recall, plasticity, topology, forgetting, Lane C exchange and canonical wire envelopes. It does not own durable state. Durable owners remain responsible for authentication, authorization, freshness, revocation, transactions, fencing and recovery.

The module has four layers:

1. **Compatibility domain types** in `src/lib.rs`, `src/hnmf.rs`, `src/hnmf_learning.rs` and `src/lane_c.rs`.
2. **Strict semantic validation** in `src/strict.rs`.
3. **Canonical transport and digesting** in `src/wire.rs`, `src/registry.rs` and `src/contract.rs`.
4. **Consumer convergence and authority-bound receipts** in `src/consumer.rs` and `src/write_receipt.rs`.

## 2. Trust boundaries

```text
untrusted bytes
    |
    v
closed registry inspection
(schema, version, contract, size)
    |
    v
typed decode + deny_unknown_fields
    |
    v
local shape validation
    |
    v
strict cross-field validation
    |
    v
canonical byte equality
    |
    v
Validated<T>
    |
    +--> domain-bound digest
    +--> registered consumer adapter
    +--> durable owner / authenticated writer
```

`Validated<T>` means only that the current contract validator accepted the value. It does not grant access or establish external freshness. A durable owner must still bind the validated value to an authenticated principal, authority epoch, revocation frontier, snapshot, writer generation and transaction outcome.

## 3. Component ownership

| Component | Owns | Explicitly does not own |
|---|---|---|
| `lib.rs` | compatibility records and deterministic snapshots | durable history, authentication |
| `hnmf.rs` | multimodal assets, spans, events, provenance | asset storage, parser indexes |
| `hnmf_learning.rs` | engrams, synapses, recall, learning proposals | learning policy activation |
| `lane_c.rs` | Lane C local exchange types | product writer authority |
| `strict.rs` | cross-field invariants and selector-resolution checks | fetching selector indexes |
| `wire.rs` | canonical JSON V1 codec | schema negotiation |
| `registry.rs` | closed schema/version/contract allow-list | dynamic plugin registration |
| `contract.rs` | structured violations, `Validated<T>`, digest-domain metadata | authorization |
| `write_receipt.rs` | fully bound tagged write receipts | executing a write |
| `consumer.rs` | named consumer bindings, shadow and cutover accounting | enabling cutover |

## 4. Memory-write path

The existing Lane C `MemoryWriteReceiptV1` remains a migration input. The authoritative canonical receipt is `write_receipt::MemoryWriteReceiptV1`.

The canonical receipt binds:

- intent identity and complete intent digest;
- candidate digest;
- authorization digest;
- writer-fence digest;
- expected snapshot digest and memory frontier;
- writer identity and issue time;
- committed record/snapshot outcome or structured rejection;
- a self digest bound to schema, version, canonicalization, Unicode policy and digest algorithm.

Rejection is a tagged outcome and cannot carry fabricated record identity.

`hepta-cognitive-store::CanonicalCognitiveStoreV1Ext` invokes the existing authenticated `AdmittedCognitiveStoreV2::append_admitted` path, upgrades its compatibility receipt, verifies closed-registry round-trip decoding and emits a shadow-equivalence receipt. It does not create a second writer.

## 5. Consumer architecture

The closed convergence registry names five consumers:

| Consumer | Canonical role | Current migration mechanism |
|---|---|---|
| `cognitive.read` | canonical event/binding/forget input | registered decode adapter and compile contract |
| `cognitive.store` | canonical event input and strong write-receipt output | authenticated writer adapter plus shadow equivalence |
| `memory.retrieval` | canonical cue input and recall output | registered decode/encode binding |
| `compact.engine` | canonical event/forget input | registered input binding |
| `intelligence.control` | canonical recall/outcome input | registered input binding |

Each profile records the owner, legacy surfaces, canonical schemas, mismatch metric, cutover gate and rollback. Registration proves the intended boundary. Production cutover still requires exact-head evidence and a consumer-owned call site.

## 6. Selector resolution

Shape validation proves that a selector is bounded and syntactically well formed. Existence and bounds for AST paths, GUI nodes and JSON pointers require `SelectorResolutionContextV1`, which binds an asset manifest and selector-index digest to the allowed selector set.

No document or caller may claim that a bare `ModalitySpanRefV1::validate()` proves target existence.

## 7. Compatibility policy

Legacy digests remain byte-compatible. New authority-bearing paths use the domain-bound digest profile. Additive adapters may coexist during shadow migration, but authoritative consumers must not silently reinterpret a legacy local type as a canonical wire contract.

See `SCHEMA_EVOLUTION.md`, `MIGRATION.md` and `WIRE_CONTRACT.md`.
