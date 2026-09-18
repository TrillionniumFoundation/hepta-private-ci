# Failure and recovery

A provider mutation is classified by what is known, not by what the caller
wishes happened.

- Before provider dispatch: a denied/rejected operation has no provider effect.
- After dispatch with lost acknowledgement: record `Indeterminate`; do not
  blind-retry.
- Issuance response received: persist the opaque handle before callback entry.
- Final-use blocks delivery after issuance: return `DeliveryBlocked` with the
  handle so the trusted host can revoke/reconcile.
- Registry commit fails after provider issuance: return `RegistryBlocked` with
  the known handle; do not issue a replacement.
- Ambiguous renew/revoke of a known handle: use non-replaying lease lookup.
- Lost issuance response: provider/operator reconciliation is required unless
  the provider implements stable operation-key status lookup.

SQLite registry reopen preserves operation fences, known handles and
indeterminate state. Final-use `claims.log` preserves claimed nonces across
process death.

Restoring old registry/authority backups can roll state backward. Such restore
requires explicit reconciliation/epoch recovery; local persistence is not an
external anti-rollback oracle.
