# Hepta module technical guides

This directory contains exactly one stable implementation guide for every module registered in `MODULES.json`. Machine-readable coverage and digests are in `MODULE_DOCS.json`; source reality is in `SOURCE_BINDINGS.json`. A guide explains implementation and operations but grants no runtime, acceptance, promotion or release authority.

## Guides

- [`platform.types`](platform.types/TECHNICAL.md) — `existing_bound`, bootstrap `PLATFORM-0-TYPE-BOUNDARY`.
- [`platform.wire`](platform.wire/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7E-DEPENDENCY-INVERSION`.
- [`kernel.authority`](kernel.authority/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B0-VERIFIED-USE`.
- [`kernel.operations`](kernel.operations/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7D-FAULT-MATRIX`.
- [`kernel.evidence`](kernel.evidence/TECHNICAL.md) — `existing_bound`, bootstrap `P0.9-EXTERNAL-GATES`.
- [`runtime.supervisor`](runtime.supervisor/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7A-RUNTIME-BOOTSTRAP`.
- [`runtime.fleet`](runtime.fleet/TECHNICAL.md) — `existing_bound`, bootstrap `FLEET-1-ALLOCATION-CONTRACT`.
- [`runtime.agentd`](runtime.agentd/TECHNICAL.md) — `existing_bound`, bootstrap `P0.8B-READINESS`.
- [`runtime.codex`](runtime.codex/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B1B-MODEL-BOUNDARY`.
- [`auth.authbus`](auth.authbus/TECHNICAL.md) — `existing_bound`, bootstrap `AUTHBUS-P1.3-V12`.
- [`secrets.heptabao`](secrets.heptabao/TECHNICAL.md) — `existing_bound`, bootstrap `HEPTABAO-1-SECRET-BOUNDARY`.
- [`inference.control`](inference.control/TECHNICAL.md) — `existing_bound`, bootstrap `P0.7B-B1A-PROVIDER-BOUNDARY`.
- [`inference.worker`](inference.worker/TECHNICAL.md) — `existing_bound`, bootstrap `INFER-V4-T4`.
- [`objective.compiler`](objective.compiler/TECHNICAL.md) — `existing_bound`, bootstrap `OBJ-0-OBJECTIVE-CONTRACTS`.
- [`utility.ndu`](utility.ndu/TECHNICAL.md) — `existing_bound`, bootstrap `NDU-0-PREFERENCE-UTILITY-CONTRACTS`.
- [`neuron.runtime`](neuron.runtime/TECHNICAL.md) — `existing_bound`, bootstrap `BIO-0-NEURON-INTUITION-CONTRACTS`.
- [`intuition.policy`](intuition.policy/TECHNICAL.md) — `existing_bound`, bootstrap `INT-1-CALIBRATED-INTUITION-POLICY`.
- [`prompt.registry`](prompt.registry/TECHNICAL.md) — `existing_bound`, bootstrap `PIM-0-PROMPT-INTERVENTION-CONTRACTS`.
- [`prompt.optimizer`](prompt.optimizer/TECHNICAL.md) — `existing_bound`, bootstrap `PIM-2-PROMPT-PRICING-PORTFOLIO-SHADOW`.
- [`context.compiler`](context.compiler/TECHNICAL.md) — `existing_bound`, bootstrap `CTX-1-CONTEXT-COMPILER`.
- [`intelligence.control`](intelligence.control/TECHNICAL.md) — `existing_bound`, bootstrap `INTELLIGENCE-A0-Q0.63`.
- [`cognitive.types`](cognitive.types/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-0-TYPES`.
- [`cognitive.store`](cognitive.store/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-1-STORE`.
- [`cognitive.read`](cognitive.read/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-READ-1-SNAPSHOT-PORT`.
- [`memory.retrieval`](memory.retrieval/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-2-RETRIEVAL`.
- [`memory.federation`](memory.federation/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-3-FEDERATION`.
- [`knowledge.graph`](knowledge.graph/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-4-KG`.
- [`compact.engine`](compact.engine/TECHNICAL.md) — `existing_bound`, bootstrap `MEM-5-COMPACT`.
- [`learning.ledger`](learning.ledger/TECHNICAL.md) — `existing_bound`, bootstrap `LRN-0-CAUSAL-LEARNING-CONTRACTS`.
- [`learning.operator`](learning.operator/TECHNICAL.md) — `existing_bound`, bootstrap `HBO-0-BELLMAN-OPERATOR-CONTRACTS`.
- [`learning.eval`](learning.eval/TECHNICAL.md) — `existing_bound`, bootstrap `LRN-2-CAUSAL-EVALUATION`.
- [`learning.artifacts`](learning.artifacts/TECHNICAL.md) — `existing_bound`, bootstrap `ART-1-LEARNING-ARTIFACT-REGISTRY`.
- [`learning.plasticity`](learning.plasticity/TECHNICAL.md) — `existing_bound`, bootstrap `PLS-1-PARAMETER-PLASTICITY`.
- [`automation.taskflow`](automation.taskflow/TECHNICAL.md) — `existing_bound`, bootstrap `TASKFLOW-1-EXECUTION-BOUNDARY`.
- [`channel.matrix`](channel.matrix/TECHNICAL.md) — `existing_bound`, bootstrap `MATRIX-1-CHANNEL-BOUNDARY`.
- [`browser.servo`](browser.servo/TECHNICAL.md) — `existing_bound`, bootstrap `BROWSER-WEB-C1`.
- [`ui.control`](ui.control/TECHNICAL.md) — `existing_bound`, bootstrap `UI-V5`.
- [`ui.native`](ui.native/TECHNICAL.md) — `existing_bound`, bootstrap `UI-NATIVE-1-SHELL`.
- [`control.runtime`](control.runtime/TECHNICAL.md) — `existing_bound`, bootstrap `RCP-1-RUNTIME-CONTROL-PLANE`.
- [`control.engineering`](control.engineering/TECHNICAL.md) — `existing_bound`, bootstrap `ECP-1-ENGINEERING-CONTROL-PLANE`.

## Adaptive algorithm overlay

The module guides above define ownership, boundaries and delivery envelopes. Implementation-level mathematics, algorithms, data lineage and quantitative acceptance gates for the fourteen adaptive modules are closed separately in [`../learning/README.md`](../learning/README.md) and bound by [`../learning/ALGORITHM_SPECS.json`](../learning/ALGORITHM_SPECS.json). This overlay does not change any module source status or capability claim.

## Pre-coding readiness overlay

Every guide now includes Section 16, which binds the module to one primary implementation lane and the exact specifications and typed protocols in [`../readiness/README.md`](../readiness/README.md). The overlay closes implementation ambiguity but does not change source or capability status.

## HeptaBao executable connection

For the implemented host-enrolled read path, continue from the `kernel.authority`, `runtime.supervisor` and `secrets.heptabao` guides to the [final-use and issuer design](../../codex-rs/hepta-contracts/FINAL_USE.md) and [HTTPS consumer integration](../../codex-rs/hepta-bao-adapter/README.md). They specify the actual signatures, persistent state schema, atomic-write and revocation fences, callback trust boundary, APIs, failure outcomes and tests. The earlier metadata-only adapter API remains available with dispatch disabled. These implementation notes add no automatic runtime enrollment or release authority.

## Shared implementation requirements

These requirements are shared by the module guides; moving the identical text here does not remove a requirement. Apply state, migration and external-effect obligations to the owner that actually holds that boundary. A pure value library does not acquire a database or daemon merely to satisfy a template. Each guide links its current native implementation, tests and operating instructions separately from the target design.

### Shared concurrency and transactions

Central synchronous RPC on the local hot path is `false`. Bounded cached control input is `true`. A fallback is required: `true`.

Ingress enforces queue, payload, concurrency and deadline limits. Cancellation is observed at defined boundaries and cannot relabel a terminal state already being committed. Retries require a stable operation identity and equal semantic digest. Timeout at an external boundary becomes indeterminate absent verified terminal acknowledgement.

State transitions are monotonic within an attempt. A crash between authorization and terminal observation leaves pending or indeterminate state, never invented success. Reconciliation is fenced by authority epoch and predecessor identity. Concurrent writers use transactions or compare-and-swap; last-write-wins is forbidden for authoritative facts.

### Shared failure and recovery

Failures are classified as validation rejection, authority rejection, unavailable dependency, bounded timeout, storage failure, conflict, cancellation, indeterminate effect, integrity failure or internal invariant violation. Errors expose safe identifiers and digests, not raw secrets, provider payloads or untrusted content.

Startup validates configuration, schema and integrity, recovers incomplete local transactions, scans outbox state and gates readiness in that order. Integrity uncertainty, unknown schema or conflicting durable identity fails closed or quarantines. Optional context or advisory signals degrade only when fallback cannot widen authority.

Every state-changing package names a rollback predecessor and tests crash/reopen behavior. Rollback restores code, configuration and compatible state. External effects are never rolled back by assumption; they require acknowledgement, compensation or quarantine.

### Shared performance and capacity

Implementing packages publish measurable latency, throughput, memory, storage growth, queue depth and recovery budgets. Bounds are enforced, not only observed. Backpressure rejects or sheds explicitly and never creates unbounded tasks or retries.

Hot paths avoid global locks, synchronous central control and full-store scans. Expensive verification uses bounded indexes, snapshots or staged slow paths. Caches bind revision and expiry and invalidate on revocation, correction, deletion or generation change. Benchmarks include steady state, cold start, maximum input, contention, degraded dependency and recovery.

### Shared observability and operations

Structured events include module, operation or attempt identity, source revision, outcome class, duration, bounded resource use and safe digest references. Metrics include ingress, rejection, saturation, transaction conflicts, dependency latency, reconciliation backlog, integrity failures, fallback use and recovery duration.

Readiness means required dependencies, schema and integrity are verified; liveness only means progress is possible. Operator surfaces never expose raw secrets or unbounded payloads. Alerts cover sustained rejection, retry storms, aged pending/indeterminate state, integrity failure, capacity exhaustion, projection lag and rollback failure.

### Shared verification and qualification

Minimum checks are exact source identity, source inventory, static verification, focused tests, package tests, all-target compilation, strict lint, clean worktree, exact-head execution and synthetic-merge execution. Stateful modules add migration, crash/reopen, corruption, idempotency, conflict and reconciliation. Adapters add revoked/stale grant, payload drift, timeout and indeterminate-outcome tests.

The implementing team cannot issue independent acceptance. Fixture success proves only the tested boundary at the exact candidate; it does not prove a production caller, physical effect, operator acceptance, promotion or release.

## Maintaining source navigation and indexes

Read each guide with its module-specific current native implementation, existing operation map (where present), source-adjacent state/operating notes and named test sources. Target signatures stay explicitly separate from current native exports; unimplemented effects, stores, drivers or consumers remain implementation work even when every document exists. Current test counts and source observations are computed by the existing verifiers, not copied as live facts into prose.

After editing a guide or module detail, run from the repository root:

```sh
python3 scripts/hepta-module-docs.py refresh-indexes
python3 scripts/hepta-module-docs.py refresh-indexes --check
python3 scripts/hepta-module-docs.py verify
python3 scripts/hepta-readiness.py verify
python3 scripts/hepta-technical-closure.py verify
```

The refresh command updates only derived guide byte/word counts and guide/detail digests in the existing indexes. It does not change module scope, implementation status, authority or acceptance. The module verifier also rejects missing local source/test/operating-document links and Markdown anchors. Structural success still does not prove a compiled API, an executed product test or a deployed consumer.
