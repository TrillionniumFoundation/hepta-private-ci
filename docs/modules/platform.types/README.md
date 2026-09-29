# platform.types

This directory is the single documentation entry point for `platform.types`.
Start with [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) for current
source and claim boundaries. The [technical guide](TECHNICAL.md) retains the
architecture, ownership and work-package history. Read the
[protocol contract](PROTOCOL_AND_QUALIFICATION_V1.md) for versioned identities,
transport and owner-pinned verification, and the
[2026-09-29 closure](OPTIMIZATION_CLOSURE_20260929.md) for Prompt capacity,
streaming/capacity optimizations, tests, performance methodology and acceptance.

Native Rust contracts and the compiled catalog govern protocol semantics.
Generated inventories are navigation; successful candidate receipts and eligible
independent review are separate evidence. Source existence is not activation.

## Version and compatibility status

| Contract | Current status | Identity and compatibility rule |
|---|---|---|
| `PromptDeliveryObservationV1` | Frozen, supported compatibility contract | Retains its original custom domain-separated commitment. It is not relabeled as HPTC and existing bytes are never reinterpreted. |
| `PromptDeliveryObservationV2` | Current versioned contract | Private-field HPTC schema 2 with an optional exact V1-digest migration witness. Migration rejects unsupported capacity instead of truncating. |
| `RuntimeTopologyCandidateV1` | Current supported contract | Native construction, canonical delta order and full safety-relevant semantic commitment are required before the strict wire codec returns a validated candidate. |
| `RegisteredNumericConversionReceiptV1` | Supported compatibility contract | Preserved for existing callers; it does not substitute for the generation-bound V2 witness. |
| `RegisteredNumericConversionReceiptV2` | Current generation-bound contract | Binds registry generation/content, profile definitions, normalization definition and the base conversion receipt; final owners reverify against an independently pinned snapshot. |
| `RandomStreamManifestV1`, `ExternalSystemManifestV1`, `SensorCalibrationManifestV1` | Current supported contracts | Native private-field validation, strict product JSON codecs, HPTC identity and named owner admission are required. |

No contract in this table grants execution, registry publication, activation,
promotion or release authority. Compatibility status means the bytes and
verification behavior remain supported; it does not mean every product caller
has migrated to the newest version.

## Exact candidate evidence

The committed public inventory and detailed implementation map are content-derived
source documents. A committed file cannot safely claim its own final Git commit
hash, because changing that file changes the commit. Therefore final qualification
does not treat a historical `sourceBase` or `observedAtHead` field as the candidate
receipt.

For every source-head and deterministic synthetic-merge run,
`scripts/platform_types_implementation_map.py` emits a candidate artifact that
binds the exact checked-out commit and tree plus the SHA-256 digests of the
committed public inventory and detailed implementation map. The property report
repeats that binding, and the final qualification receipt rejects any mismatch
with its own exact candidate identity. This is the authoritative exact-head
binding used by qualification.

Manual qualification workflows select executable bytes through GitHub's workflow
ref picker and `github.sha`; free-form workflow inputs cannot control checkout
refs. Resolved full object IDs are then frozen and reused by both source-head and
synthetic-merge jobs.

## Current boundary

The supported foundation remains authority-free and stateless. Prompt V1 bytes
remain frozen. Prompt V2 now admits only values within its frozen HPTC array
capacity; larger V1 observations are retained as V1, never silently truncated.

The [qualification integrity continuation](QUALIFICATION_INTEGRITY_20260929.md)
defines resource-attempt publication, stale-report rejection, independently
recomputed consumer test counts, candidate-bound implementation-map evidence and
the existing-lane guard regressions.

Completion still requires successful exact source-head and synthetic-merge
receipts for the same final source SHA, zero generated-file drift, current-head
eligible independent approval and the applicable owner/target-host evidence.
Those gates cannot be replaced by hand-edited lifecycle booleans or retained
failure diagnostics.
