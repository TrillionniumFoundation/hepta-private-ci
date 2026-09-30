# secrets.heptabao product caller

`codex-hepta-bao-adapter` now owns the normal binary target
`hepta-secrets-runtime`. The source-bound constructor is
`compose_hepta_secrets_runtime` in
`src/bin/hepta-secrets-runtime.rs`.

The constructor forces the underlying SQLite recovery runtime to a claim limit
of one. `maxClaimsPerSweep` controls the number of completed claim/execute
cycles, not the number of leases acquired before execution. This removes the
lease-aging queue created by claiming 32 rows and processing them sequentially.

The executable deadline contract rejects configuration unless:

```text
consumer_timeout_ms < forward_execution_lease_ms < absolute_operation_deadline_ms
recovery_lease_ms < absolute_operation_deadline_ms
shutdown_drain_deadline_ms < absolute_operation_deadline_ms
```

The binary validates that database and token-file paths are absolute and that
the provider endpoint is an absolute HTTPS URL. It never prints provider token
contents. Product authority, registered consumers, trusted time and checkpoint
services remain dependency-injected and independently governed.

## Truth boundary

This is a source-composed product caller. It is not evidence that a deployment
has selected the binary, that the target filesystem is qualified, or that an
operator has accepted activation. `targetHostQualified`,
`storageProfileQualified`, `operatorAccepted`, `activated`, `released` and
`productionQualified` therefore remain false until separate exact-candidate
receipts prove those facts.

Metrics expose JIT sweep and claim counts, claim conflicts, and oldest due
reconciliation age. Measurements requiring timestamps inside the SQLite
claim/execution boundary are represented as unknown (`null`) rather than
fabricated zero values until the owner supplies those timestamps.
