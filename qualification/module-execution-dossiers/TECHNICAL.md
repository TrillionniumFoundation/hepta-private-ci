# Hepta all-module execution and evolution technical specification

**Parent plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Readiness overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Coverage:** all forty registered modules, seven implementation lanes and twenty-four CNS organ roles  
**Status:** documentation-depth closure; source, runtime, hardware, future-window and independent-decision evidence are not implied

## 1. Scope and truth boundary

This specification turns the existing module guides, source bindings, readiness protocols and CNS anatomy into an execution dossier that a module team can implement without inventing runtime assumptions. It is a qualification companion, not a second global plan. Canonical identity, ownership, contracts, data authority, work packages, source roots and claim levels remain in their existing registries.

A dossier closes a documentation ambiguity only when it identifies the exact information that later evidence must contain. It does not claim that an executable process exists, that a library has a production caller, that a physical store has been deployed, that a real model has been used, that future behavior improved, that a hardware loop is safe, or that an independent operator accepted a candidate.

The common completion model is deliberately split:

```text
specified
-> source_implemented
-> contracts_compiling
-> host_composed
-> qualification_executed
-> independently_evaluated
-> next_snapshot_loaded
-> rollback_qualified
-> longitudinally_validated
-> separately_selected/promoted/released
```

No later state may be inferred from an earlier state. In particular, directory presence is not process activation, a fixture is not a production caller, candidate registration is not selection, and queue acknowledgement is not terminal effect success.

## 2. Module execution receipt contract

Every module integration checkpoint must materialize all eighteen fields below. The record is immutable for one exact candidate and one process/body generation.

| Field | Required meaning | Rejection condition |
|---|---|---|
| `sourceReceipt` | exact commit, tree, target, ordered parents and observation time | branch name, moving tag or stale cached fact used as identity |
| `moduleGuideDigest` | exact digest of the module technical guide used by the team | guide changed after implementation started |
| `declaredSourceRoots` | canonical roots from `SOURCE_BINDINGS.json` | implementation outside owned roots without co-owner envelope |
| `entrypoints` | executable, library, worker, adapter or migration entrypoint | only a directory or package name is supplied |
| `consumerCallsites` | named product or qualification callers and invoked port | consumer is inferred from dependency metadata only |
| `hostRuntimeIdentity` | process/image/host/runtime/device tuple | host is unknown, mutable or qualification-only but labelled production |
| `binaryOrArtifactDigest` | binary, image, model, adapter or script identity | version string without content identity |
| `configurationAndBodyGeneration` | immutable config, objective, model and body generations | mixed generations or implicit global configuration |
| `ownedPhysicalState` | files, database, keyspace, remote owner or `none_by_design` proof | memory-only fixture presented as durable state |
| `schemaAndMigration` | DDL/byte format, version, migration and restore algorithm | migration omitted for state-bearing module |
| `singleWriterFence` | writer identity, lease/CAS/fence and shard rule | multiple writers rely on last-write-wins |
| `terminalObserver` | owner that can observe the terminal outcome | policy, dispatcher or queue self-labels success |
| `revocationSource` | epoch, tombstone, consent or artifact revocation authority | cached grant cannot be invalidated |
| `faultResults` | profile-specific crash, corruption, timeout and drift evidence | happy-path unit test is the only evidence |
| `resourceMeasurements` | target-host p50/p95/p99 and bounded resource observations | estimates or developer workstation numbers replace target measurements |
| `fallback` | deterministic, bounded and no-authority-widening fallback | failure silently retries or expands permissions |
| `rollbackPredecessor` | exact compatible predecessor and recovery procedure | “reinstall previous version” without state compatibility proof |
| `externalGateDisposition` | each applicable `RDY-EXT-*` gate with evidence or open state | documentation marks an external gate passed |

`none_by_design` is valid only when the module is demonstrably stateless or has no terminal-effect boundary. The receipt must cite the type or test that proves absence. It is not a placeholder for work deferred to another team.

## 3. Entrypoints, callers and runtime composition

A module is runtime-composed only when the receipt names the code entrypoint, host process, configuration source, readiness dependencies, shutdown path and at least one real caller. Cargo/Bazel membership proves build reachability but not product reachability. An integration test calling a library directly proves a boundary only at the qualification level unless the same path is invoked by the named product host.

Composition follows these rules:

1. A pure library names exported symbols and every host that loads it.
2. A service names the executable, socket/IPC endpoints, startup ordering, readiness condition and shutdown fence.
3. An offline worker names its scheduler, immutable input snapshot, output registry, resource budget and retry identity.
4. An effect adapter names the caller, consumed authority, final payload digest, destination identity, terminal observer and reconciliation path.
5. A UI names its backend protocol, session generation, stale-view rejection and human override semantics.
6. A model-bearing module names weights, tokenizer, preprocessing, quantization, runtime, device and actual consumer.

The host cannot acquire ownership of a domain merely because it embeds a library. Data authority remains with the canonical module writer. Cross-owner changes use durable intent, destination deduplication, acknowledgement and fenced reconciliation.

## 4. Physical state, schema and single-writer semantics

Each state-bearing module classifies every state surface as authoritative, append-only event source, immutable artifact, rebuildable projection, cache, checkpoint or external-owner reference. The classification determines migration and rollback behavior.

Authoritative state requires one schema owner and one writer. Append-only state never rewrites history; corrections and deletion append superseding or revocation records. Rebuildable projections publish a complete generation atomically and can be discarded without losing source facts. Caches bind source generation and expiry. Checkpoints bind model, configuration and predecessor generations. External-owner references never turn a local mirror into the source of truth.

The minimum durable-state specification contains:

```text
format/DDL and canonical encoding
identity and predecessor keys
transaction and fsync/publication boundary
idempotency and semantic-conflict rule
writer fence and shard/lease key
migration precondition and postcondition
crash recovery and corruption quarantine
backup/restore compatibility
retention, correction, deletion and revocation traversal
resource growth and compaction envelope
```

A crash after a durable write but before acknowledgement is reconciled from the stable operation identity and semantic digest. Blind retry is forbidden. Restoring a backup that predates a revocation requires replaying the revocation frontier before the restored state can become readable.

## 5. Fault, recovery and fallback profiles

The machine dossier assigns one mandatory fault profile to every module. Profiles are additive: a module crossing multiple boundaries runs every relevant profile even when one is designated primary.

### 5.1 Contract and pure-library profile

Required cases are minimum/maximum values, unknown critical fields, canonical ordering, digest stability, invalid units, overflow, deterministic replay and cross-language parity. The library must have no ambient authority or hidden mutable singleton.

### 5.2 Durable-owner profile

Required cases are stale predecessor, semantic ID conflict, crash before/after commit, acknowledgement loss, filesystem full, truncated frame, checksum corruption, nonempty WAL/journal, reopen, migration failure, backup restore, concurrent writer and deletion non-resurrection.

### 5.3 Process and control-plane profile

Required cases are startup dependency unavailable, stale generation, watchdog expiry, cancellation at every state transition, bounded queue saturation, process kill/restart, split-brain fence, configuration drift and safe degradation during central outage.

### 5.4 External-effect adapter profile

Required cases are revoked/stale grant, payload drift, destination drift, timeout, acknowledgement loss, duplicate operation, terminal observer disagreement, partial effect, compensation failure and indeterminate reconciliation. Transport acceptance remains non-terminal.

### 5.5 Read/projection profile

Required cases are stale snapshot, incomplete generation, source correction, projection lag, cache revocation, deletion rebuild, unavailable dependency, bounded truncation and deterministic fallback without widening authority.

### 5.6 Learning and artifact profile

Required cases are incomplete candidate set, zero propensity, unsupported evaluation policy, outcome correction, evaluator collision, future leakage, revoked training row, corrupt artifact, mixed generation, incompatible predecessor, failed reload and restore of pre-revocation state.

### 5.7 Embodied and assimilation profile

Required cases are stale calibration, clock drift, sensor disagreement, body-generation mismatch, watchdog expiry, emergency stop, actuator saturation, host reboot, malicious package metadata or maintainer script, path escape, owner-consent expiry, migration interruption and unauthorized peer enrollment.

Fallback is an explicit state transition, not an exception handler. It reduces capability, preserves the immutable objective and cannot borrow from safety, evidence or rollback budgets.

## 6. Performance and resource measurement

Every implementation publishes comparable baseline and candidate measurements on a named target profile. Measurements bind source, binary/artifact, host, operating system, runtime, configuration, body generation, dataset, load shape and observation interval.

The common metric set is:

```text
throughput and completed operations
p50/p95/p99 latency and deadline misses
CPU, accelerator, resident memory and transient allocation
storage growth, write amplification, WAL/journal and compaction cost
queue depth/age, retries and reconciliation backlog
file descriptors, processes, sockets and network bytes
model tokens/context, cache hit, OOD and abstention where applicable
energy, temperature, jitter and sensor age for embodied paths
confidence intervals and censoring/incomplete counts
```

A module-specific profile may mark metrics not applicable, but must explain why. Average latency cannot hide p99 or deadline failure. A simulator benchmark cannot replace target-host timing. Training cost and runtime cost are reported separately. Resource ceilings are enforced at ingress and scheduler boundaries rather than merely observed after overload.

## 7. CNS organ mapping and multi-timescale control

The forty software modules are projected into twenty-four functional organ roles. A module may participate in several organs, but retains one primary development lane and one data owner. Organ composition does not merge durable facts.

The control hierarchy uses five time scales:

```text
reflex: local deterministic veto/clamp/stop
sensorimotor: coherent body-state estimation and feedback
cognitive: objective-bound planning, retrieval and tool use
consolidation: replay, evaluation and next-snapshot candidate creation
development: code/topology proposals and governed rollout
```

No slow loop blocks a faster safety loop. The constitutional kernel, human override and reflex safety remain outside the learnable surface. Runtime feedback may be cyclic only when sampling period, delay, gain, uncertainty, saturation and stop policy are explicit. Initialization, schema ownership and activation dependencies remain acyclic.

Organ lifecycle is generation-bound:

```text
proposed -> built -> simulated -> qualified -> dormant -> canary -> active
active -> draining -> retired
any qualified/active state -> quarantined
```

Adding, splitting, merging, rewiring or retiring an organ creates a next-generation proposal. The current graph remains immutable. Draining blocks new work, reconciles outstanding operations, migrates or tombstones state and proves fallback readiness before retirement.

## 8. NDU participation and non-applicability

NDU subjects are restricted to system, domain, agent and episode. Software modules and organs are not NDU subjects merely because they emit forward/backward data. The execution dossier classifies each module into one of these roles:

| Role | Meaning |
|---|---|
| immutable hard filter | authority, truth, privacy, deletion, consent and emergency state remove infeasible candidates before utility arithmetic |
| objective source | immutable request success, legal actions and evidence requirements define the run objective |
| preference/utility owner | `utility.ndu` owns bounded preference and recursive-utility projections |
| bounded contributor | module emits utility, risk, resource, uncertainty or support observations with units and generation |
| action consumer | policy or controller consumes NDU summaries but cannot rewrite them or issue authority |
| outcome/evaluation owner | independently observed outcomes and causal estimates judge future candidates |
| artifact/next-snapshot owner | immutable coefficient, policy and topology candidates are stored for later selection |
| non-applicable transport | component carries typed data without interpreting or optimizing utility |

The baseline solver is deterministic fixed-point feasibility, Pareto filtering and registered scalarization. Learned FBSDE coefficients remain shadow candidates until well-posedness, support, stability, future-window, retention and rollback gates pass. Parent and child preference artifacts are not selected in the same generation. Missing contribution is uncertainty/unavailability, not zero utility.

NDU does not replace the world model. The world model estimates consequences; NDU values supported consequences under the frozen objective and bounded preference state. NDU also does not replace causal evaluation: an internal utility increase is not an independently observed task improvement.

## 9. Longitudinal learning closed loop

The minimum executable loop is deliberately end-to-end:

```text
real request and immutable objective
-> complete legal candidate set and assignment propensity
-> selected read-only action/intervention
-> independently observed outcome and watermark
-> durable ledger reopen and correction/revocation cutoff
-> immutable dataset snapshot
-> bounded candidate training with exact code/runtime lineage
-> preregistered disjoint evaluation and retention slices
-> independent candidate decision
-> immutable artifact registration
-> new process generation loads selected candidate
-> changed future behavior is observed
-> exact predecessor rollback is rehearsed
```

A module test may close one boundary but not this loop. Longitudinal evidence requires future calendar windows and independent snapshots; timestamps generated in one fixture cannot substitute. Missing or delayed outcome remains pending or censored. The evaluated policy cannot write its own terminal outcome, conserved credit or acceptance receipt.

The first vertical slice remains read-only retrieval/context use so the system can prove candidate completeness, causal attribution, persistence, reload and rollback without external effects. Physical and mutating actions enter only after the same evidence chain works in a bounded domain.

## 10. Governed module self-iteration

Self-iteration generates candidates under a frozen envelope. The mutation grammar is typed: parameter delta, prompt factor change, workflow step, skill revision, code AST/file change and organ topology operation. No-change is always a candidate.

A module candidate binds exact base, allowed roots, contract and guide digests, objective, generator, seed, semantic diff, mandatory tests, resource delta, authority delta and rollback predecessor. It cannot modify the authority rules, hidden tests, evaluator configuration, deletion policy or evidence that judges the same candidate.

The generator may advance a candidate only through sandbox testing. Independent identities are required for evaluation, review, acceptance, selection, merge, promotion and release. Independence means different principals and credential/signing chains, not the same model with a different prompt.

For structural operations:

- `add` proves contracts, owner, resource envelope, fallback and absence of duplicate authority;
- `split` proves state partition, migration and caller routing;
- `merge` proves owner consolidation without history loss or wider authority;
- `rewire` proves dependency, feedback stability and fallback reachability;
- `retire` drains work, reconciles effects and preserves historical interpretability.

Canary abort fences new work, reconciles outstanding operations, reloads the exact predecessor and verifies the revocation frontier. Compensation is a new authorized action, never an assumed rollback.

## 11. Generic external-system assimilation

Assimilation begins from explicit owner consent and one bounded system boundary. The initial Debian service is a fixture for the general algorithm, not a special case that grants operating-system takeover.

### 11.1 System classification

The discovery stage classifies the target as library, CLI, daemon, service graph, desktop application, data system, device driver, robotics controller or operating-system substrate. Classification identifies observation and effect boundaries; it does not infer authority.

### 11.2 Manifest and contract synthesis

Discovery records source/package identity, licenses/SBOM, signatures, APIs, CLI/D-Bus/socket schemas, service dependencies, users/capabilities, filesystems, mutable state, resource behavior, health, restart and backup ownership. Raw secrets become references only.

Contract synthesis emits typed read and effect candidates with preconditions, input/output bounds, idempotency, timeout, terminal observation, failure mapping and state ownership. Generated contracts remain untrusted candidates until behavior parity and independent review pass.

### 11.3 Sandbox and behavior parity

The target runs in an isolated VM, container, rootfs or hardware simulator with no production credentials and bounded egress. The evaluator compares externally visible behavior, state transitions, performance, faults, restart and restore. Package scripts and dynamic plugins are treated as untrusted effects.

### 11.4 State migration and enrollment

Migration defines quiescence, source/destination schema, ordered steps, checksum/semantic verification, downtime, compensation and exact restore point. The host is enrolled only after owner consent, qualification and rollback evidence. Enrollment is target-specific and expiring.

### 11.5 Portable evolution package

What may propagate between authorized systems is a signed package containing:

```text
source and target compatibility manifest
typed adapter and contract digests
candidate code/model/policy/artifact
tests, fault results and resource measurements
state migration and rollback plan
independent evaluation and expiry
```

Credentials, consent, host enrollment and acceptance never propagate. Each target reruns compatibility and qualification. A source host cannot enroll peers, copy secrets, widen privileges or activate a candidate on another host. This is bounded transfer of verified capabilities, not autonomous infection.

## 12. Embodied implementation requirements

A physical or digital body requires concrete implementations of time/calibration, sensor admission, body schema, world model, attention, action gating, motor planning, local control, reflex safety, actuator gateway, terminal observation, metabolism/homeostasis, simulation twin, memory, consolidation, anomaly response and human override.

The common organ manifest names ports, effect class, data owner, resource envelope, health checks, fallback, calibration/body generation, rollback predecessor and retirement rule. Digital browser, Matrix, model and filesystem adapters use the same generation and intent/outcome semantics as physical sensors and actuators.

Physical activation additionally requires target-host timing, bounded force/speed/temperature, watchdog, independent emergency stop, sensor calibration, actuator saturation behavior, hardware-in-loop fault tests and sim-to-real residuals. Repository fixtures can validate protocols but cannot certify those measurements.

## 13. Parallel delivery and integration waves

The seven lanes execute in ordered waves without turning the program into a sequential monolith:

1. **W0 source and contracts:** exact source, guide/dossier digest, types, protocols and authority negatives.
2. **W1 durable foundation:** operation/evidence/cognitive stores, migrations, read ports, runtime hosts and fault recovery.
3. **W2 deterministic cognition:** objective compiler, deterministic NDU and C1 read-only vertical path.
4. **W3 shadow adaptation:** causal ledger, artifacts, independent outcomes, neuron and prompt-policy shadow candidates.
5. **W4 longitudinal transition:** future evaluation, retention, unlearning, new-generation reload and rollback.
6. **W5 governed evolution:** code/topology candidates, hidden evaluation, no-change baseline and bounded canary.
7. **W6 embodiment/assimilation:** one authorized service and one simulator/HIL target before broader federation.

Within a wave, teams use non-overlapping source roots and frozen public semantics. Any shared-contract change invalidates affected lane envelopes. Integration PRs own adapters and tests, not participant domain facts.

## 14. Documentation-depth gap closure

The companion closes these specification gaps:

- `IMPL-DOC-001`: runtime entrypoint and consumer callsite binding;
- `IMPL-DOC-002`: physical state, schema, migration and single-writer binding;
- `IMPL-DOC-003`: host, binary/artifact, configuration and body-generation identity;
- `IMPL-DOC-004`: terminal observer, revocation, fallback and reconciliation;
- `IMPL-DOC-005`: module-specific fault and recovery profile;
- `IMPL-DOC-006`: target-host performance measurement profile;
- `IMPL-DOC-007`: module-to-organ and multi-timescale mapping;
- `IMPL-DOC-008`: NDU subject, contribution and non-applicability mapping;
- `IMPL-DOC-009`: causal longitudinal loop and snapshot transition;
- `IMPL-DOC-010`: add/split/merge/rewire/retire execution semantics;
- `IMPL-DOC-011`: generic open-source assimilation and portable evolution package boundary;
- `IMPL-DOC-012`: all-module parallel wave and integration acceptance matrix.

Closure means the required record, algorithm, failure behavior, evidence and stop conditions are specified and machine-checked. It does not mean the record has been populated with runtime evidence.

## 15. External capability gates

The following gates remain external and open until real evidence exists:

- `RDY-EXT-001`: exact source modules compile and execute required tests;
- `RDY-EXT-002`: semantic review by a distinct reviewer;
- `RDY-EXT-003`: real model consumer and runtime/device identity;
- `RDY-EXT-004`: future-calendar longitudinal efficacy;
- `RDY-EXT-005`: empirical biomimicry through ablation and lesion evidence;
- `RDY-EXT-006`: target-host real-time and hardware-in-loop evidence;
- `RDY-EXT-007`: explicit owner consent for an external-system fixture;
- `RDY-EXT-008`: independent operator acceptance;
- `RDY-EXT-009`: separately governed canary, selection, promotion and release.

No document, generated status, branch name, fixture or self-issued receipt may mark these gates passed. A module receipt records their current disposition and exact external evidence when available.

## 16. Coding and activation checklist

Before coding, freeze source, guide, dossier, contract, protocol, data-authority, work-package, lane and qualification digests. Confirm owned roots, deterministic fallback, mandatory fixtures and zero authority delta.

Before composition, populate entrypoints, callers, host identity, state, schema/migration, writer fence, observer, revocation, fault and resource fields. Prove no duplicate durable writer and no hidden central RPC on a local safety path.

Before activation, pass exact-source and synthetic-merge checks, named product integration, target-host fault/performance suites, rollback rehearsal and every applicable independent decision. Keep unresolved external gates explicit. Selection, promotion and release remain separate transitions.
