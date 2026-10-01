# cognitive.read Compatibility Matrix

This is the compatibility contract for receipts, local codecs, product bindings,
and qualification evidence. It does not activate the module. Activation remains
false until exact-head and deterministic synthetic-merge qualification pass and
independent acceptance is recorded.

## Version matrix

| Surface | Current version/domain | Compatibility promise | Reader behavior | Writer behavior |
|---|---|---|---|---|
| Exact-ID request binding | `hepta.cognitive.read.ids.request.v1` | Stable inside V1; IDs, fields, snapshot and byte ceiling are bound | Reject duplicates, invalid bounds and snapshot mismatch | Sort IDs/fields; never silently truncate |
| Exact-ID canonical receipt | `hepta.cognitive.read.ids.v1` | Unchanged V1 layout; payload excludes only trailing digest | Local integrity only, not source authentication | Enforce total bytes before projection/citation cloning |
| Prepared structural view | `PreparedReadSnapshotV1` | Additive borrow-scoped Rust API; same V1 bytes | Repeat request checks, retain immutable snapshot identity | Do not serialize or store grants/currentness in the view |
| Product cut view | Agentd private `OwnerCutReadView` | One acquired cut per request | Final use reacquires a current cut and creates a new view | Do not share across principals, scopes or requests |
| Read V2 local codec | `ReadRequestV2` / `ReadResultV2` | Owner-local compatibility, not public wire | Validate schema, bounds, authority, receipt; owner must separately establish currentness | Incompatible layout requires V3 |
| Transient projection | `TransientSnapshotProjectionV1` | Source-compatible authority-free wrapper | Never infer completeness or freshness | Product code uses an owner cut and final-use revalidation |
| Canonical shadow V1 | `hepta.cognitive.authoritative-read.canonical-shadow.v1` | Existing ID/digest/lifecycle shadow remains unchanged | Treat source-revision equivalence as unknown | Do not invent or default a legacy citation revision |
| Revision-bound canonical shadow V2 | `hepta.cognitive.authoritative-read.canonical-shadow.v2` | Additive local Rust surface; V1 bytes are unchanged | Require exact owner-issued source ID/revision/digest bindings and matching canonical provenance | Fail closed on missing, duplicate, zero, substituted or drifted revisions; never treat the shadow as final-use authority or wire |
| Agentd selected-read binding | `hepta.agentd.cognitive-context-read.v1` | Owner cut, selected records and retrieval execution context | Reject generation, revision, content, scope or context drift | Recompute at publication and native worker boundary |
| Prepared context handoff | `cognitive.context.prepare@1` | Additive control schema 2 method/payload; receipt outside unchanged snapshot | Require capability, exact RPC/receipt and witnessed namespace; missing is not zero exposure | Persist optional receipt in existing native journal; historical omission retains bytes |
| Worker revalidation | `cognitive.context.revalidate@1` | Stable control message and field semantics | Unknown versions and stale host generations fail closed | Use only with bounded owner-validated context |
| Golden vector | `hepta.cognitive.read.golden-vector.v1` | One live plus one missing exact-ID read | Compare all digests, lengths and canonical bytes | Never change expected values solely to make tests pass |
| Qualification receipt | `hepta.cognitive.read.qualification.v2` | Exact candidate, complete command inventory, consumer gate states and hashed evidence | Require all gates, exact argv, logs, exits, named semantic PASS rows, nonzero test execution and valid measurements | Emit separately for source and merge; no source changes |
| Historical qualification | `hepta.cognitive.read.qualification.v1` | Retained historical format only | Do not interpret old subset-success semantics as V2 qualification | Never relabel or rebind a V1 receipt to a new candidate |
| Baseline benchmark | `hepta.cognitive.read.benchmark.v1` | Measurement schema, not performance guarantee | Compare equivalent commit/toolchain/host/workload | Preserve actual p50/p95/p99 and available process RSS |
| Prepared benchmark | `hepta.cognitive.read.prepared-benchmark.v1` | Equivalent paired projections; construction cost included | Validate the full workload matrix and distinguish warm-only measurements | Record actual empirical distributions; no invented speedup |
| SQLite owner capacity | `hepta.cognitive.read.sqlite-capacity.v1` | Exact-candidate host measurement, not a portable SLA | Require 512 records/IDs, 32 iterations, monotone p50/p95/p99, SQLite rows/pages, CPU and RSS | Run the real owner path and bind the current commit/tree; never infer target-host acceptance |
| Consumer audit | `hepta.cognitive.read.consumer-audit.v1` | Registry plus exact source blobs | Lexical references are not compiled or executed migrations | Emit per candidate; keep acceptance fields false |
| Consumer execution map | `hepta.cognitive.read.consumer-execution.v1` | Per-consumer required gates and interpretation | Preserve registered/composed/product-qualified distinctions | Never convert package success into V2 migration or activation |

## Evolution rules

1. Domain-separated digests and canonical layouts are immutable within a version.
2. Unknown layouts fail closed; there is no best-effort protocol downgrade.
3. No read view, shadow or cache entry carries authority. Owner-currentness is rechecked.
4. Golden vectors are reviewed integrity fixtures, not deployment permission.
5. Source, dependency, workflow or source-map changes require new evidence.
6. Source-head qualification never substitutes for merge qualification, real
   product behavior, independent review, canary or release approval.
7. Module activation, product proof and production implementation remain false
   until their respective repository and external evidence gates are closed.
8. V2 source-revision shadow evidence is accepted only with an explicit owner-issued
   bridge. Legacy V1 citations remain partial and are never upgraded by inference.

## Supported transitions

| From | To | Automatic? | Required evidence |
|---|---|---:|---|
| Exact-ID V1 | Prepared implementation using unchanged V1 bytes | Source optimization only | Golden/parity, mutation, hostile input, boundary and product tests |
| Exact-ID V1 | New request/receipt version | No | New domain, vectors, review, dual-read migration and exact-candidate receipts |
| Canonical shadow V1 | Revision-bound canonical shadow V2 | No implicit conversion | Explicit owner-issued source revision bindings, V2 domain, success/tamper tests and exact source/merge receipts |
| Local codec V2 | Local codec V3 | No | Explicit cache invalidation/migration and hostile decode tests |
| Worker revalidation @1 | @2 | No | Agentd/protocol/infer-core/worker/replay/generation/rollback tests together |
| Qualification V1 | V2 | No historical conversion | Fresh complete execution, gate-validator regressions, retained historical V1 interpretation |
| Activation false | Activation true | Never by schema/source edit alone | Required checks, immutable artifacts, independent acceptance and release process |

V1 legacy citations still do not carry source revisions. The additive V2 shadow closes this
only when an owner supplies an exact revision bridge; it does not change the owner schema,
compose a product caller, grant final-use authority, or admit canonical bytes as a transport
protocol.

`activation=false` remains required. Golden vectors are reviewed protocol artifacts
for local integrity conformance, not admission of a network wire format. The activation
rule remains **Never by schema migration alone**; source edits also cannot activate the module.
