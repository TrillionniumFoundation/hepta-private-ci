# cognitive.store current development index

This directory is the canonical entry point for the `cognitive.store` source candidate. It describes source truth only; independent acceptance, activation, promotion and release are separate external states.

## Current truth

The machine-readable state is [CURRENT_STATE.json](CURRENT_STATE.json). Its generated [CURRENT_STATUS.md](CURRENT_STATUS.md) maps recovery, witness, publication, revocation, rollback, lifecycle and evidence invariants to exact sources and regression tests. [EXECUTION_DOSSIER.md](EXECUTION_DOSSIER.md) is generated from that state and the committed [QUALIFICATION_PLAN.json](QUALIFICATION_PLAN.json); neither generated document is a pass receipt.

| Question | Current answer |
|---|---|
| Semantic owner | `codex-hepta-cognitive-store` |
| Physical durable owner | `codex_hepta_memory::CognitiveStore` over `cognitive_1.sqlite3` |
| Only production write façade | `codex_hepta_agentd::AgentdProductionWriterHost` |
| Default runtime write authority | None; read-only unless trusted-host bootstrap is supplied |
| Raw mutable alias | Hidden from the default façade; enabled only for the named Agentd host or explicit qualification |
| Writable recovery | Source implemented; exact-candidate and target-host evidence still required |
| Signed host bootstrap | Source implemented with external current-cut, live authority state, signer trust and token files |
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

- [TECHNICAL.md](TECHNICAL.md): module architecture and implementation guide.
- [PRODUCTION_CLOSURE.md](PRODUCTION_CLOSURE.md): canonical product boundary and claim vocabulary.
- [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json): machine-readable source mapping and open gates.
- [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md): current-cut, authority, rotation, canary, restart and rollback ceremony.
- [ADR-0001-RETENTION-PRUNING.md](ADR-0001-RETENTION-PRUNING.md): ancestry-safe retention and pruning decision.
- [DATA_LIFECYCLE.md](DATA_LIFECYCLE.md): authoritative, rebuildable, backup and derived-data lifecycle.
- [PRIVACY_EXPORT_DELETE_RUNBOOK.md](PRIVACY_EXPORT_DELETE_RUNBOOK.md): operator export/delete workflow and evidence.
- [SCHEMA_COMPATIBILITY.md](SCHEMA_COMPATIBILITY.md): migration, reopen and rollback compatibility matrix.
- [ERROR_CATALOG.md](ERROR_CATALOG.md): stable operator-facing error classes.
- [RETRY_RECONCILE_MATRIX.md](RETRY_RECONCILE_MATRIX.md): retry, reconcile and escalation behavior.
- [SLO.md](SLO.md): candidate performance and recovery objectives.
- [THREAT_MODEL.md](THREAT_MODEL.md): threats, controls and qualification tests.

## Source qualification

The dedicated workflow is `.github/workflows/cognitive-store-qualification.yml`. It freezes source/base once for both `source-head` and deterministic `base-merge` lanes. The committed plan retains the existing package, bootstrap, crash/reopen, 256/16,384-record and strict-Clippy checks, and adds typed product recovery, a real child exit between semantic commit and witness publication, default-feature compilation, map/evidence regressions, generated-state drift checks, and correction/tombstone history profiles.

Each command records its own result rather than inheriting the status of an earlier step. Native preparation failure produces explicit `infrastructure_invalid` non-execution records. A v2 qualification manifest is emitted even when checks fail or are missing; only a complete terminal-success manifest bound to the exact tested commit/tree establishes execution. Artifact upload is not a qualification pass.

## Updating source bindings

`sourceBase` remains historical provenance. `sourceObjects` binds current source, delegated implementation trees, read/product callers, tests, and qualification inputs. The map itself is excluded to avoid recursive Git hashes. Commit source and metadata definitions before emitting a new map with:

```sh
python3 scripts/cognitive_store_map_generate.py \
  --source-commit "$(git rev-parse HEAD)" > /tmp/cognitive-store-map.json
```

Review and commit the emitted map as a separate authoring change. Qualification never regenerates it, patches fixtures, deletes itself, or pushes source. `sourceBindingSnapshot` records the authored source commit; subsequent source drift is rejected, including a new file in a bound implementation tree.

Generate state projections with `python3 scripts/cognitive_store_status.py --write` during authoring; CI runs only `--check`. Keep the detailed architecture and historical evidence intact. Repository fixtures do not replace independent witness retention, target-filesystem fault injection, governed signer operations, physical erasure, or release approval.
