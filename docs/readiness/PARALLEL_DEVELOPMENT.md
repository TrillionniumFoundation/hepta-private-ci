# Parallel module development and integration specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Coverage:** all 40 registered modules  
**Purpose:** start parallel implementation without contract drift, path collision, undocumented runtime assumptions or false capability claims

## 1. Scope and authority boundary

This specification assigns every registered module to one primary implementation lane and defines cross-lane checkpoints. It does not grant broad repository ownership, bypass work-package predecessors or authorize merge. Each team receives a bounded `ParallelLaneEnvelopeV1` tied to an exact source receipt and existing `WORK_PACKAGES.json` paths.

The execution-oriented specification is `qualification/module-execution-dossiers/TECHNICAL.md`; its exact forty-module projection is `qualification/module-execution-dossiers/MODULE_DOSSIERS.json`. These files are qualification companions, not a second global plan or a replacement for module, contract, data-authority, delivery, readiness or CNS registries. Documentation depth cannot manufacture a host, process, physical store, real model, independent decision or production activation.

## 2. Frozen inputs and lane envelopes

Before coding, every lane freezes:

```text
CanonicalSourceReceiptV1
MODULES, MODULE_DOCS and SOURCE_BINDINGS digests
CONTRACTS, PROTOCOL_SCHEMAS and DATA_AUTHORITY digests
WORK_PACKAGES, PATH_OWNERSHIP and the three DAG digests
readiness, algorithm, CNS, HNMF and execution-dossier digests
qualification profile, mandatory checks, resource ceiling and expiry
```

A semantic change creates base drift and requires a new envelope. Mock implementations are permitted only behind exact typed contracts and cannot become alternative durable owners. `none_by_design` is valid only with evidence proving that the state or boundary does not exist.

## 3. Primary implementation lanes

| Lane | Exact modules | First exit condition |
|---|---|---|
| `LANE-A-FOUNDATION` | `platform.types`, `platform.wire`, `kernel.authority`, `kernel.operations`, `kernel.evidence`, `auth.authbus`, `secrets.heptabao` | shared contracts, negative authority tests and durable fault semantics compile |
| `LANE-B-RUNTIME` | `runtime.supervisor`, `runtime.fleet`, `runtime.agentd`, `runtime.codex`, `inference.control`, `inference.worker`, `automation.taskflow`, `channel.matrix`, `browser.servo`, `ui.control`, `ui.native` | named hosts, typed effect boundaries, terminal observers and deterministic fallbacks exist |
| `LANE-C-MEMORY` | `cognitive.types`, `cognitive.store`, `cognitive.read`, `memory.retrieval`, `memory.federation`, `knowledge.graph`, `compact.engine`, `prompt.registry`, `context.compiler` | coherent snapshots, single writers, migrations, deletion and restore fixtures pass |
| `LANE-D-OBJECTIVE-VALUE` | `objective.compiler`, `utility.ndu`, `control.runtime` | immutable objective, deterministic feasibility/Pareto/NDU and bounded allocation pass |
| `LANE-E-LEARNING` | `learning.ledger`, `learning.operator`, `learning.eval`, `learning.artifacts` | immutable decision/outcome/dataset/evaluation/artifact lineage works across reopen |
| `LANE-F-ADAPTIVE-POLICY` | `neuron.runtime`, `intuition.policy`, `prompt.optimizer`, `learning.plasticity`, `intelligence.control` | shadow-only adaptive path, ablations and no-current-mutation proof pass |
| `LANE-G-ENGINEERING` | `control.engineering` | bounded envelopes, isolated candidates, independent evaluator adapter and rollback work |

A module has one primary lane. Integration tracks may grant explicit adapter/test co-ownership without transferring durable facts. Lane A freezes public semantics first; other lanes may implement private internals in parallel.

## 4. Cross-lane integration tracks

`TRACK-1-READ-ONLY-VERTICAL` composes runtime, memory and objective/value into request → retrieval → read-only report with zero external effect. `TRACK-2-ADAPTIVE-SHADOW` adds complete candidates, propensities, independent outcomes and next-snapshot artifacts. `TRACK-3-EMBODIMENT-AND-ASSIMILATION` wraps digital organs and one explicitly authorized external service in simulation or sandbox before canary.

Integration PRs own adapters and integration tests only. Domain changes return to the owning lane or use a registered co-owner package. An integration façade cannot become an undeclared writer.

## 5. Integration checkpoints

```text
I0 SOURCE: exact source, branch purpose, registry, guide and dossier digests
I1 TYPES: canonical types/protocols compile, round-trip and reject invalid input
I2 STORES: physical schema, single writers, migration, crash/reopen and deletion fixtures
I3 VERTICAL: deterministic read-only path through named host entrypoints and callers
I4 SHADOW: complete candidate logging, propensities, independent outcomes and artifacts
I5 LONGITUDINAL: future windows, retention, unlearning, new-generation load and rollback
I6 ITERATION: bounded candidate generation, no-change comparison and independent review
I7 EMBODIED/ASSIMILATION: target simulator/HIL or external-service qualification
```

A later checkpoint cannot waive an earlier failure. `I2` requires real durable formats rather than in-memory semantics. `I3` requires named product callers rather than standalone library tests. `I5` requires a new process generation to load an evaluated artifact rather than merely persisting candidate bytes.

## 6. Branch, PR and merge discipline

One PR carries one bounded work package or checkpoint. It records exact source/tree, envelope, changed paths, contracts, authority delta, tests, resources, rollback and unresolved external gates. Source-head and deterministic synthetic-merge checks both pass. Overlapping paths require DAG order or a registered lease. Generated files pass clean-worktree parity. Branch names, labels, comments and queued workflows are observations, not source selection or acceptance.

## 7. Stop conditions and escalation

All lanes stop on base drift, authority delta, cross-owner write, contract ambiguity, unknown schema, unbounded queue/retry/resource, mandatory-test failure, missing rollback, evaluator collision, claim/evidence mismatch, deletion resurrection, empty runtime binding, unnamed terminal observer or fallback authority widening. Infrastructure failures may be retried only under package policy; semantic failures require a new candidate.

## 8. Required evidence per lane

Every lane produces exact source inventory, static verification, focused/package tests, all-target build, strict lint, clean tracked state, fault evidence, target-host resource measurements and exact-head/merge-candidate receipts. Adapters add revoked grant, payload drift, timeout and indeterminate-outcome tests. Learning modules add support, future-window, retention and unlearning evidence only when making those claims.

Every module handoff materializes:

```text
sourceReceipt
moduleGuideDigest
declaredSourceRoots
entrypoints
consumerCallsites
hostRuntimeIdentity
binaryOrArtifactDigest
configurationAndBodyGeneration
ownedPhysicalState
schemaAndMigration
singleWriterFence
terminalObserver
revocationSource
faultResults
resourceMeasurements
fallback
rollbackPredecessor
externalGateDisposition
```

Fault profiles are `FP-CONTRACT`, `FP-DURABLE-OWNER`, `FP-RUNTIME`, `FP-EFFECT-BOUNDARY`, `FP-LEARNING-OFFLINE`, `FP-UI` and `FP-ENGINEERING-ASSIMILATION`. Measurement profiles are `PERF-LIBRARY`, `PERF-DURABLE`, `PERF-HOT-LOCAL`, `PERF-CONTROL`, `PERF-ADAPTER`, `PERF-OFFLINE`, `PERF-UI` and `PERF-ENGINEERING`. Detailed cases are normative in the dossier technical specification; exact module assignments are machine-readable in `MODULE_DOSSIERS.json`.

## 9. Coding-entry checklist

Parallel coding begins only when all 40 module guides contain the V8.2 overlay, each module appears exactly once in the readiness lane registry and execution dossier, shared protocol generation is frozen, path conflicts are ordered, deterministic fallbacks exist and external gates remain unclaimed. Coding entry is not activation entry: source-complete modules remain dormant until named callers, hosts, stores, observers, target measurements, rollback and independent decisions are bound.

## 10. Module execution profile matrix

| Module | Runtime/state | Fault | Performance | NDU participation |
|---|---|---|---|---|
| `platform.types` | library/stateless | `FP-CONTRACT` | `PERF-LIBRARY` | bounded context, not an NDU subject |
| `platform.wire` | library/stateless | `FP-CONTRACT` | `PERF-LIBRARY` | typed transport, not an NDU subject |
| `kernel.authority` | security/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | hard feasibility outside utility |
| `kernel.operations` | durability/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | non-NDU operational evidence |
| `kernel.evidence` | evidence/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | claim verifier outside utility |
| `runtime.supervisor` | daemon/runtime | `FP-RUNTIME` | `PERF-HOT-LOCAL` | bounded resource/liveness context |
| `runtime.fleet` | distributed/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | resource endowment contributor |
| `runtime.agentd` | daemon/runtime | `FP-RUNTIME` | `PERF-CONTROL` | composition context only |
| `runtime.codex` | execution/authoritative | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | action execution, not value owner |
| `auth.authbus` | security/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | hard authorization context |
| `secrets.heptabao` | external adapter | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | non-NDU secret boundary |
| `inference.control` | control/runtime | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | model resource/cost contribution |
| `inference.worker` | worker/runtime | `FP-RUNTIME` | `PERF-CONTROL` | model signal provider |
| `objective.compiler` | library/stateless | `FP-CONTRACT` | `PERF-LIBRARY` | immutable objective owner |
| `utility.ndu` | control/projection | `FP-RUNTIME` | `PERF-CONTROL` | system/domain/agent/episode P/U owner |
| `neuron.runtime` | in-process/checkpoint | `FP-RUNTIME` | `PERF-HOT-LOCAL` | temporal signal, not NDU subject |
| `intuition.policy` | in-process/read-only policy | `FP-RUNTIME` | `PERF-HOT-LOCAL` | episode policy consumer |
| `prompt.registry` | registry/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | bounded intervention facts |
| `prompt.optimizer` | offline/read-only | `FP-LEARNING-OFFLINE` | `PERF-OFFLINE` | state-dependent utility consumer |
| `context.compiler` | library/stateless | `FP-CONTRACT` | `PERF-LIBRARY` | bounded evidence context |
| `intelligence.control` | in-process/composition | `FP-RUNTIME` | `PERF-CONTROL` | composition without value ownership |
| `cognitive.types` | library/stateless | `FP-CONTRACT` | `PERF-LIBRARY` | bounded memory/body context |
| `cognitive.store` | durability/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | facts, not utility state |
| `cognitive.read` | library/read snapshot | `FP-CONTRACT` | `PERF-LIBRARY` | evidence input provider |
| `memory.retrieval` | local/read projection | `FP-CONTRACT` | `PERF-LIBRARY` | candidate/support contributor |
| `memory.federation` | distributed/read projection | `FP-CONTRACT` | `PERF-LIBRARY` | bounded remote evidence |
| `knowledge.graph` | projection/rebuildable | `FP-CONTRACT` | `PERF-LIBRARY` | world/evidence relation context |
| `compact.engine` | offline/rebuildable | `FP-LEARNING-OFFLINE` | `PERF-OFFLINE` | consolidation context |
| `learning.ledger` | durability/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | decision/outcome/propensity evidence |
| `learning.operator` | offline/artifact candidate | `FP-LEARNING-OFFLINE` | `PERF-OFFLINE` | continuation-value candidate |
| `learning.eval` | offline/evaluation owner | `FP-LEARNING-OFFLINE` | `PERF-OFFLINE` | independent efficacy/stability evaluator |
| `learning.artifacts` | registry/authoritative | `FP-DURABLE-OWNER` | `PERF-DURABLE` | immutable NDU/policy artifacts |
| `learning.plasticity` | offline/proposal | `FP-LEARNING-OFFLINE` | `PERF-OFFLINE` | next-snapshot proposal only |
| `automation.taskflow` | execution/authoritative | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | action cost/outcome contributor |
| `channel.matrix` | external adapter | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | digital sensor/actuator context |
| `browser.servo` | external adapter | `FP-EFFECT-BOUNDARY` | `PERF-ADAPTER` | digital sensor/actuator context |
| `ui.control` | UI/session | `FP-UI` | `PERF-UI` | human preference/override input only |
| `ui.native` | UI/session | `FP-UI` | `PERF-UI` | human preference/override input only |
| `control.runtime` | control/projection | `FP-RUNTIME` | `PERF-HOT-LOCAL` | boundary conditions/resource allocation |
| `control.engineering` | engineering/authoritative | `FP-ENGINEERING-ASSIMILATION` | `PERF-ENGINEERING` | work planning, not an NDU subject |

CNS organ roles and declared source roots are derived at verification time from canonical registries rather than duplicated into this Markdown table. A module may serve multiple organs but retains one primary lane and one authoritative writer boundary.

## 11. Integration wave schedule

| Wave | Parallel work | Merge gate | Capability ceiling |
|---|---|---|---|
| W0 | exact source, dossier, type/protocol freeze | I0/I1 | documentation and contract compilation |
| W1 | durable stores, migrations, read ports, runtime hosts | I2 | source implementation and fixtures |
| W2 | objective, deterministic NDU, C1 read-only path | I3 | deterministic read-only behavior |
| W3 | causal ledger, artifacts, outcomes, shadow adaptive policy | I4 | candidate generation only |
| W4 | future evaluation, retention, unlearning, reload/rollback | I5 | bounded longitudinal claim when evidence exists |
| W5 | code/topology candidates and canary abort | I6 | governed self-iteration candidate |
| W6 | authorized service and simulator/HIL target | I7 | target-specific qualified organ |

## 12. Documentation-depth gap closure

The following execution ambiguities are closed at specification level: `IMPL-DOC-001`, `IMPL-DOC-002`, `IMPL-DOC-003`, `IMPL-DOC-004`, `IMPL-DOC-005`, `IMPL-DOC-006`, `IMPL-DOC-007`, `IMPL-DOC-008`, `IMPL-DOC-009`, `IMPL-DOC-010`, `IMPL-DOC-011` and `IMPL-DOC-012`. They cover entrypoints/callers; physical state/migrations/single writers; host and generation identity; terminal observation/revocation/reconciliation; fault and performance profiles; CNS/NDU mapping; longitudinal snapshot transition; structural organ evolution; generic open-source assimilation; and all-module integration waves. Execution evidence remains in receipts, not prose.

## 13. External gates preserved

`RDY-EXT-001` through `RDY-EXT-009` remain external for source compilation, independent semantic review, real-model/runtime identity, future-calendar efficacy, empirical biomimicry, target hardware, owner consent, operator acceptance and production canary/selection/promotion/release. No dossier, fixture, branch, workflow or generated status may convert them to passed.

## Appendix A. Closed gap and protocol mapping

This appendix records repository specification closure only. It does not grant runtime, model, provider, external-effect, operator, promotion or release authority.

### Protocol bindings

- `ParallelLaneEnvelopeV1`
- `IntegrationCheckpointV1`
- `CanonicalSourceReceiptV1`

### Closed specification gaps

- `RDY-GAP-PAR-001`
- `RDY-GAP-PAR-002`
- `RDY-GAP-PAR-003`
- `RDY-GAP-PAR-004`
