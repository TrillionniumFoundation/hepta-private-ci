# cognitive.read compiled contract limits and compatibility

This file is a machine-checked companion to `TECHNICAL.md`. Rust tests include
this file at compile time so a contract-limit change cannot silently drift from
the developer documentation.

## Compiled limits

```text
MAX_READ_IDS_V1 = 512
MAX_ENCODED_READ_RESULT_BYTES_V2 = 1048576
MAX_COGNITIVE_CONTEXT_BYTES = 8192
MAX_SELECTED_CONTEXT_RECORDS = 4
```

The exact-ID ceiling applies to `total_encoded_bytes`, not merely the record
payload. `payload_encoded_bytes` is the canonical prefix covered by the receipt
digest. `total_encoded_bytes` includes that payload and the trailing 32-byte
receipt digest. Requests are rejected before citation/projection cloning when
the precomputed total exceeds the caller ceiling.

Every result remains `AuthorityPosture::DENY_ALL`.

## Type and authority boundary

`TransientSnapshotProjectionV1` identifies a projection over caller-supplied,
locally consistent bytes. It proves neither owner identity, caller access,
completeness, freshness nor revocation state. Product attachment requires the
source-owned Lane C cut and `cognitive.context.revalidate@1` immediately before
final use.

## Canonical compatibility matrix

| Surface | Current version | Compatibility rule |
|---|---:|---|
| Exact-ID request binding | `hepta.cognitive.read.ids.request.v1` | Field and ID order are canonicalized; semantic additions require a new domain/version. |
| Exact-ID result payload | `hepta.cognitive.read.ids.v1` | Internal typed-local integrity representation; not a public wire protocol. |
| Snapshot digest | `hepta.cognitive.snapshot.v1` | Consumed as an opaque source-owned digest. |
| Final-use capability | `cognitive.context.revalidate@1` | Required for model attachment; absence or stale bindings fail closed. |
| Golden vector set | `cognitive-read-golden-v1` | Any byte change requires an explicit compatibility review and vector-version update. |

## Activation

`activation=false` remains mandatory until the exact candidate commit has green
`CI required` and `Architecture required` checks, immutable qualification logs,
artifact digests and product smoke/replay evidence. Source implementation or
golden-vector success alone does not activate production authority.
