# prompt.registry qualification status

## Current candidate

This delivery candidate is implemented in checked-in Rust source. No source
patcher or map generator runs during qualification. The native registry and
Agentd/extension current-use integration are source-composed, not a claim of
production activation. The real global development plan is
`docs/DEVELOPMENT.md`, selected by `docs/CURRENT.json`.

| State | Value |
| --- | --- |
| sourceImplemented | true |
| sourceComposed | true |
| productActivated | false |
| independentlyAccepted | false |
| productionReady | false |
| released | false |

Source existence is not an executed test receipt. Required exact-head and
bound-base synthetic-merge checks must be read for their actual source/tree,
profile, job run/attempt, executed tests, exit codes and postconditions.
A core-only pass does not imply that the product profile passed. Historical,
queued, cancelled, timed-out, zero-test or unrelated results are not passes.
The workflow `.github/workflows/hepta-prompt-registry-qualification.yml` uses
`--check` for the committed implementation map and writes all evidence outside
the checkout. Its receipt never self-accepts, activates, promotes or releases.

## Implemented changes and boundaries

Current-use validation is shared by preparation and the locked durable dispatch
claim; cached ready contexts reconsult the owner and cannot silently replace
the already injected payload. Stable typed errors distinguish withdrawal,
identity/expiry drift, poisoned owners, indeterminate commits and capacity.
Actual terminal provider outcomes remain truthful.

Checkpoint copy-compaction omits inactive payload bytes, retains audit facts,
checks retained-history equality and is idempotent for identical completed
checkpoints. Restore verification requires a trusted exact identity and does
not initialize, migrate, trim or repair the candidate. Checkpoint receipts
explicitly state source_erased=false. They do not switch the live owner or erase
old source/backup bytes. Operational metrics remain diagnostic when poisoned.

## Remaining gates, not implicit completion

- Passing core AND product profiles on the final exact-head AND synthetic merge.
- Actual transport/stream/final-output cancellation semantics beyond the durable
  dispatch-claim boundary, under the deployed provider/host configuration.
- Externally fenced checkpoint handoff and approved disposal of original/backup
  raw bytes; copy-compaction alone is not erasure.
- A versioned durable GC-age policy; currently oldest-reclaimable age is unknown.
- Independent target-host security/semantic review, protected postmerge checks,
  operator activation, acceptance and release.

## Developer references

- `API_CONTRACT.md`: real Rust operations, identity fields, error/retry policy.
- `OPERATIONS.md`: retention, checkpoint, non-mutating restore and incident handling.
- `PERFORMANCE.md`: native measured paths, sample counts and non-SLA interpretation.
- `IMPLEMENTATION_MAP.json`: generated operation/test/caller/blob navigation.

The mainline integration anchor is
`a126987b84737dbc2ee2592442a314117bddb4a2`. Actual current execution identity is
bound by each receipt, not inferred from this human-readable status document.


## Verified-closeout candidate scope

Branch `codex/prompt-registry-verified-closeout-20260928` adds owner-local V5
payload GC with retained V4 semantic/audit history, shared typed recovery
classification, integrity-safe final-use mapping, actual I/O counters, measured
collection profiles and fail-closed four-lane receipt aggregation. These are
source changes until the same candidate's native and product checks execute.
The earlier delivery-consistency branch's results are predecessor diagnostics,
not receipts for this branch. Do not infer activation, acceptance, release,
streaming-output cancellation, secure device erasure or historical GC age from
these changes. Oldest-reclaimable age remains unknown without a durable clock
policy. Use current workflow artifacts for pass/fail/not-run status.

## Machine-generated implementation status

<!-- prompt.registry generated-status:begin -->

| Generated field | Value |
| --- | --- |
| `sourceImplemented` | `true` |
| `sourceComposed` | `true` |
| `closedWorldPublicFunctions` | `false` |
| `nativeSourceMappingComplete` | `false` |
| `productExecutionProved` | `false` |
| `independentlyAccepted` | `false` |
| `productActivated` | `false` |
| `productionReady` | `false` |
| `released` | `false` |
| `activePersistentSchemas` | `4, 5` |
| `semanticSchema` | `4` |
| `payloadGenerationSchema` | `5` |

This block is generated from `IMPLEMENTATION_MAP.json`. When either `productExecutionProved` or `closedWorldPublicFunctions` is false, this document cannot claim production completion.

<!-- prompt.registry generated-status:end -->
