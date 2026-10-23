# control.engineering documentation index

`control.engineering` coordinates bounded engineering work and integration evidence. It does not mint runtime capability, merge itself, activate a deployment, or convert repository qualification into production acceptance.

The canonical reading order is:

1. [`TECHNICAL.md`](TECHNICAL.md) — module identity, ownership, contracts, state model and authority ceiling.
2. [`IMPLEMENTATION.md`](IMPLEMENTATION.md) — SQLite v10 owner, worker lifecycle, candidate sandbox and integration reconciliation.
3. [`SANDBOX_SECURITY.md`](SANDBOX_SECURITY.md) — exact Git-object materialization and the strong Linux isolation boundary.
4. [`CAPACITY.md`](CAPACITY.md) — database/WAL/audit sizing, admission ceilings and migration signals.
5. [`PRODUCTION_INTEGRATION.md`](PRODUCTION_INTEGRATION.md) — externally governed lease, audit, key-custody, deployment and operator evidence.
6. [`OPERATIONS.md`](OPERATIONS.md) — backup, restore, incidents, rollback and release evidence handling.
7. [`STATUS.json`](STATUS.json) — generated current-state projection. This is the single machine-readable status summary.
8. [`API_COMPATIBILITY.json`](API_COMPATIBILITY.json) — generated exact public export inventory.
9. [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json), [`TRACEABILITY.json`](TRACEABILITY.json) and [`COMPONENTS.json`](COMPONENTS.json) — source/test navigation and machine traceability.

## Qualification identities

Changes under the module source, module documents, its required workflows or the global exact-source verifier require all of the following:

- exact source-head qualification;
- deterministic base-merge qualification on pull requests;
- a current-head non-author GitHub approval;
- a merge commit preserving the reviewed exact-blob observation ancestry;
- an exact post-merge `main` qualification receipt;
- strong sandbox, coverage, type, lint, API, stress and real mutation-campaign evidence.

A GitHub approval is an observed repository governance fact only. It is not independent semantic acceptance. External production evidence remains separately governed and is never manufactured by CI fixtures.
