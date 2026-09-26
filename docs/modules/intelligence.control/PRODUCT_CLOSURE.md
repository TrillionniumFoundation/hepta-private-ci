# intelligence.control product-closure guide

Parent: [`TECHNICAL.md`](TECHNICAL.md). Canonical source root:
`codex-rs/hepta-intelligence`. Product integration owner:
`codex-rs/hepta-agentd`.

This guide describes the product-closure source introduced after the canonical
seven-owner façade. It is deliberately narrower than an activation or release
claim. Exact-head and synthetic-merge execution, real-process provider/App
Server qualification, target-host measurements and independent acceptance
remain separate evidence gates.

## 1. One generation and fence model

A canonical intelligence run has one physical identity derived from the durable
`RunStartRecordV1`; the cognition runner may not reconstruct or substitute it.
`AgentdIntelligenceRunIdentityV1::from_run_start` binds:

- authenticated issuer, key epoch, message identity, sequence, expiry, scope,
  signed body and signature;
- objective profile and admitted source identity;
- run, objective, hard-constraint, preference, model, prompt-registry and
  artifact identities;
- authority epoch, current lifecycle generation and objective fence;
- runtime body, objective semantic bytes and ObjectiveFunctionV1 identity;
- the owner-controlled deadline.

The lifecycle relation is explicit:

```text
process launch generation = spawn_generation
Running generation        = spawn_generation + 1
Draining generation       = spawn_generation + 2
```

`objective_run_fence_digest_v1(agent_id, spawn_generation,
current_generation)` is the only fence constructor used by ObjectiveStart,
invocation validation, prepared-run publication and composition-bound
admission. `AgentRunCoordinator::start_bound_run` rechecks the exact process
identity before it mutates run state. Compatibility `start_run` remains for
older noncanonical callers and is not the canonical product admission API.

## 2. Host-owned invocation provider

`HostOwnedAgentdIntelligenceInvocationProviderV1` is the concrete provider. Its
factory derives all seven owner values from host-owned current sources; request
bytes cannot provide policy, model, artifact, trust, currentness or run identity.
The provider overwrites any factory-supplied run identity with the exact durable
RunStart binding and validates the completed invocation before returning it.

Product embeddings should install runner and provider atomically:

```rust,ignore
config.with_canonical_intelligence_profile(runner, |identity, record| {
    // Read the seven current owner sources and return the typed request/inputs.
    build_current_intelligence_invocation(identity, record)
})?;
```

The older independent runner/provider setters remain compatibility composition
seams. A runner alone never advertises `intelligence.canonical_v1`.

The ordinary command-line binary currently configures the signed authority
runner only. It has no ambient authority to manufacture seven owner inputs and
therefore does not install a canonical provider or advertise the capability.
This is intentional fail-closed behavior, not a product-execution claim.

## 3. Canonical invariant gate

The pure façade canonicalizes legal candidates before product comparison.
`validate_canonical_outcome_v1` is the final pure gate and rejects:

- run or snapshot substitution;
- candidate-set digest drift;
- a selected candidate outside the admitted legal set;
- a selected candidate with zero propensity;
- a Ready/Abstained/SlowPath outcome whose terminal decision kind disagrees.

Agentd compares canonical sorted candidate identities, not caller vector order.
Malicious-port tests cover an out-of-set selection and zero propensity. The
existing currentness checks still run before and after each owner call and once
more immediately before dispatch-proposal publication.

## 4. Formal Decision and Outcome closure

The default product path uses only `learning.ledger::LedgerWriter`:

- `append_intelligence_decision_v1` creates an authenticated
  `ProductionDecisionV2`;
- `append_intelligence_outcome_v1` creates an authenticated terminal Outcome;
- no default-build product method calls `append_qualification`.

The legacy runner methods guarded by
`qualification-legacy-learning-write` remain explicit qualification-only
surfaces and are reported separately by generated traceability.

`AgentdIntelligenceLearningHostV1` persists an immutable payload sidecar, syncs
it and its directory, then commits a `kernel.operations` intent/outbox row.
Final-use authority is checked immediately before the only product ledger
writer is called. Recovery reopens the operations store and replays the exact
payload, operation identity and original ledger predecessor; it never creates a
new logical event.

Terminal semantics are closed:

| Product disposition | kernel.operations terminal state | Meaning |
|---|---|---|
| `Acknowledged` | `Applied` | LedgerWriter returned an append/idempotent receipt |
| `Rejected` | `NotApplied` | Typed binding, evidence, CAS or schema rejection |
| `Revoked` | `Quarantined` | Current evidence/trust is revoked |
| `Indeterminate` | nonterminal `Indeterminate` | Commit may have happened; exact reconciliation only |

The learning host exposes `OperationBacklogMetrics`, including queued, leased,
acknowledged, indeterminate and terminal counts.

## 5. Physical terminal binding

An Outcome is not accepted merely because a model call returned. The support
digest from `intelligence_physical_terminal_binding_digest_v1` binds:

- exact RunStart-derived request/body/artifact/authority/generation/fence;
- exact context and envelope digests;
- exact advisory decision, selected candidate and propensity;
- terminal Agentd run phase and revision;
- independently observed provider terminal digest.

The Outcome path verifies that the active authenticated Decision has the same
episode, run-snapshot digest and selected candidate. Pending or nonterminal
outcomes cannot close the canonical product episode.

## 6. Bounded execution and hard timeout policy

The runner retains four bounded blocking-worker slots. A permit remains owned by
the actual worker after request timeout, so abandoned synchronous work cannot
silently free capacity and multiply without bound.

`AgentdIntelligenceTelemetryV1` reports:

- active and peak workers, configured slots and Busy rejections;
- request timeouts, late completions, hard-timeout trips and worker crashes;
- run-identity, currentness and canonical rejections;
- Ready, Abstained and SlowPath totals;
- last observed authority epoch and manifest-read count;
- per-stage latency count/total/max and Rejected, Unavailable, TimedOut,
  Quarantined and Indeterminate failure counts;
- whether the host-owned invocation provider is attached.

Pure synchronous Rust cannot be killed safely from another in-process task.
An explicitly configured product runner may therefore use
`with_hard_timeout_process_exit(grace)`. If a timed-out blocking worker remains
alive after the bounded grace, Agentd exits with code 70. Supervisor recovery
creates a fresh fenced process generation; no old in-process authority survives.
Compatibility and tests do not enable this policy implicitly.

`capability_profile_digest` binds authority-file identity, verifier, worker
capacity, hard-timeout policy and evaluation-trust generation. It is the
configuration identity for qualification receipts; it is not an activation
grant.

## 7. Generated implementation truth

`scripts/hepta-intelligence-control-status.py` is the only writer for:

- `IMPLEMENTATION_MAP.json`;
- `TEST_TRACEABILITY.json`.

Tracked files use the literal `CI_EXACT_HEAD` marker to avoid a self-referential
commit. Independent intelligence CI regenerates both files after source-head or
synthetic-merge tests with the exact checkout SHA and asserts that SHA equals
`git rev-parse HEAD`. Those exact documents and command records are retained as
artifacts.

The status matrix separates:

- source presence;
- daemon route callsite;
- concrete provider implementation;
- atomic product composition;
- default-binary composition;
- durable product learning and reconciliation;
- exact-head and synthetic-merge execution;
- real-process E2E;
- target-host qualification;
- independent acceptance, activation and release.

Qualification-only tests and APIs are listed separately and cannot establish a
default product claim.

## 8. Restart and reconciliation runbook

### Before ContextAttached

A published RunStart with canonical profile enabled is not silently projected
through compatibility admission. The authenticated ObjectiveStart must be
retried so the same durable record can derive the same invocation and run
identity.

### ContextAttached but not dispatched

The exact Agentd run/context record is reused. A physical caller must match the
run ID, revision, context and envelope before it can advance to Dispatched.

### Possible turn/start with no acknowledgement

The native execution journal reconciles terminal provider evidence. Absence of
exact terminal evidence produces `Indeterminate`; automatic redispatch is
forbidden.

### Decision/Outcome append uncertainty

The operations row and immutable payload survive process loss. Restart adopts
the unsettled operation into the new owner generation and invokes the same
LedgerWriter request. Ledger record identity and predecessor CAS make an
already-applied mutation idempotent. Current revocation may instead quarantine
the operation; it never converts uncertainty into success.

## 9. Remaining external gates

The following are not claimed by this source change:

1. real-process host-owned provider → authenticated ObjectiveStart → physical
   App Server → terminal Outcome E2E;
2. target-host latency, RSS, worker saturation and hard-timeout restart
   measurements;
3. current exact-head and deterministic synthetic-merge terminal-green receipts;
4. independent semantic/security review and operator acceptance;
5. activation, canary promotion or release.

Until those receipts exist, `intelligence.canonical_v1` remains a configured
profile capability, not a repository-wide default or deployment claim.

## Daemon-owned product-learning service

`AgentdIntelligenceLearningRuntimeConfigV1` composes the durable learning host into the normal Agentd task owner without manufacturing authority. It is accepted only after the all-or-none canonical profile, must bind the unique Running generation, and runs restart reconciliation before bounded prepared-outbox dispatch. The required service is generation-fenced before and after destination work. The default binary remains fail-closed because it does not construct this config.
