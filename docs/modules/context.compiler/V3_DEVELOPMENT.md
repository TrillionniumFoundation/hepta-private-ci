# V3 context compiler development guide

This is the active implementation guide. `TECHNICAL.md` and the JSON maps are
source-navigation projections; `design-baseline/` retains the detailed V2 proof
model. Current native outcomes, candidate identities and approvals belong to
PR/workflow receipts, not copied success counts in these documents.

## Ownership and entry points

| Responsibility | Source owner | Entry point / boundary |
|---|---|---|
| Governed prompt factors, realizations and admissions | `hepta-prompt-registry` | `context_authority_snapshot_v3`, `context_authority_successor_v3` |
| Canonical V3 selection, serialization and tokenization composition | `hepta-intelligence` | `compile_prompt_registry_v3`, `prepare_prompt_delivery_v3` |
| Pure proof objects and admission/delivery invariants | `hepta-context-compiler` | `compile_v2`, `build_attachment`, `prepare_delivery_v2`, final-request proof / recovery binding |
| Named compile/stage facade and exact request consumer | Existing Agentd prompt pipeline | `AgentdPromptPipelineOwner::compile_and_stage_v3`; `prompt_runtime` / `exact_context_delivery` |
| Exact encoded provider body and attempt-bound observation | Existing prompt extension / codex-api | `ext/hepta-prompt/src/exact_body.rs`, typed developer context slot |

The compiler and intelligence facade do not call a model or issue execution
capabilities. The registry issues construction-closed context snapshots. A
verified compilation/attachment is evidence about bytes and admission; it is not
a provider-send grant. Keep one physical effect spine. The historical alternate
Agentd V3 module is deliberately not registered.

## Compilation contract

`compile_prompt_registry_v3` consumes the durable registry, an optimizer
`SelectedPromptPortfolioV1`, a `PromptExerciseRequestV1`, a
`PromptRegistryCompilationRequestV3` and a `PromptExactTokenizerV3` implementation.
The caller must preserve the selected portfolio's model tuple and generation
binding; it must not reconstruct authority from a digest-only lookup table.

| Request field | Required relation |
|---|---|
| Compilation / serialization / attachment IDs | Valid stable identities for the corresponding proof objects |
| `registry_model_tuple` | Equals the selected portfolio tuple; the portfolio tuple digest verifies |
| `execution_profile` | Matches provider/model/version, tokenizer identity, framing and normalization contracts |
| `now_unix_ms` | Nonzero and equals the exercise request time |
| `token_budget` | Bounds selection and the actual serialized context token count |
| `truncation_policy_digest` | Nonzero, identifies the reviewed truncation contract |

V3 rejects empty portfolios. The underlying V2 compiler can represent empty
selection, so its scope/domain and attachment/preparation checks must remain
valid even when there are no admissions to iterate.

The crate-owned canonical bundle serializes selected IDs, roles and contents in
its reviewed order. Exact tokenization operates on those bytes. Digest pins bind
observed tokenizer identity, binary, vocabulary, normalization policy and version;
they do not prove semantic correctness or immutable interpreter custody. The
final provider request is counted separately, with its exact framing and typed
context slot. Never add an approximate count fallback on tokenizer failure.

`PromptRegistryCompiledContextV3` closes construction of registry authority and
source/tokenization bindings. Some exposed proof/profile fields are mutable for
compatibility, so consumers must invoke `validate()` rather than trusting a
caller-mutated object. Debug output excludes raw prompt payload.

## Revocation, expiry and final authorization

A newer snapshot may not move time or epoch backwards. At the same epoch its
revocation set must be unchanged; at a higher epoch it must retain every previous
revocation. Independent root verification does not establish this continuity.
Verified admissions share their immutable frontier, attachment construction checks
each distinct admission baseline, and delivery preparation additionally checks
the attachment frontier. This prevents resurrection between the two consumers.

The exact owner reserves preparation before tokenizer await, then reacquires the
current registry and holds that owner through proof construction and durable
pre-send authorization. There is no await in this authorization interval. Check
exclusive expiry and clock rollback at final use, including after durable sync.
A revocation before authorization rejects the request. Post-authorization
cancellation requires the transport owner's separate contract.

Keep the same encoded body through exact observation and transport. The current
Responses profile accepts exactly one complete developer/input_text context
string, rejects duplicate JSON keys, wrong roles, metadata-only placement and
concatenation, and binds provider/model/template/tool-schema identity.

## Durable delivery and recovery

Schema 3 archives preparation identity, final-request proof and exact provider
intent without raw prompt bytes. Publish with file sync, atomic rename and
directory sync before releasing transport bytes. Uncertain publication fences
that owner until reopen; deterministic rejection before publication may leave an
otherwise valid owner usable.

On Unix, the exact store walks no-follow directory components, pins the private
root, opens files relative to it, rejects unsafe ownership/mode/type/link count
before truncation and compares directory/lock/publication inode identity. Owned
root initialization applies private permissions through the descriptor. Configure
real directory paths: symlink ancestors are rejected. This is not Windows parity
or proof against privileged replace-and-restore / power-loss / rollback attacks.

Recovery may reconcile the archived attempt against provider evidence. It may
not redispatch, manufacture delivery from a callback, delete unresolved history
or upgrade schema-2 digest-only history into authenticated evidence.
`Indeterminate` remains unresolved. Duplicate semantic terminals are idempotent;
conflicting terminal replacement is rejected.

Raw content retirement and durable replay history are separate. Delivered
end-turn and rejected attempts can release settled raw stages; tool continuation
and unknown outcomes retain their stage. Runtime dispatch history is bounded at
1024 records and exact pre-send history at 4096. History rollover requires a
versioned journal/checkpoint/archive preserving tombstones, unresolved bindings
and independently anchored frontiers.

## Error and observability contract

Pipeline/runtime Debug and Display use stable reason codes. Adapter, registry,
compilation and exact-owner dynamic details must not reach ordinary logs. The
public exact-delivery diagnostic is opaque and preserves a reason code without
exporting internal error variants. Changing a reason code is an observable API
change; adding raw error chains would violate this contract.

Phase diagnostics are bounded process-local attempted measurements, including
errors and cancellation. Nested phases overlap, unobserved percentiles are null,
and the last-256 nearest-rank p50/p95/p99 are not target-host product SLOs. The
257-turn owner fixture retains subprocesses, growing history and real fsync under
a bounded harness watchdog; its budget is not a single-turn latency threshold.

## Development and qualification procedure

1. Change the owning pure proof/registry/consumer seam. Preserve wire/digest
   compatibility or explicitly version it. Do not add another execution owner.
2. Add adversarial behavior tests at that consumer: domain/frontier rollback,
   expiry during tokenization, duplicate/conflicting terminal, reopening,
   private-file substitution, uncertain sync and raw-free diagnostics.
3. Register each test module. A source file without a module declaration is not
   executable coverage. Future settlement test source remains dormant until its
   implementation and registration exist.
4. Run `just test` for affected packages, scoped strict Clippy / `just fix`, and
   `just fmt`. Dependency changes require Cargo and Bazel input validation.
5. Refresh `CURRENT_STATE.json` source blobs and run
   `scripts/generate_context_compiler_module_docs.py --write` then `--check`.
   Shared workspace-input changes also require the affected module navigation
   observations to be rebound; this grants no execution or acceptance.
6. Inspect exact source-head and synthetic-merge CI receipts. Profile matrix
   `cargo check` is compilation evidence, not native-test or product execution.
   Required named tests, fixture profile, command exit codes and failures must
   all be retained. Never disable a failed security gate to report closure.

Ordinary authenticated App Server turn admission and external
`ContextSecurityCapabilitiesV3` are not composed into this owner. Independent
provider truth, real tokenizer qualification, transport cancellation, additional
provider roles, cross-holder redaction, selected-host capacity/durability and
operator acceptance remain explicit integration tasks. Repository source changes
cannot grant independent acceptance, activation or release.
