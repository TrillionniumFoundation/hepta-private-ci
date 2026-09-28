# `cognitive.read` compiled limits and compatibility contract

This file is the human-readable mirror of limits compiled into the read crate and its Agentd product composition. `scripts/verify-cognitive-read-constants.py` parses the Rust declarations directly and requires the following block to match exactly.

```text
MAX_READ_IDS_V1 = 512
MAX_ENCODED_READ_RESULT_BYTES_V2 = 1048576
MAX_COGNITIVE_CONTEXT_BYTES = 8192
MAX_SELECTED_CONTEXT_RECORDS = 4
REVALIDATION_ALERT_THRESHOLD_PER_MINUTE = 3
REVALIDATION_ALERT_WINDOW_SECONDS = 60
```

## Byte accounting

`payload_encoded_bytes` is the complete canonical body covered by the receipt digest. It excludes only the trailing 32-byte receipt digest, not the body's envelope fields. `total_encoded_bytes` includes those trailing 32 bytes. Admission is checked against `total_encoded_bytes` before projected records or citations are cloned. These are module-local integrity bytes, not an admitted cross-process wire protocol.

The Agentd context compiler measures the final JSON shape, including the plan envelope and both possible `read_allowed` values, before accepting each item. A final serialization assertion prevents publication above `MAX_COGNITIVE_CONTEXT_BYTES`. The product path admits at most `MAX_SELECTED_CONTEXT_RECORDS` records.

## Authority and type boundary

Every direct snapshot projection has `AuthorityPosture::DENY_ALL`. `TransientSnapshotProjectionV1` and `TransientReadIdsResultV1` distinguish caller-supplied projections. `PreparedReadSnapshotV1` reuses immutable structural validation only. Agentd's private `OwnerCutReadView` binds that view to one already acquired durable cut inside a single request. Neither kind of view is production authority. The worker must repeat `cognitive.context.revalidate@1` immediately before physical `TurnStart`, using a newly acquired owner cut.

## Compatibility matrix

| Contract | Current version | Compatibility rule |
|---|---:|---|
| Exact-ID request/result | V1 | Golden bytes remain unchanged; semantic or canonical-layout changes require a new version. |
| Prepared structural view | V1 | Borrow-scoped local API; no cache of authorization or freshness and no serialized representation. |
| Owner-local cache envelope | V2 | Decode, length, schema, authority, receipt, and digest checks are fail-closed. It is not a public wire protocol. |
| Receipt digest | V1 domains | Any covered-field change must alter the golden vector. Domain changes require an explicit compatibility entry. |
| Agentd context envelope | Product-local | Exact final JSON bytes are bounded; new fields must update boundary tests and source-map evidence. |
| Revalidation alert | V1 event | Only low-cardinality reason codes are allowed; threshold/window changes must update this file and the operations runbook. |

Golden vectors live in `qualification/cognitive-read/golden/cognitive_read_vectors.json` and are exercised by the crate's golden-vector tests. Property, fuzz-style, mutation, envelope-boundary, prepared-parity, benchmark, and product replay tests are part of the qualification inventory.

## Qualification and activation

`activation=false` remains mandatory until the exact candidate has successful required repository checks, source-head and deterministic synthetic-merge suites, immutable matching evidence, and independent acceptance. Qualification V2 requires the complete mandatory command inventory and valid measurements, not an arbitrary nonempty subset of successful exit codes. See `STRUCTURAL_REUSE.md` for measurement boundaries and `CONSUMERS.md` for the exact-candidate consumer matrix.

The named repository aggregate gates remain `CI required` and `Architecture required`; module-local qualification does not replace them.

Operational signal names, alert routing, and the incident runbook are defined in `OPERATIONS.md`. The error event is `cognitive_context_revalidation_alert`.
