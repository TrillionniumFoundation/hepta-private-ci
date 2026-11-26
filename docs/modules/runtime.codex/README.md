# runtime.codex documentation index

`runtime.codex` integrates the existing Codex App Server thread/turn execution
spine with Hepta authority, durable operation ownership and exact terminal
correlation. It does not create a second model or tool execution spine.

## Start here

| Task | Document |
| --- | --- |
| Understand architecture, contracts and owner boundaries | [`TECHNICAL.md`](TECHNICAL.md) |
| Build and exercise the repository candidate locally | [`QUICKSTART.md`](QUICKSTART.md) |
| Provision identities, directories, sockets and services | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Diagnose failures without replaying an unknown effect | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| Run day-2 operations, canary, incident response and rollback | [`OPERATIONS.md`](OPERATIONS.md) |
| Review source-level failure and replay semantics | [`FAULT_MATRIX.md`](FAULT_MATRIX.md) |
| Review all crash cut points | [`CRASH_INJECTION_MATRIX.md`](CRASH_INJECTION_MATRIX.md) |
| Resolve unavailable App Server history | [`QUARANTINE_AND_RELEASE.md`](QUARANTINE_AND_RELEASE.md) |
| Run protected target-host evidence | [`PRODUCTION_QUALIFICATION.md`](PRODUCTION_QUALIFICATION.md) and [`TARGET_HOST_FAULT_HARNESS.md`](TARGET_HOST_FAULT_HARNESS.md) |
| Decide whether a candidate may advance | [`ACCEPTANCE_CHECKLIST.md`](ACCEPTANCE_CHECKLIST.md) |
| Inspect exact source mapping and remaining gates | [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) and [`REMEDIATION_STATUS.md`](REMEDIATION_STATUS.md) |

## Four independent completion levels

1. **Repository source qualification** proves that one exact source or ordered
   synthetic-merge candidate compiled, passed the closed-world test inventory,
   passed strict lint/format checks and retained machine-readable receipts.
2. **Target-host qualification** proves the selected binaries, issuer process,
   Agentd/App Server generation, sockets, persistent stores and real provider
   under required fault injection and resource load.
3. **Independent acceptance** is an external decision over the complete evidence
   set, unresolved quarantine inventory, canary and rollback rehearsal.
4. **Activation, promotion and release** are operational decisions after the
   first three levels. A GitHub workflow, generated document or source maintainer
   cannot self-grant them.

A later level never backfills a failed or missing earlier level. A signature
proves who attested particular bytes; it does not turn failed, skipped,
cancelled, stale or absent evidence into a pass.

## Non-negotiable safety rules

- Only a fresh, exact, non-idempotent server-owned effect-entry acknowledgement
  may permit the one physical `turn/start` attempt.
- A lost, mismatched or idempotent acknowledgement is reconciliation evidence,
  not another send permit.
- Unknown provider acknowledgement, process loss and unavailable App Server
  history never prove “not applied”.
- `hepta-infer-worker` is model-only. Model authorization does not authorize an
  arbitrary tool effect.
- Issuer and quarantine private keys stay outside the worker, Agentd and source
  checkout.
- Never regain capacity by deleting journals, rewinding authority frontiers or
  converting an unresolved effect into success/failure without exact evidence.
