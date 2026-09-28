# prompt.registry: implementation and qualification dossier

Parent: `docs/modules/prompt.registry/TECHNICAL.md`. Qualification lane:
`prompt.registry` exact-head plus deterministic base-merge. Common execution
semantics remain governed by `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Claim boundary

The current remediation candidate distinguishes five independent states:

| State | Value |
| --- | --- |
| source implemented | true |
| source composed | true |
| product activated | false |
| independently accepted | false |
| released | false |

Source implementation and source composition do not grant deployment,
external-effect, merge, acceptance or release authority. `productionReady` is
false until current exact-head and base-merge qualification receipts are green
and protected postmerge checks pass.

## 2. Source and work envelope

Primary roots:

- `codex-rs/hepta-prompt-registry`
- `codex-rs/hepta-prompt-optimizer`
- Agentd prompt owner/runtime/final-use integration
- `codex-rs/hepta-intelligence/src/prompt_delivery.rs`
- `docs/modules/prompt.registry`

The registry remains the authoritative prompt-factor owner. The optimizer is a
read-only consumer. Agentd owns product composition and dispatch-time final-use
fencing. No parallel authority or execution spine is introduced.

## 3. Public operations and contract

The implemented contract separates semantic factor identity from
model-specific realization identity. It includes governed factor registration
and admission, relation registration, realization plus payload publication,
retirement and terminal revocation, exact-model compatible enumeration,
payload dereference and dispatch-time final-use validation.

Model compatibility binds the complete model tuple, including model/version,
tokenizer, template, tool schema, context profile and locale. Consumer
capabilities filter unsupported roles before staging. Registry insertion does
not automatically select or activate a factor in a running request.

## 4. State, storage and recovery

`DurablePromptRegistry` owns one bounded in-process image under an exclusive
state-directory lock. The strict V4 semantic image durably includes factors,
realizations, bindings, payload references, relations, supersession and
lifecycle events. V1, V2, V3 and the transitional outer-V4/inner-V2 layout are
migrated forward to strict V4; a validated strict-V4 reopen is read-only apart
from trimming an unselected payload tail.

New payload extents are synchronized before metadata publication. Metadata is
written to a temporary file, synchronized, renamed and followed by directory
synchronization. Failure after rename is treated as indeterminate durability:
the writer is poisoned and must be reopened and reconciled instead of silently
retrying over an outcome that may already be durable.

Revocation is terminal in the registry image. Frozen snapshots, payload
dereference and final-use validation all re-check lifecycle state; the Agentd
runtime carries a bounded final-use lease from staging to dispatch recording.
That source-level fence is not, by itself, evidence that a deployed provider
adapter has been activated or independently accepted.

## 5. Capacity and performance contract

The current canonical bounds include the registry record limit and a 64 KiB
maximum realization payload. Storage remains bounded by the payload extent
limit and metadata-size limit. These are safety ceilings, not scale evidence.

The source owner now exposes unified logical-record/payload/byte quota
metrics, consistent checkpoint export, copy-compaction/GC into a fresh V4
directory, restore verification and bounded fsync probes. The qualification
workflow executes the 1k/8k/16k logical-scale and fsync profiles and binds the
profile digest into each exact-candidate receipt. No WAL, Merkle or incremental
digest design is justified unless those measurements identify a material
bottleneck.

## 6. Required verification

The module-specific workflow must execute both current source-head and a
deterministic synthetic merge against the bound base. Each lane must prove:

- formatting without source mutation;
- registry unit and durable-recovery tests;
- optimizer relation/capability integration tests;
- Agentd prompt pipeline and final-use tests;
- strict Clippy for owned packages;
- Cargo closed-world source-graph validation;
- protocol/schema and implementation-map validation.

The emitted receipt binds run ID and attempt, lane, source/base/tested SHA,
tested tree and owned source blob digests. Queued, skipped, cancelled,
historical or unrelated results are not passes.

Required product scenario:

```text
bootstrap
→ authenticated factor registration/admission
→ realization and payload publication
→ candidate enumeration
→ optimization
→ compile and stage
→ revoke before dispatch
→ dispatch must fail closed
→ restart
→ revocation and failure remain effective
```

## 7. Current native implementation

Implemented source includes:

- core factor, realization, relation, lifecycle and snapshot semantics;
- strict durable V4 relation persistence and legacy migration;
- authenticated factor/realization/relation publication paths;
- exact-model and consumer-capability compatible enumeration;
- payload-digest verification and bounded dereference;
- Agentd prompt owner/runtime composition;
- dispatch-time final-use lease and durable final-use records;
- included optimizer relation graph tests rather than an orphan source file;
- copy-compacted V4 checkpoints, unified quota metrics, restore verification,
  bounded fsync probes and operational scale profiles.

The machine-generated implementation map and qualification receipts, not this
narrative, are authoritative for exact source identities and executed tests.

## 8. Remaining work and non-claims

Before any production-ready statement:

1. make both exact-head and base-merge module qualification lanes green;
2. commit the exact generated implementation map for the qualified candidate;
3. complete the end-to-end revoke-before-dispatch and restart scenario;
4. review the emitted 1k/8k/16k and fsync profiles and record whether any
   WAL, Merkle or incremental-digest work is justified;
5. qualify external quiescent checkpoint activation and rollback in the named
   product environment;
6. obtain independent product activation, acceptance and release decisions.

No source change in this dossier self-accepts, self-merges, self-deploys or
self-releases the module.
