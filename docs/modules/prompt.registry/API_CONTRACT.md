# prompt.registry API, identity, and failure contract

This guide describes the committed Rust implementation, not an RPC service or
a deployed capability. The canonical global plan is `docs/DEVELOPMENT.md`
(`HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` 8.0.0); `docs/CURRENT.json` identifies
that document set. Runtime activation and release remain independent decisions.

## 1. Owners and authoritative facts

`PromptRegistry` is the deterministic domain core. `DurablePromptRegistry` is
its single durable writer under a private state-directory lock.
`AgentdPromptPipelineOwner`, in `codex-rs/hepta-agentd/src/prompt_runtime.rs`,
composes that writer, the durable staged-context/dispatch store, and the
final-use lease store. The optimizer consumes read-only snapshots. There is no
separate `prompt_pipeline.rs` implementation and no mutable singleton.

The actual factor lifecycle is `Draft`, `Admitted`, `Retired`, `Revoked`.
`Revoked` is terminal. This implementation does not expose the previously
reported `Enabled/Parked/Disabled/Tombstoned/Deleted` lifecycle or a generic
`upsert/render` registry service. A missing grant, incompatible identity, or
unknown durable schema is not interpreted as permission.

| Operation | Domain transition and authority | Durable result |
| --- | --- | --- |
| `register_factor_final_use` | Register bounded draft identity with a signed, operation-bound grant | One registry revision, or identical retry without a new revision |
| `admit_factor_final_use` | Independently admit a governed internal draft; proposer cannot self-review | Admission evidence, reviewed scope, grant lineage, and lifecycle event |
| `register_factor_relation_final_use` | Register canonical live governed endpoints and evidence | Relation stored in the strict V4 image |
| `register_realization_payload_final_use_v2` | Publish an exact model-specific binding and matching bounded payload | Immutable payload extent before atomic metadata selection |
| `retire_factor_final_use` | Admitted factor becomes retired under signed actor/scope/reason binding | Associated realizations become inactive |
| `revoke_factor_final_use` | Non-revoked factor becomes permanently revoked under signed actor/scope/reason/cutoff binding | Revocation frontier and lifecycle event survive reopen |
| `snapshot_v2` / `read_compatible_v2` | Read exact registry/model/generation compatibility | Read evidence, not effect authority |
| `dereference_realization_v2` | Revalidate snapshot, binding, lifecycle, expiry, and payload digest | Bounded owned payload bytes or rejection |

The Agentd facade exposes governed `publish_factor`, `admit_factor`,
`publish_realization`, `publish_relation`, `retire_factor`, and `revoke_factor`.
No production ingress should substitute raw draft-registration helpers for the
signed product path. Grant consumption and registry persistence are distinct
owners: an indeterminate registry outcome requires reconciliation, not blind
resubmission of a spent grant.

## 2. Identity components

Factor semantic identity and realization identity are different. A realization
binds model ID/version, model digest, tokenizer, template, tool schema, context
profile, locale, role, payload digest, token cost, and optional expiry.
Supersession is explicit; insertion does not automatically select a factor.
The registry record ceiling is 16,384 logical records, with the selected owner
configuration allowed to impose a lower ceiling. Maximum realization payload
is 64 KiB. Metadata and selected payload extents have separate 32 MiB ceilings;
the physical extent file additionally contains its fixed header.

`PromptFinalUseLeaseV1` retains its version-1 digest domain. It binds the
compilation ID, context attachment/payload digests, registry snapshot,
generation vector, complete model tuple, issuance/deadline, and sorted unique
realization selections. At most 128 selections are accepted. Duplicate
realization IDs are rejected even when an attacker changes the paired factor
ID. Recomputing a lease checksum does not authorize changed payload bytes.

`PromptFinalUseBoundaryV1` carries the compilation and context identities
observed at the consuming boundary plus the trusted host clock. Its
`validate_at_boundary` operation first binds those identities, then checks the
current registry and selected payloads. `PromptFinalUseValidator` adds bounded,
owner-local timing and rejection counters; counters never authorize a use.

A lease binds the generation and model tuple supplied by the registered
compilation path. It is not an independently refreshed model-configuration
oracle or an owner-epoch service. The embedding must bind its real current
configuration; it must not manufacture a current generation from an old lease.

## 3. Preparation, cached reuse, dispatch, and terminal facts

Preparation now invokes the same current-use validator used by the durable
dispatch claim. Revocation, retirement, expiry, changed snapshots, missing
payloads, or a poisoned registry prevent exposure of a staged attachment.
The clock is read after taking the registry-owner lock. A caller cannot keep
an expired lease alive merely by backdating a dispatch timestamp.

The prompt extension reconsults the owner before reusing a cached ready
attachment. The attachment must remain byte/identity-equivalent to what was
injected. Removal, withdrawal, or changed bindings fail closed rather than
silently substituting a new prompt into the already assembled turn. A previous
absence does not self-activate a later insertion in the same turn.

The dispatch claim holds the registry-owner mutex through current validation
and durable dispatch recording. Identical durable attempt retries preserve the
original identity. Conflicting attempt reuse is rejected; unresolved attempts
require reconciliation. The provider adapter binds the attempt to the physical
request digest before allowing its provider policy path to proceed.

**Linearization boundary:** these checks establish current-use validity at
preparation and at the durable dispatch claim. They do not prove cancellation
of network I/O already admitted by that claim, retract already streamed bytes,
or independently fence every downstream output consumer. A later revocation
must not make an already observed provider delivery disappear from the audit
record. Terminal delivery/rejection/indeterminate facts continue to be recorded
truthfully. Actual transport/output cancellation and deployed provider behavior
need their own integration proof; a unit test is not that proof.

## 4. Stable final-use error policy

Callers should branch on `code()` / `recovery()`, not parse diagnostic prose.
`Display` emits only the stable code and recovery category, not raw compiler or
registry details.

| Code suffix (`prompt_final_use_...`) | Meaning | Required recovery |
| --- | --- | --- |
| `invalid_shape`, `digest_mismatch`, `binding_mismatch` | Invalid or conflicting evidence | Reject |
| `revoked`, `retired`, `not_admitted` | Selection has no current lifecycle permission | Reject; do not retry the same selection |
| `expired`, `snapshot_changed`, `selection_changed` | Evidence no longer matches an eligible current snapshot | Recompile/reselect under fresh authority |
| `store_unavailable` | Owner or filesystem temporarily unavailable | Retry only after availability is restored |
| `reopen_required` | Owner fenced after an uncertain commit | Reopen and reconcile first |
| `indeterminate_durability` | Commit may already have become durable | Reopen and reconcile; never infer predecessor success |
| `capacity_exceeded` | Logical or physical quota cannot admit the operation | Relieve capacity; no immediate retry loop |
| `registry_rejected`, `compilation_rejected` | Integrity/configuration/compiler rejection | Reject and diagnose through the owner |

These codes describe the final-use contract. Other Agentd APIs retain their
existing error types; this document does not claim every repository error has
been converted to this taxonomy.

## 5. Checkpoint API

| Method | Mutates live source? | Destination semantics |
| --- | --- | --- |
| `operational_metrics` | No | Diagnostic only; `authoritative=false` after poisoning |
| `export_consistent_checkpoint` | No | A separately synchronized, exact V4 copy |
| `checkpoint_compacted` | No | Omits inactive payload bytes while retaining semantic/lifecycle metadata |
| `verify_restore_checkpoint` | No | Strict existing-V4 read, exact expected revision and digest, no migration or repair |
| `probe_fsync` | No registry mutation | Exclusive anchored temporary file, 1 byte through 1 MiB, cleanup synchronized |

Both expected identity arguments to `verify_restore_checkpoint` are mandatory;
`None` now returns `RestoreIdentityRequired`. This intentionally tightens the
previous optional-check behavior. The expected identity must come from a
trusted current checkpoint decision, not the candidate being inspected.
Missing directories/locks, partial checkpoints, unknown schemas, wrong private
permissions, invalid extents, mismatched identity, or unselected tails fail
without creating files, migrating data, trimming bytes, or updating metadata.

Completed identical checkpoint retries are idempotent. Different or partial
existing destinations are never overwritten. Source and checkpoint retained
history digests must match. Checkpoint receipts explicitly report
`source_erased=false`: reclaimed byte counts mean bytes omitted from the new
checkpoint, not bytes physically erased from the live source or old backups.
The destination is not automatically activated and it does not grant effect
authority. See `OPERATIONS.md` for owner handoff, retention, and recovery.

## Shared stable failure/recovery contract and collection

Publishers retain `DurableRegistryError` rather than flattening it into strings.
`DurableRegistryError::failure()` maps it to `PromptRegistryFailureV1`, with
stable redacted `code()` and `PromptRegistryRecoveryV1`. Agentd's final-use
adapter consumes this same classification. Recovery is advice, not authority.

| Class | Recovery |
| --- | --- |
| Identity reuse with different semantics | Reject; never overwrite or retry under the reused ID |
| Withdrawn, authorization rejected, invalid input | Reject the attempted use |
| Payload/snapshot integrity or frontier corruption | Reject/quarantine; do not reinterpret as a stale cache |
| Stale snapshot or unavailable selection | Re-enumerate/recompile and validate current authority |
| Expired admission | Reauthorize; not a blind write retry |
| Owner busy or temporary storage/authority unavailability | Back off and retry only after availability and identity checks |
| Capacity exhaustion / ENOSPC | Relieve capacity under policy before retry |
| Reopen required or unknown durability | Reopen and reconcile the selected durable outcome before further authority use |

`PromptFinalUseLeaseV1` rejects repeated factor IDs even when realization IDs
are distinct. A poisoned registry is diagnosed before lease expiry so a caller
cannot mistake an unknown durable result for a simple recompilation request.
An actual completed provider send remains an observed fact after revocation;
this change does not relabel it as never dispatched, or promise to retract bytes
already sent. The existing final-use gate remains the authority for any new
use, including cached attachment preparation and dispatch recording.

`collect_payload_garbage(&mut self)` returns `PromptRegistryGcReceipt`: source
and selected revision/digest, removed raw payload count/bytes, predecessor file
bytes unlinked, cleanup-pending status, selected extent bytes and total elapsed
time. A nonempty collection invalidates prior snapshots with a new revision;
otherwise it is an idempotent cleanup. A committed publication with pending
unlink is a receipt, not an indeterminate publication error. See OPERATIONS.md
for storage V5 compatibility, staging limits and crash-recovery rules.
