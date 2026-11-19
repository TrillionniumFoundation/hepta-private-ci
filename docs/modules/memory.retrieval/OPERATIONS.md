# memory.retrieval operations

## Startup

Choose exactly one retrieval mode. Compatibility starts without a current HNMF provider. Shadow, canary and required start only after protected host configuration supplies a validated provider snapshot for the exact Agentd owner/body generation. Do not synthesize model, encoder, policy or engram identities from environment strings or caller input.

## Provider lifecycle

Issue short leases from a protected owner. Rotation supplies the expected current revision and a fully validated replacement context; a mismatch is a conflict. Revocation increments revision and immediately denies reads. Recovery loads a persisted snapshot only after validating owner/body, interval, revoked state, context digest, common generation identity and snapshot digest. Clock rollback, expiry, poisoned locks and unavailable owner all fail closed.

## Alerts

Alert on startup rejection, expired/revoked provider, revision conflict, generation mismatch, owner revalidation failure, abnormal abstention rate, stale-context rejection, candidate/graph capacity pressure, SLO breach, benchmark receipt mismatch and learning append failure. Logs contain digests/counts and never raw private memory or credentials.

## Incident actions

For semantic or source-integrity incidents, revoke the provider and return to compatibility only through an explicit protected configuration change. For canary regressions, set compatibility, preserve receipts and compare selected versus delivered subsets. For stale owner state, stop HNMF delivery and repair the authoritative SQLite owner; never rebuild authority from retrieval receipts. For learning-ledger failure, fail the configured product operation rather than silently dropping assignment evidence.

## Qualification

Before promotion, run exact-source and deterministic synthetic-merge qualification, target-host probes, provider fault tests and rollback rehearsal. Retain raw evidence and immutable receipts. GitHub-hosted measurements are regression evidence, not target-host acceptance.
