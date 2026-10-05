# Lane A implementation and installation checks

Use each owner's current technical guide for implementation facts. This file
does not maintain a second status ledger or add a source-change approval step.
In particular, the durable operation path is implemented in the existing
CognitiveStore owner; the old claim that it is only an in-memory reference is
obsolete.

- [kernel.operations](../modules/kernel.operations/TECHNICAL.md): durable intent,
  outbox, destination acknowledgement and current-fence reconciliation.
- [auth.authbus](../modules/auth.authbus/TECHNICAL.md): signed ingress, replay
  checkpoints, policy history and quota/reservation recovery.
- [kernel.authority](../modules/kernel.authority/TECHNICAL.md): final-use
  linearization and independent issuer/consumer boundaries.
- [secrets.heptabao](../modules/secrets.heptabao/TECHNICAL.md): the original Bao
  provider and AuthBus operation composition.
- [platform.wire](../modules/platform.wire/TECHNICAL.md): versioned encoding and
  cross-language conformance vectors.

For a real installation, verify the named target's current programs, original
state, independently provisioned trust, revocation delivery, cold recovery and
resource limits. Use actual fault and capacity measurements for the affected
stateful owners. A source test cannot supply a provider credential, manufacture
an independent decision or prove a physical-host restore.

Repository owners choose repository review and merge policy. Authorized normal
development does not require a separate lane acceptance receipt. Production
evaluation, model/provider access and release use their actual configured
boundaries and remain subject to their original authority and validity checks.
