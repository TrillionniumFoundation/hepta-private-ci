# Native integration status

This change adds executable qualification and native contracts. It does not
claim a production organ/TaskFlow memory-cell loop.

| Boundary | Implemented and executed | Production work still required |
|---|---|---|
| Typed request/readout | `hepta-cognitive-types/src/memory_cell.rs` decodes bounded requests and readouts, preserves source/model distinctions, and rejects incomplete success/failure envelopes. | Map the product's canonical scope/entity identifiers and request lifecycle to these contracts. The language router remains a qualification implementation. |
| Source-owner verification | `hepta-memory-retrieval/src/memory_cell.rs` checks query, generation, snapshot and execution budgets, then invokes `MemorySourceVerifierV1` for every source. Tests exercise scope/entity mismatch and revoked dependencies. | Implement this trait against the authenticated current cognitive owner; caller-provided digests or an arbitrary owner JSON export cannot establish authority or freshness. |
| Existing SQLite owner | The repository already has `CognitiveStore` and `hepta-memory/src/cognitive_retrieval_adapter.rs::execute_owner_observation`, which binds canonical owner observations to a durable cognitive cut and generation vector. | That adapter has not been changed to consume the new parametric `MemoryReadoutV1`. Add the source-ID mapping, principal/scope checks, current revocation/frontier verification and final-use revalidation there or in an owner-controlled sibling adapter. |
| Context compilation | `native/bridge.rs` is a real caller: Python-trained three-cell readout → Rust decode → fixture owner verifier → `hepta-context-compiler::compile`. Its executed receipt has value 290, `mixed`, one `UntrustedEvidence` item, no trusted instruction and no authority. | Replace the fixture owner with the live owner path and carry prediction/provenance labels into the actual context realization. The bridge uses the V1 digest compiler; it does not perform V2 admission, serialization, exact tokenization or provider delivery. |
| Parameter/version publication | The Python qualification uses an actual SQLite single-writer CAS pointer, immutable cell objects, coherent bundle digests, source cuts and complete lineage. Lifecycle experiments copy complete bundles to independent directories and reject mixed versions. | Bind these transitions to the production learning artifacts/ledger owners and their capabilities, release/admission receipts and rollback lifecycle. The qualification `ArtifactOwner` is not that production adapter. |
| Multi-node lifecycle | Local HTTP node processes, independent files, real process death/restart, explicit source replay and complete-bundle redistribution are exercised and measured. | No cross-host deployment, network partition protocol, consensus, authenticated transport or automatic distributed revocation is wired. Uninformed independent replicas may still serve their old coherent copy; the experiment records this gap before explicit delivery. |
| Organ / TaskFlow | The qualification invokes existing native libraries and records their results. | There is no new production organ scheduling hook, TaskFlow executor edge, approval/lease transition or provider invocation consuming these memory cells. Those callers require a separate integration change and product-level tests. |

The native evidence is a six-crate leaf build with unchanged Rust source bytes
and external dependency versions/checksums constrained to the repository lock.
It passed 127 tests and ran the bridge with both a successful owner export and a
revoked export. Two existing target-host probes remain ignored. This validates
the native boundary and the qualification caller, not a complete product build.

Keep three distinctions in status reports: library contract versus production
caller; prediction with source dependencies versus independently proven fact;
explicit replica delivery versus automatic distributed consistency. A passing
qualification receipt does not remove any of these remaining integration steps.
