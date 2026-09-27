# auth.authbus activation decision

Status: **BLOCKED pending terminal exact-head and synthetic-merge qualification**.

This decision is intentionally fail-closed. Source implementation is not equivalent to production activation evidence.

## Implemented security controls

- issuer registrations are opaque handles whose trust-bearing fields are resolved from owner-controlled persisted registries;
- settlement reloads the exact issuer identity, purpose and epoch from the durable authority registry;
- the raw authority writer is crate-private and product callers use `AuthBusAuthorityHost`;
- owner lifetime is fenced across processes and all checkpoint publication occurs while the host owns that fence;
- startup and periodic owner maintenance perform bounded restart reconciliation and expired-reservation sweeping;
- operational snapshots expose checkpoint, recovery, reservation, quota and issuer signals;
- exact-source and synthetic-merge qualification lanes execute product callers, workspace regression and strict lint before producing evidence receipts.

## Mandatory evidence before activation

Activation requires all of the following on one exact candidate SHA and tree:

1. closed-world API inventory succeeds without product-caller exceptions;
2. forged key, revoked key, epoch substitution, purpose substitution and fake-quarantine negative tests execute and pass;
3. same-process, dual-process and process-death owner-fence tests execute and pass;
4. checkpoint failpoints, rollback recovery and bounded reservation lifecycle tests execute and pass;
5. AuthBus, qualification, evidence, Agentd and Bao product tests execute and pass;
6. full workspace all-target regression and strict Clippy execute and pass;
7. the synthetic merge candidate executes the same gates successfully;
8. the evidence receipt binds source SHA, tree SHA, schema digest, Cargo lock digest, test-log digests, build-artifact digests and workflow run identity;
9. production trusted-time, settlement signer, key custody, metrics export and alert routing are named and independently reviewed;
10. target-host ENOSPC, rename/fsync failure and power-loss recovery rehearsals are recorded.

A queued, skipped, cancelled, deferred, prior-head or static-only check is not evidence of success. This file may be changed to `APPROVED` only by naming immutable successful workflow run IDs and artifact digests. Until then, `productionActivation` remains `blocked` and no completion claim is permitted.
