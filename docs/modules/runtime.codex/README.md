# runtime.codex documentation index

`runtime.codex` integrates Hepta's governed model boundary with the existing Codex App Server thread/turn execution spine. It does not introduce another model or tool runtime.

## Normative design and source mapping

- [Technical development guide](TECHNICAL.md)
- [Implementation map](IMPLEMENTATION_MAP.json)
- [Fault matrix](FAULT_MATRIX.md)
- [State machine and crash invariants](STATE_MACHINE.md)
- [Final-use authority port](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md)

## Build and operations

- [Quickstart](QUICKSTART.md)
- [Deployment and operations runbook](OPERATIONS.md)
- [Quarantine and release protocol](QUARANTINE_AND_RELEASE.md)
- [Production qualification and acceptance](PRODUCTION_QUALIFICATION.md)

## Claim boundary

Repository source, mock-provider product tests, and CI receipts may establish source correctness for one exact Git candidate. They do not establish target-host identity, production signer-key custody, trusted time or revocation distribution, a real provider terminal stream, external-tool terminality, independent acceptance, activation, promotion, or release.

A missing or failed receipt is never converted into a pass. An indeterminate effect is never converted into “not applied” by timeout, restart, log loss, operator judgment, or capacity pressure.
