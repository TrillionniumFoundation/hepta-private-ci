# runtime.codex documentation index

`runtime.codex` integrates Hepta's governed model boundary with the existing Codex App Server thread/turn execution spine. It does not introduce another model or tool runtime.

## Normative design and source mapping

- [Technical development guide](TECHNICAL.md)
- [Implementation map](IMPLEMENTATION_MAP.json)
- [Fault semantics](FAULT_MATRIX.md)
- [Machine-readable fault-injection matrix](FAULT_INJECTION_MATRIX.json)
- [State machine and crash invariants](STATE_MACHINE.md)
- [Final-use authority port](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md)

## Build and operations

- [Quickstart](QUICKSTART.md)
- [Deployment and operations runbook](OPERATIONS.md)
- [Quarantine and release protocol](QUARANTINE_AND_RELEASE.md)
- [Production qualification and acceptance](PRODUCTION_QUALIFICATION.md)

## Verification commands

```bash
python3 scripts/check-runtime-codex-fault-matrix.py
python3 scripts/runtime-codex-qualification.py --help
```

The dedicated `runtime.codex qualification` workflow separately evaluates the exact branch head and the deterministic merge candidate, retains all command outcomes, emits a canonical JSON receipt, and attaches GitHub provenance attestation to that receipt.

## Claim boundary

Repository source, mock-provider product tests, and CI receipts may establish source correctness for one exact Git candidate. They do not establish target-host identity, production signer-key custody, trusted time or revocation distribution, a real provider terminal stream, external-tool terminality, independent acceptance, activation, promotion, or release.

A missing or failed receipt is never converted into a pass. An indeterminate effect is never converted into “not applied” by timeout, restart, log loss, operator judgment, or capacity pressure.
