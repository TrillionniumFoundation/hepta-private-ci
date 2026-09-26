# memory.retrieval operations

## Startup

1. Open the canonical SQLite cognitive owner and obtain a Lane C cut.
2. Load an authenticated retrieval profile and verify its digest against the generation vector.
3. Load the vector-index owner snapshot, model/encoder/tokenizer identities and HNMF snapshot.
4. Validate `RetrievalExecutionContextV1`.
5. Construct the Agentd product context with a bounded future lease.
6. Attach the context to `AgentdConfig` before runtime start.
7. In required mode, abort startup if any current-context requirement is absent.

## Rotation

- Read `lifecycle_epoch()` and `context_state_digest()`.
- Build and validate the complete replacement context before acquiring the write fence.
- Call `rotate_context(expected_epoch, replacement, new_expiry)`.
- Persist the resulting epoch, lease and state digest outside the rollback domain.
- Observe stale-context rejection and error-rate metrics before retiring the old model/index artifacts.

A failed epoch comparison means another operator or controller already changed the context. Refresh state; never force-write around the fence.

## Renewal

`renew_context` retains the exact context and advances the epoch. Renewal is prohibited after expiry or revocation. Set the lease much shorter than artifact retention but longer than the maximum request plus rotation budget.

## Revocation

Call `revoke_context(expected_epoch)`. Revocation advances the epoch, clears the context and sets lease expiry to zero. Required retrieval must immediately fail closed. Do not reinstate a revoked object; construct or recover a separately authorized generation.

## Recovery

Recover from an independently retained tuple:

- owner and body generation;
- lifecycle epoch;
- lease expiry;
- full context or explicit revoked state;
- product state digest.

A live recovery requires a future lease. The provider recomputes the state digest and validates the full execution context. A mismatch is corruption or rollback and blocks startup.

## Alerts

Page on:

- context absent/expired/revoked in required mode;
- generation or model mismatch;
- stale-context rejection spike;
- contradiction or OOD abstention step change;
- p95/p99 or peak-RSS threshold breach;
- receipt-count mismatch;
- exact-head/source-freshness CI failure;
- learning-ledger append failure after exposure.

## Evidence retention

Each qualification run retains source commit/tree, host identity, raw logs, parsed metrics, threshold result and SHA-256 manifest. GitHub-hosted artifacts are temporary evidence. Accepted named-host receipts belong in `qualification/memory-retrieval/BASELINES/` or the external immutable evidence store and must never be silently overwritten.
