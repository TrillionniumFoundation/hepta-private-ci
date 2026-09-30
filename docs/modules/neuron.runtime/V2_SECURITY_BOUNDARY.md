# Neuron Runtime V2 security and rollback boundary

This document is the formal security-gap register for the durable V2 runtime. It
records a blocking boundary; it does not claim that the boundary has already been
closed and it grants no model-selection, execution, result-use, activation,
promotion or release authority.

## 1. Current trust domains

The product path currently relies on distinct durable domains:

1. the `HPTNGS02` generation store for exact operation/result history;
2. the `HPTNGI02` admission/discovery index and dispatch fence;
3. the durable provider execution ledger for physical model execution truth;
4. the independent checkpoint witness for accepted checkpoint frontiers;
5. the Agentd control-state record for lifecycle and generation topology.

Each domain is validated independently. Missing, corrupt, replaced, poisoned or
indeterminate state fails closed. A result committed locally is not result-use
authority, and a control-state record is not provider-execution authority.

## 2. Open joint-rollback gap

The current checkpoint witness does **not** independently authenticate every
admission and provider-dispatch frontier. An actor able to roll back both of the
following at the same time may remove evidence while leaving the checkpoint
frontier apparently unchanged:

```text
local admission / dispatch history
AND durable provider execution history
```

The runtime must therefore not claim protection from a host-level joint rollback
of both trust domains. Absence in both rolled-back histories is not authoritative
proof that physical execution never occurred.

Stable gap identifier:

```text
NR-SEC-ROLLBACK-001
```

Status:

```text
open_security_gap
```

Blocked claims:

```text
productExecutionProved
independentAcceptance
productionActivation
release
```

## 3. Acceptable closure designs

Closing `NR-SEC-ROLLBACK-001` requires one independently reviewed design and
same-candidate evidence for at least one of these profiles:

### A. Independently anchored admission/provider frontier

Publish a monotonic digest that binds:

- generation and execution epoch;
- exact operation key;
- reservation and dispatch frontier;
- provider ledger frontier and provider receipt identity;
- local result/failure frontier;
- predecessor anchor and checkpoint witness frontier.

The anchor must live outside the rollback domain of both local histories.

### B. Jointly signed provider and checkpoint frontier

The provider owner and checkpoint-witness owner sign one canonical frontier. The
signature scope must prevent mixing a current checkpoint with an older provider
or dispatch history. Key rotation, revocation and recovery must preserve the
frontier lineage.

### C. Explicit threat-model exclusion

A deployment may exclude a simultaneously privileged rollback of both domains
only through an explicit security and operator acceptance decision. The exclusion
must identify the trusted host controls, backup/restore controls, independent
monitoring and incident procedure. Source tests cannot make this decision.

## 4. Required verification

Whichever profile is selected must demonstrate:

- rollback of admission history alone is detected;
- rollback of provider history alone is detected;
- rollback of both histories at an unchanged checkpoint is detected or is an
  explicitly accepted threat-model exclusion;
- stale frontier replay, mixed-generation replay and key-rotation downgrade fail
  closed;
- backup/restore retains success, failure, reservation, dispatch and witness
  lineage;
- process termination at every publication cut cannot manufacture `NotStarted`;
- recovery never issues blind provider execution;
- historical generations remain queryable after handoff and restore.

Evidence must bind the exact source SHA, base SHA, tested tree, executable digest,
provider identity, storage identities, workflow run/attempt and retained logs.

## 5. Operational response

When a frontier mismatch, unexplained history loss or joint rollback is suspected:

1. keep every affected execution gate closed;
2. preserve local store, index, witness, provider ledger and control-state bytes;
3. do not delete files, reset a generation or create a replacement operation key;
4. compare the exact independent frontier and retained backup evidence;
5. reconstruct only from a topology and history set accepted by the documented
   recovery contracts;
6. reopen service only after exact reconciliation and independent operator review.

## 6. Relationship to other documents

- `V2_CONTROL_PLANE.md` defines permission and recovery boundaries.
- `V2_DURABLE_CONTROL_STATE.md` defines lifecycle/topology persistence.
- `V2_RUNBOOK.md` defines incident and generation-handoff actions.
- `SUPPORT_CALIBRATION.md` defines empirical acceptance contracts.

This register is intentionally conservative. Until `NR-SEC-ROLLBACK-001` is
closed or explicitly accepted by the deployment threat model, all production and
release claims remain false.
