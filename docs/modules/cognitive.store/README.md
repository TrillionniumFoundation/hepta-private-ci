# cognitive.store current development index

This directory is the canonical entry point for the `cognitive.store` source candidate. It describes source truth only; independent acceptance, activation, promotion and release are separate external states.

## Current truth

Start with [ARCHITECTURE_CURRENT.md](ARCHITECTURE_CURRENT.md), the sole short-form description of the current implementation. [READINESS.json](READINESS.json) is the machine-readable capability matrix and fail-closed qualification policy. [OPERATION_STATUS.json](OPERATION_STATUS.json) records every mapped operation with the five independent dimensions `source_present`, `compiled`, `repository_qualified`, `target_host_qualified`, and `released`.

The invariant state remains [CURRENT_STATE.json](CURRENT_STATE.json). Its generated [CURRENT_STATUS.md](CURRENT_STATUS.md) maps recovery, witness, publication, revocation, rollback, lifecycle and evidence invariants to exact sources and regression tests. [EXECUTION_DOSSIER.md](EXECUTION_DOSSIER.md) is generated from that state and the committed [QUALIFICATION_PLAN.json](QUALIFICATION_PLAN.json); neither generated document is a pass receipt.

The [September 28 implementation note](IMPLEMENTATION_UPDATE_20260928.md) describes the current ordinary-host read capability, three-profile API probes, optimized recovery measurements and externally signed per-storage-owner lifecycle reconciliation. It distinguishes those implementations from still-required destructive pruning, genuine host evidence and actual physical erasure.

| Question | Current answer |
|---|---|
| Semantic owner | `codex-hepta-cognitive-store` |
| In-memory qualification model | `InMemoryCognitiveModel`; `CognitiveStore` is a compatibility spelling |
| Physical durable owner | `codex_hepta_memory::CognitiveStore` over `cognitive_1.sqlite3` |
| Durable read surface | `DurableCognitiveReadCapability`; no grant/revoke or semantic mutation methods |
| Federation policy surface | `FederationPolicyCapability`, available only to named host/qualification features |
| Production mutation surface | Sealed `ProductionMutationCapability` |
| Only production write facade | `codex_hepta_agentd::AgentdProductionWriterHost` |
| Default runtime write authority | None; read-only unless trusted-host bootstrap is supplied |
| Raw mutable facade alias | Qualification-only, absent from default and normal host profiles |
| Normal host reads | `read_capability()` derives exact-cut paging/revalidation from the same recovered owner |
| Writable recovery | Source implemented with final live authority check; exact-candidate and target-host evidence still required |
| Signed host bootstrap | Source implemented with external current-cut, live authority state, signer trust, token files and independently supplied deployed source identity |
| Lifecycle completion | Authenticated per-owner receipts; not an erasure provider or an independent physical-erasure proof |
| Selected-host evidence | Exact source/host/cut-bound owner receipts; repository verification does not self-qualify the host |
| Retention readiness | Owner-attested disjoint key ranges, chained immutable segments and an unpublished same-cut successor receipt; no hot rows are deleted |
| Product execution proved | No, until the dedicated source-head and deterministic base-merge workflow is terminal-success |
| Production activated/released | No |

## Canonical flow

```text
external signed current cut + live signed authority + opaque token
                         |
                         v
             AgentdProductionWriterHost
                         |
             sealed mutation capability
                         |
                         v
            hepta-memory::CognitiveStore
                         |
                 cognitive_1.sqlite3
```

No second database, dual writer or shadow authority is permitted.

## Documents

- [ARCHITECTURE_CURRENT.md](ARCHITECTURE_CURRENT.md): concise current implementation, capability boundaries, qualification truth and matrix.
- [READINESS.json](READINESS.json): fail-closed candidate, workflow and capability state.
- [OPERATION_STATUS.json](OPERATION_STATUS.json): enforced five-dimensional status for every implementation-map operation.
- [TECHNICAL.md](TECHNICAL.md): module architecture and implementation guide.
- [IMPLEMENTATION_UPDATE_20260928.md](IMPLEMENTATION_UPDATE_20260928.md): normal read API, deployed source binding, release recovery profile, lifecycle receipt schemas and exact execution boundaries.
- [QUALIFICATION_AND_OBSERVATION_BINDING.md](QUALIFICATION_AND_OBSERVATION_BINDING.md): committed command/workload binding, independent log counters and descriptor-retained publication observation.
- [PUBLICATION_HARDENING.md](PUBLICATION_HARDENING.md): descriptor-bound archive publication, current lifecycle trust, release-report validation and scoped regression evidence.
- [PRODUCTION_CLOSURE.md](PRODUCTION_CLOSURE.md): canonical product boundary and claim vocabulary.
- [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json): machine-readable source mapping and open gates.
- [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md): current-cut, authority, rotation, canary, restart and rollback ceremony.
- [HOST_QUALIFICATION.md](HOST_QUALIFICATION.md): exact source/host/cut-bound selected-host receipt contract without self-activation.
- [ACCEPTANCE_GOVERNANCE.md](ACCEPTANCE_GOVERNANCE.md): content-validated evidence reports, distinct independently signed review roles and ordered approval dependencies without performing activation or release.
- [ADR-0001-RETENTION-PRUNING.md](ADR-0001-RETENTION-PRUNING.md): ancestry-safe retention and pruning decision.
- [RETENTION_READINESS.md](RETENTION_READINESS.md): chained segment and unpublished same-cut rebuild evidence required before pruning publication.
- [ARCHIVE_RUNBOOK.md](ARCHIVE_RUNBOOK.md): encrypted cold-generation transfer and native restored-cut verification.
- [ARCHIVE_OBSERVATION.md](ARCHIVE_OBSERVATION.md): signed observation after response loss or publication ambiguity, without replay or adoption.
- [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md): authoritative, rebuildable, backup and derived-data lifecycle.
- [PRIVACY_EXPORT_DELETE_RUNBOOK.md](PRIVACY_EXPORT_DELETE_RUNBOOK.md): operator export/delete workflow and evidence.
- [SCHEMA_COMPATIBILITY.md](SCHEMA_COMPATIBILITY.md): migration, reopen and rollback compatibility matrix.
- [ERROR_CATALOG.md](ERROR_CATALOG.md): stable operator-facing error classes.
- [RETRY_RECONCILE_MATRIX.md](RETRY_RECONCILE_MATRIX.md): retry, reconcile and escalation behavior.
- [SLO.md](SLO.md): candidate performance and recovery objectives.
- [THREAT_MODEL.md](THREAT_MODEL.md): threats, controls and qualification tests.

## Source qualification

The dedicated workflow is `.github/workflows/cognitive-store-qualification.yml`. It freezes source/base once for both `source-head` and deterministic `base-merge` lanes. The committed plan retains package, bootstrap, crash/reopen, 256/16,384-record and strict-Clippy checks. Its 50 commands also cover typed product recovery, real child exit between semantic commit and witness publication, normal Agentd feature compilation, normal-host read pages, external-consumer API probes, map/evidence regressions, generated-state drift, correction/tombstone history, release descriptor recovery, storage-owner signatures, encrypted archive/restore, read-only publication observation, selected-host receipt validation, retention-checkpoint readiness, and acceptance-governance regressions. Five added records exercise descriptor publication, final lifecycle trust and exact-candidate recovery-report validation without accepting an SLO or weakening an existing gate.

Each command records its own result rather than inheriting the status of an earlier step. The runner validates the entire committed plan before dispatch. The manifest independently checks the resolved command, working directory, workload and limits, and recounts tests from the retained log. Five further records cover these bindings, the three shared-runner regression suites and final-use observation staging. Native preparation failure produces explicit `infrastructure_invalid` non-execution records. A v2 qualification manifest is emitted even when checks fail or are missing; only a complete terminal-success manifest bound to the exact tested commit/tree establishes execution. Artifact upload is not a qualification pass.

## Updating source bindings

`sourceBase` remains historical provenance. `sourceObjects` binds current source, delegated implementation trees, read/product callers, tests, and qualification inputs. The map itself is excluded to avoid recursive Git hashes. Commit source and metadata definitions before emitting a new map with:

```sh
python3 scripts/cognitive_store_map_generate.py \
  --source-commit "$(git rev-parse HEAD)" > /tmp/cognitive-store-map.json
```

Review and commit the emitted map as a separate authoring change. Qualification never regenerates it, patches fixtures, deletes itself, or pushes source. `sourceBindingSnapshot` records the authored source commit; subsequent source drift is rejected, including a new file in a bound implementation tree.

Generate state projections with `python3 scripts/cognitive_store_status.py --write` during authoring; CI runs only `--check`. Keep the detailed architecture and historical evidence intact. Repository fixtures do not replace independent witness retention, target-filesystem fault injection, governed signer operations, physical erasure, or release approval.
