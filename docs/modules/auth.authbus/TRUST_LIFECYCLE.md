# AuthBus trust, key rotation and replay-retirement lifecycle

This document defines the host-side public-trust lifecycle for `auth.authbus`.
It does not create or escrow issuer private signing keys. Private-key custody remains
with the independently governed producer/KMS/HSM. Agentd receives only a protected
public trust projection.

## Enrollment

Install Agentd trust schema v2 with:

- `trust_revision = 1` for a new issuer projection;
- a nonzero `key_epoch`;
- the Ed25519 public key for that epoch;
- `revoked = false`;
- the bounded existing-thread allowlist.

The file is a direct child of the canonical Agent home, mode `0600`, under a mode
`0700` home, same owner, no links. Agentd persists a digest of the complete trust
projection in `authbus_trust_heads`. Reusing one revision with changed key, epoch,
revocation or allowlist fails closed.

## Rotation

For normal key rotation:

1. create the new producer key under the external key authority;
2. atomically install a new trust projection with a strictly larger
   `trust_revision` and strictly larger `key_epoch`;
3. admit new messages only with the new epoch;
4. quarantine or drain active old-epoch outbox deliveries according to the incident
   and delivery policy;
5. advance the replay checkpoint and retain the returned generation/digest outside the
   Agent home/run/backup restore boundary;
6. after the external checkpoint is durable and the old epoch has no active outbox
   rows, call `retire_authbus_replay_epoch`;
7. persist the returned post-compaction checkpoint externally before considering the
   retirement complete.

The permanent retired-epoch marker remains in SQLite even after replay high-water rows
are compacted. Later durable admission for that epoch returns `Revoked`.

## Revocation

For emergency revocation, install a strictly higher `trust_revision` for the same
epoch with `revoked = true`, then call `quarantine_authbus_issuer` to retire queued
or leased messages. The same key epoch cannot be changed back to `revoked = false`,
even with a higher trust revision. Recovery requires a new key epoch.

Revocation after an external target has already accepted an operation cannot undo that
effect. The effect-specific reservation stays held/quarantined until observed terminal
reconciliation closes it.

## Independent replay checkpoint

The production host must supply both the trust projection and independent replay watermark. Agentd rejects signed-ingress startup when the trust file is configured without the checkpoint (or vice versa):

`--authbus-replay-checkpoint-file /independently-retained/private/checkpoint.json`

The checkpoint path must be absolute/canonical, symlink-free, outside the Agent home and
run root, under a private owner directory, and mode `0600`. Its JSON schema is defined
in `codex-rs/hepta-agentd/AUTHBUS_TEXT.md`.

`verify_authbus_replay_checkpoint` treats this as a rollback watermark: normal replay
growth after the checkpoint is allowed, while restoring a database whose stored
checkpoint predecessor is older than the independently retained expected generation
fails closed. Destructive replay compaction is stricter and requires the current replay
registry digest to equal the exact externally retained checkpoint being consumed.

## Forbidden transitions

The durable owner rejects:

- decreasing or reusing a trust revision with changed content;
- decreasing a key epoch;
- changing a public key within one epoch;
- un-revoking the same epoch;
- reusing a retired epoch;
- retiring an epoch with active outbox rows;
- retiring against a stale/mismatched external checkpoint;
- advancing a checkpoint from any generation other than the exact stored predecessor.

These are source-level controls only. Production activation additionally requires
independent security/semantic review, operator acceptance and protected external key and
checkpoint custody.
