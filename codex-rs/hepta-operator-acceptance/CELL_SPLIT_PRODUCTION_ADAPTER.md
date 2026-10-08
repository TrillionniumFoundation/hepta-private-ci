# CellSplit production target-host adapter

`ProductionTargetHostRuntime` is the owner-bound composition root for the real
CellSplit target-host lifecycle. It has no filesystem, network, signer-key,
token, password, CAS, CNS, telemetry, or hardware side effects. The deployment
must provide every handle in `ProductionTargetHostRuntimeConfig`; absent or
misbound handles return `MissingExternalInput`, `UnboundOwner`, or
`WrongTrustRoot`. `blocked_packet()` is diagnostic and always carries
`productionEvidence: false`.

The adapter requires one explicit namespace and trust-root binding for each
owner: artifact/CAS registry, CNS route, fault injector, tombstone, TaskFlow,
host telemetry, hardware attestation, learning ledger, future-window evaluator,
and evidence signer/observer. Each owner returns an immutable predecessor-bound
receipt; the adapter checks generation fences, receipt-chain predecessors,
operation idempotency, and abort state before advancing.

The fourteen steps are `OwnersBound`, artifact/CAS load, CNS route cutover,
dispatch, clean restart, approved power-loss, recovery, rollback, tombstone,
old-generation rejection, future-window evaluation, host/observer signing,
TaskFlow/learning-ledger replay, and independent verification.

Exported packets cover artifact/CAS/registry, CNS dispatch, route-fence restart
replay, restart/power-loss/rollback/tombstone/no-resurrection, resource samples
and attestation, baseline/future-window observer evidence, signed target-host
evidence, TaskFlow event chains, learning-ledger witness frontiers, and
independent evaluator receipts. The existing signed-evidence verifier remains
the only path that can accept a host/observer envelope.

No target host, hardware attestation, fault injector, observer/evaluator, or
production owner is connected in this repository checkout. Therefore no
production evidence or activation claim is emitted here.
