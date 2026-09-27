# intelligence.control current implementation

This document records the current source implementation of `intelligence.control`. The stable architectural contract remains in `TECHNICAL.md`; machine-readable claim state is in `CURRENT_STATUS.json`. Exact commit/tree execution is established only by the independent `Hepta intelligence.control qualification` workflow receipt.

## 1. Current claim boundary

The canonical seven-owner composition source, authenticated `ObjectiveStart` route callsite, bounded concrete invocation provider, durable RunStart binding, Decision-before-ready rule, durable Decision/Outcome outbox, canonical candidate guard and profile-owned metrics are implemented in source.

The source does **not** establish production activation. At this stage:

- the atomically composed embedding profile exists;
- the standalone Agentd binary intentionally refuses the former runner-only CLI profile;
- exact-head and deterministic-merge execution remain false until terminal-green receipts exist;
- physical Agentd/App Server E2E, target-host qualification, independent acceptance, activation and release remain false.

`qualification-legacy-learning-write` is compatibility/qualification coverage only. It is not product completion evidence.

## 2. Canonical composition boundary

The canonical façade remains `prepare_intelligence_run` in `codex-rs/hepta-intelligence/src/canonical.rs`. It sequences exactly seven owners:

1. `objective.compiler`;
2. `utility.ndu`;
3. `neuron.runtime`;
4. `prompt.optimizer`;
5. `intuition.policy`;
6. `context.compiler`;
7. `learning.eval`.

The façade owns no durable objective, utility, neural, prompt, intuition, context, evaluation, model or learning fact. Its output carries `AuthorityPosture::DENY_ALL` and cannot dispatch a model, invoke a tool, grant production write authority, promote an artifact or release a candidate.

`canonical_guard.rs` wraps arbitrary owner ports before the core algorithm sees their receipts. It rejects producer/stage/snapshot/predecessor substitution and rejects a selected candidate that is not a member of the canonical legal candidate set. The canonical candidate set and the learning-ledger candidate-ID/completeness domains remain distinct digests and are both checked.

## 3. Unified generation and fence identity

`codex-rs/hepta-agentd/src/run_identity.rs` is the single constructor for the Agentd objective fence. The identity binds:

- agent identity;
- process spawn generation;
- current run generation.

A normal lifecycle is explicitly tested with `spawn_generation = 41` and `current_generation = 42`; the implementation no longer relies on them being equal.

`AgentdRunStartBindingV1` is constructed from the already authenticated durable `RunStartRecordV1`. Prepared intelligence inherits, rather than recomputes:

- run ID;
- admitted request digest;
- objective and hard-constraint digests;
- preference/model/prompt/artifact identities;
- runtime-body and ObjectiveFunction identities;
- profile and intent digests;
- authority epoch;
- current generation;
- objective fence;
- deadline.

`AgentRunCoordinator::start_bound_run` checks generation and fence against `RuntimeComposition` before a run can enter the daemon lifecycle. A mixed or stale snapshot fails before mutation.

## 4. Concrete provider and atomic profile

`AgentdIntelligenceInvocationRegistryV1` is the concrete product provider. It is a bounded registry of at most 256 one-shot factories keyed by durable run ID. A request can select only a previously registered run; it cannot supply owner profiles, model state, keys, evaluator trust, learning authority, currentness state or metrics.

The provider trait has a private sealed supertrait. External crates cannot implement a provider that falsely reports product readiness while omitting bounded storage, a durable learning owner or observability.

A product-ready provider requires all of the following:

- non-zero profile digest;
- durable `AgentdIntelligenceLearningHostV1`;
- inspectable bounded invocation registry;
- profile-owned runtime metrics.

Runner and provider setters are crate-private. External embeddings must use `AgentdCanonicalIntelligenceRuntimeProfileV1` or `compose_canonical_intelligence_profile_v1`, which attach runner and provider atomically. The standalone Agentd CLI rejects the former authority-file/signer/key triple because that combination could install only a runner.

`intelligence.canonical_v1` is advertised only when the runner and a product-ready sealed provider are both attached. Missing prerequisites produce no capability or fail startup/composition; they do not silently claim canonical execution.

## 5. ObjectiveStart to Ready transaction

For a compiled authenticated `ObjectiveStart`:

1. Objective runtime durably publishes `RunStartRecordV1` under the current Fleet generation and canonical fence.
2. Agentd asks the sealed provider for the exact one-shot invocation registered for that run.
3. Invocation validation compares the canonical request and owner inputs to the durable RunStart identity.
4. Agentd freezes only the small immutable runtime composition and releases the run mutex.
5. The runner executes the seven read-only owner stages inside a bounded blocking worker.
6. The runner performs final currentness validation and derives an authority-free dispatch proposal digest bound to the durable RunStart binding.
7. The host-owned Decision plan constructs the exact production Decision and writes its intent to the durable outbox before contacting the learning-ledger owner.
8. Agentd requires the Decision state to be `Acknowledged`.
9. Agentd revalidates the signed Objective and Fleet fence twice more.
10. Only then may the exact run enter `Admitted` and `ContextAttached`, and only then may `Ready` be returned.

A `Pending`, `Rejected`, `Revoked` or `Indeterminate` Decision cannot become a physical-turn binding.

## 6. Durable Decision and Outcome closure

`AgentdIntelligenceLearningOutboxV1` is an append-only, hash-chained JSONL outbox. It bounds record count, attempts, field sizes and replay work. Appends call `sync_all`; startup tolerates only an incomplete final line, truncates it, validates the retained chain and immediately reconciles pending records.

Its terminal states are explicit:

- `Acknowledged`: the destination owner returned an authenticated append receipt;
- `Rejected`: the destination deterministically rejected the exact event;
- `Revoked`: current trust or authority no longer permits the append;
- `Indeterminate`: maximum bounded attempts were exhausted without terminal proof.

No state is inferred from queue acceptance, handler return or process survival.

`AgentdIntelligenceDecisionPlanV1` binds the Decision to:

- the canonical run and episode;
- exact objective and run-snapshot identity;
- canonical candidate-set digest;
- sorted candidate-ID digest and canonical-order digest;
- selected candidate and non-zero propensity;
- dispatch-proposal digest;
- independent signed learning evidence.

After Decision acknowledgement, the plan publishes one immutable `IntelligenceLearningBindingV1`. Cloned live plans share one publication cell; conflicting publication fails closed.

`AgentdIntelligenceOutcomePlanV1` accepts only a terminal or censored independently observed outcome. It overwrites the caller-provided episode and support binding with the acknowledged Decision identity. The outcome support digest mixes the immutable run/Decision/candidate/dispatch binding with the physical terminal-observation digest.

After process restart, the physical dispatch owner may reopen `AgentdIntelligenceOutcomePlanV1` from the exact acknowledged binding it durably retained. It does not replay the Decision or model request. The physical App Server observer-to-Outcome callsite still requires real process integration and qualification.

## 7. Physical dispatch boundary

`AppServerModelDriver::run_intelligence` remains the named physical caller. It requires an already attached run/context/envelope binding, persists native dispatch before `turn/start`, revalidates the Agentd handoff immediately before the effect and reconciles transport loss by reading terminal provider state. A possibly dispatched run is never automatically redispatched.

This source binding is not proof that the current profile has executed against a real provider. Real-process tests must cover:

- lost `turn/start` acknowledgement;
- provider terminal reconciliation;
- Agentd and worker restart;
- dependency outage;
- generation, key and revocation races;
- terminal Outcome append after restart.

## 8. Resource isolation

Canonical candidates are limited to 128. The snapshot contains exactly seven owner bindings. Every stage budget is non-zero and the sum may not exceed the total cognition budget.

The runner owns four blocking worker permits. A request timeout does not pretend to kill `spawn_blocking`; the worker retains its permit until it actually exits. This prevents unbounded accumulation of abandoned work. The product records late workers and worker saturation explicitly.

This is effect isolation, not hard resource termination. Target-host production qualification still requires a killable process/driver boundary for any owner stage that cannot cooperatively observe cancellation or deadlines.

## 9. Observability

`AgentdIntelligenceRuntimeMetricsV1` belongs to one explicit provider profile. It is not a process-global registry and has no unbounded labels.

For each of the seven stages it records:

- calls and successes;
- rejected, unavailable, timed-out, quarantined and indeterminate failures;
- cumulative and maximum latency in microseconds.

The profile additionally records:

- worker-busy rejections;
- cognition timeouts and worker crashes;
- currentness and candidate-set rejections;
- active and completed late workers;
- Decision acknowledged/rejected/revoked/indeterminate counts;
- last observed authority epoch.

`AgentdCanonicalIntelligenceStatusV1` exposes the profile digest, pending invocation count, durable learning reconciliation backlog, worker capacity/availability and one metrics snapshot. Run-phase dwell metrics and target-host RSS remain future qualification work.

## 10. Source verification and CI

`scripts/hepta_intelligence_control_status.py` is the source-truth verifier. It checks the actual symbols and ordering needed for:

- unified generation/fence identity;
- durable RunStart inheritance;
- sealed concrete provider and atomic-only profile;
- standalone runner-only refusal;
- Decision-before-ready ordering;
- durable outbox and restart Outcome binding;
- canonical selected-candidate membership;
- profile-owned metrics and late-worker accounting.

`.github/workflows/hepta-intelligence-control.yml` runs independently of unrelated repository lanes. For pull requests it executes both source-head and deterministic synthetic-merge candidates, with matrix fail-fast disabled. It runs source checks, formatting, focused package tests and strict Clippy, then retains a receipt containing exact commit, tree and source digest.

A checked-in document or test name never sets `exactHeadExecuted` or `deterministicMergeExecuted` to true. Those fields advance only from terminal-green exact-candidate receipts.

## 11. Remaining product gates

The following remain open even after source compilation succeeds:

1. Wire the real physical terminal observer into `AgentdIntelligenceOutcomePlanV1` and durably retain its acknowledged binding at the dispatch owner.
2. Complete real-process Agentd/App Server E2E for lost acknowledgement, restart, dependency outage and revocation races.
3. Qualify a killable owner-process boundary for non-cooperative synchronous stages.
4. Collect target-host latency, RSS, saturation and reconciliation-backlog evidence.
5. Obtain independent semantic and security acceptance.
6. Obtain operator acceptance, activation, promotion and release authorization.

Until those gates close, `productionImplementation`, `productExecutionProved`, `targetHostQualified`, `independentAcceptance`, `activation` and `release` remain false.
