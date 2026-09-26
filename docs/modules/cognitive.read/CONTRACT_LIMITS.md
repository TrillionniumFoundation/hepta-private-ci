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

`payload_encoded_bytes` is the canonical encoded body before receipt and envelope bookkeeping. `total_encoded_bytes` is the complete canonical wire result, including the trailing 32-byte receipt and every envelope field. Admission is checked against `total_encoded_bytes`; callers must not reinterpret the payload count as a wire-size guarantee.

The Agentd context compiler measures the final JSON shape, including the plan envelope and both possible `read_allowed` values, before accepting each item. A final serialization assertion prevents publication above `MAX_COGNITIVE_CONTEXT_BYTES`. The product path admits at most `MAX_SELECTED_CONTEXT_RECORDS` records.

## Authority and type boundary

Every direct snapshot projection has `AuthorityPosture::DENY_ALL`. `TransientSnapshotProjectionV1` and `TransientReadIdsResultV1` make caller-supplied, locally consistent snapshots distinguishable from an owner-acquired cut. A transient projection is never sufficient production authority. The worker must repeat `cognitive.context.revalidate@1` immediately before physical `TurnStart`.

## Compatibility matrix

| Contract | Current version | Compatibility rule |
|---|---:|---|
| Exact-ID request/result | V1 | Additive fields require canonical golden-vector updates; semantic changes require a new version. |
| Owner-local cache envelope | V2 | Decode, length, schema, authority, receipt, and digest checks are fail-closed. It is not a public wire protocol. |
| Receipt digest | V1 domains | Any covered-field change must alter the golden vector. Domain changes require an explicit compatibility entry. |
| Agentd context envelope | Product-local | Exact final JSON bytes are bounded; new fields must update boundary tests and source-map evidence. |
| Revalidation alert | V1 event | Only low-cardinality reason codes are allowed; threshold/window changes must update this file and the operations runbook. |

Golden vectors live in `qualification/cognitive-read/golden/cognitive_read_vectors.json` and are exercised by the crate's golden-vector tests. Property, fuzz-style, mutation, envelope-boundary, benchmark, and product replay tests are part of the exact source map.

## Qualification and activation

`activation=false` remains mandatory until the exact candidate has successful `CI required` and `Architecture required` checks, the focused cognitive-read exact-head workflow and deterministic synthetic-merge workflow have succeeded, and their immutable evidence bundles match the published SHA-256 manifests and artifact digests.

Operational signal names, alert routing, and the incident runbook are defined in [`OPERATIONS.md`](OPERATIONS.md). The error event is `cognitive_context_revalidation_alert`.
