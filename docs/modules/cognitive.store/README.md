# cognitive.store current development index

This directory is the canonical entry point for the `cognitive.store` source candidate. It describes source truth only; independent acceptance, activation, promotion and release are separate external states.

## Current truth

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

The dedicated workflow is `.github/workflows/cognitive-store-qualification.yml`. It runs independent `source-head` and deterministic `base-merge` lanes and retains exact-SHA command records for:

- cognitive-store semantic tests;
- durable memory-owner tests;
- Agentd product writer tests;
- signed bootstrap, rotation, restart, canary and live revocation;
- child-process crash/reopen;
- 256-record and 16,384-record durable profiles;
- all-target strict Clippy;
- closed-world architecture and orphan-source verification.

A command shown in documentation is not evidence. Only a retained terminal-success manifest bound to the exact tested commit/tree establishes execution.
