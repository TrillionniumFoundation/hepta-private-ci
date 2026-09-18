# Failure and recovery

## Crash points

Before durable operation record: no provider dispatch is allowed.

After durable pending record but before dispatch: restart sees pending/unknown
work and must reconcile before any replacement operation is issued.

After dispatch and before acknowledgement: transition to `Unknown`. Never infer
not-applied from timeout, connection reset, malformed success body or process
death.

After provider acknowledgement and before consumer callback: the lease is
persisted as `Active`. A final-use revocation may still block secret delivery;
operators can then revoke the provider lease without having released it.

After consumer entry but before caller receipt: provider lease remains Active
and the consumer effect is indeterminate. Do not issue another credential merely
because the caller did not receive a success receipt.

## Reconciliation

Reconciliation is an explicit trusted observation, never a local guess.
Provider-specific integrations may prove one of:

- active lease with exact provider lease ID and expiry
- revoked lease
- operation not applied

If a provider cannot expose enough identity to distinguish a lost response from
a duplicate issuance, the correct state remains `Unknown` and operator/provider
reconciliation is required.

## Restart

The local lease registry rebuilds current metadata and operation-id history from
the append-only journal. Raw secret values are not recoverable from the registry.

Final-use replay state rebuilds the current epoch nonce set from `claims.log`.
A partial/corrupt journal fails closed. Epoch change persists the stronger
authority head before compaction so a crash cannot reopen an old epoch with
forgotten claims.

## Backup and rollback

Restoring an old lease registry can lose knowledge of provider effects and
requires reconciliation before new mutations. Restoring or deleting final-use
authority state is an authority reset and requires independent trust/epoch
recovery. Neither local store is an external anti-rollback oracle.
