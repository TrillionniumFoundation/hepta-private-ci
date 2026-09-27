# cognitive.read Compatibility Matrix

This file is the compatibility contract for cognitive.read receipts, local codecs, product bindings, and qualification evidence. It does not activate the module. `activation=false` remains mandatory until exact-head and deterministic synthetic-merge qualification both pass and independent acceptance is recorded.

## Version matrix

| Surface | Current version/domain | Compatibility promise | Reader behavior | Writer behavior |
|---|---|---|---|---|
| Exact-ID request binding | `hepta.cognitive.read.ids.request.v1` | Stable inside V1. Every requested ID, requested field, snapshot digest, and byte ceiling is bound. | Reject duplicate IDs, duplicate fields, unsupported limits, malformed identities, and snapshot mismatch. | Emit deterministically sorted IDs and fields. Never silently truncate. |
| Exact-ID canonical receipt | `hepta.cognitive.read.ids.v1` | Stable canonical byte layout for V1. `payload_encoded_bytes` excludes only the trailing receipt digest; `total_encoded_bytes` includes it. | Recompute the payload digest and require the trailing 32-byte digest to match. Unknown layouts fail closed. | Enforce the total canonical-byte ceiling before cloning projected records or citations. |
| Read V2 local codec | `ReadRequestV2` / `ReadResultV2` | Owner-local compatibility surface only; it is not a public cross-module wire protocol. | Validate schema, bounds, authority posture, receipt, and cache freshness on every decode or cache hit. | Do not extend fields in place. Introduce V3 for an incompatible local layout. |
| Transient projection | `TransientSnapshotProjectionV1` | Source-compatible V1 wrapper with permanently authority-free results. | Treat every result as `AuthorityPosture::DENY_ALL`; never infer owner completeness or freshness. | Product code must prefer an owner-acquired cut plus final-use revalidation. |
| Agentd selected-read binding | `hepta.agentd.cognitive-context-read.v1` | Product-local V1 binding of owner cut, selected records, and retrieval execution context. | Reject changed generation, record revision, content digest, scope, or retrieval-context binding. | Recompute immediately before publication and again at the native worker boundary. |
| Worker revalidation message | `cognitive.context.revalidate@1` | Stable control-message name and V1 field semantics. | Unknown message versions or stale host generations fail closed before model-request attachment. | Send only after a bounded context has passed owner and Agentd revalidation. |
| Golden vector file | `hepta.cognitive.read.golden-vector.v1` | Byte-for-byte fixture for one live plus one missing exact-ID read. | Compare snapshot, request binding, payload length, total length, receipt, and canonical hex. | A changed vector requires an explicit new schema/domain or a reviewed compatibility decision. |
| Qualification receipt | `hepta.cognitive.read.qualification.v1` | Immutable evidence manifest for one exact commit/tree and one workflow attempt. | Require complete SHA/tree identity, command exit codes, artifact hashes, clean tracked worktree, and `activation=false`. | Emit separately for source head and deterministic synthetic merge. Never copy a receipt to a different commit. |
| Benchmark record | `hepta.cognitive.read.benchmark.v1` | Measurement schema, not a performance guarantee. | Compare only runs with the same commit, toolchain, host class, record count, requested-ID count, and iteration count. | Record p50/p95/p99 and peak RSS when the host exposes it. |

## Evolution rules

1. Domain-separated digests are immutable within a version. A semantic or byte-layout change requires a new domain/version.
2. Decoders and validators fail closed on unknown versions; there is no best-effort downgrade.
3. Cache entries never carry authority and must be revalidated against the current owner state before use.
4. Golden vectors are reviewed protocol artifacts. Updating expected bytes merely to make a test green is forbidden.
5. Qualification receipts bind one exact commit and tree. Rebases, dependency changes, workflow changes, or implementation-map changes require fresh receipts.
6. A successful source-head receipt does not substitute for synthetic-merge qualification, product smoke/replay, independent review, canary, or release approval.
7. `activation=false`, `productExecutionProved=false`, and `productionImplementation=false` remain truthful until all repository and external evidence gates are closed.

## Supported transitions

| From | To | Allowed automatically? | Required evidence |
|---|---|---:|---|
| Exact-ID V1 | Exact-ID V1 with implementation-only optimization | Yes | Golden vectors unchanged; property, mutation, fuzz, boundary, and product replay tests pass. |
| Exact-ID V1 | Exact-ID V2 | No | New domain, new golden vectors, compatibility review, dual-read migration plan, and exact-head plus merge-candidate receipts. |
| Local Read V2 codec | Local Read V3 codec | No | Explicit cache invalidation/migration rules and hostile decode tests. |
| `cognitive.context.revalidate@1` | `@2` | No | Agentd, protocol, infer-core, native-worker, replay, stale-generation, and rollback tests qualified together. |
| Qualification receipt V1 | V2 | No | Evidence consumer migration and retained V1 verification support for historical receipts. |
| `activation=false` | `activation=true` | Never by schema migration alone | Required checks green on the exact candidate, immutable artifacts published, independent acceptance, canary, promotion, and release approval. |
