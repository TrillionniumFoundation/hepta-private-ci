# Embodied and digital-organ runtime execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Parent architecture:** `docs/cns/CNS_ARCHITECTURE.json` and `docs/cns/TECHNICAL.md`

## 1. Scope and authority boundary

This specification makes the CNS organ model implementable across physical and digital bodies. It does not activate hardware or grant physical-effect authority. High-level cognition remains on the Codex spine; reflex and motor loops are bounded deterministic controllers operating only inside a pre-authorized envelope.

Human emergency stop, constitutional constraints and local reflex safety dominate learned planning. No local sensorimotor loop depends on synchronous central RPC.

## 2. Time domains and control-loop classes

Every loop binds `RealTimeLoopProfileV1` and one monotonic clock domain:

| Loop | Target scale | Allowed behavior |
|---|---:|---|
| reflex | sub-millisecond to 10 ms | deterministic veto, clamp or stop |
| sensorimotor | 1 ms to 100 ms | state estimation and local feedback |
| cognitive | 100 ms to minutes | snapshot-bound planning and tool use |
| consolidation | minutes to days | replay and next-snapshot proposals |
| development | releases | code/topology candidates and rollout |

Profiles record period, deadline, jitter, execution budget, priority, watchdog and fallback controller. Deadline miss never broadens authority; repeated misses degrade or stop the affected organ.

## 3. Sensor identity, calibration and fusion

Each sensor or digital adapter has `SensorCalibrationManifestV1` with exact hardware/adapter, clock, generation, operating range, uncertainty and validity interval. Observations bind sensor, calibration, body generation, monotonic time, payload digest, scope and uncertainty.

Unknown identity, expired calibration, future timestamp beyond skew, stale sample, unbounded payload or body mismatch fails before fusion. Fusion uses a coherent source interval and records omitted sensors, disagreement and uncertainty. Contradiction on a safety-critical axis forces abstention or reflex stop.

Digital equivalents are explicit: browser session/page generation, Matrix authentication/room generation, provider model/runtime generation and filesystem mount generation act as proprioceptive state.

## 4. Body generation and proprioception

`body.schema` publishes one immutable body-state generation containing pose or digital topology, velocity/change rate, contacts/connections, integrity, active organ manifests and uncertainty. Consumers cannot mix body generations. Structural change creates a new signed body graph and drains the predecessor.

Integrity includes sensor availability, actuator readiness, calibration freshness, service identity and outstanding indeterminate operations. An unknown critical component marks the body degraded or unsafe.

## 5. Motor planning, reflex and actuation

Motor planning converts one legal semantic action into an intent binding objective, body generation, actuator, final payload digest, safety envelope, deadline, idempotency key and authority witness. Immediately before dispatch, reflex safety evaluates current body state and rule generation.

Reflex output is limited to allow, veto, clamp, route to a prequalified fallback or request human takeover. It cannot invent a new objective or effect. The actuator adapter consumes final-payload-bound authority once. Queue acceptance is not success; `ActuatorReconciliationReceiptV1` records observed terminal effect or an indeterminate state resolved by a fenced reconciler.

## 6. Emergency stop and recovery

Emergency stop is independent of model cooperation and emits `EmergencyStopReceiptV1`. It fences new intents, commands local safe state, records acknowledgement per actuator and leaves unknown effects indeterminate. Restart requires a fresh body snapshot, integrity and calibration checks, reconciled operations, fallback readiness and explicit recovery authority.

Physical stop circuitry and software stop paths are independently tested. A model or optimizer cannot mask, delay or downgrade a stop.

## 7. Hardware-in-loop and sim-to-real

The qualification ladder is deterministic simulation, randomized digital twin, software-in-loop, hardware-in-loop with no autonomous production effect, bounded supervised canary and separately governed activation. The simulator digest, hardware identity, firmware, calibration, host timing and environment profile are evidence inputs.

Sim-to-real reports dynamics residual, latency/jitter difference, sensor bias, actuator saturation, contact error, thermal/energy difference and unmodeled event rate. A gap above profile keeps the candidate in simulation or shadow.

## 8. Failure taxonomy and degradation

Failures include stale calibration, clock drift, dropped or duplicated observations, body-generation mismatch, sensor disagreement, actuator saturation, stuck command, acknowledgement loss, network partition, watchdog expiry, emergency-stop failure, thermal/resource breach and simulator mismatch.

Declared degradation modes reduce capability: lower speed, read-only mode, local fallback, organ quarantine or full stop. No degradation can widen action scope, bypass evidence or borrow from emergency, rollback or safety budgets.

## 9. Performance and safety envelope

Every target host publishes p50/p95/p99 execution, jitter, missed deadlines, CPU, memory, allocation, queue age, energy/thermal, sensor age and reconciliation latency. Local loops preallocate bounded memory, avoid global locks and use deterministic scheduling where required.

Physical effect packages require independent safety analysis, force/speed/temperature limits, watchdog proof, emergency-stop latency and fault injection. Repository fixtures cannot self-certify these external gates.

## 10. Golden fixtures and tests

- stale sensor and expired calibration reject before fusion;
- mixed body generations reject before planning;
- a high-utility intent with collision risk is vetoed;
- duplicate idempotency key with changed payload conflicts;
- acknowledgement loss remains indeterminate until observer reconciliation;
- emergency stop during dispatch fences new work and requires explicit recovery;
- local control continues safe fallback during central outage;
- sim-to-real residual above threshold blocks canary.

Property tests enforce acyclic body graph, qualified fallback for essential organs, no central RPC on local loops, reflex dominance, terminal observation, bounded queues and exact generation rollover.

## 11. Implementation sequence

Implement timing and calibration types, sensor bus, coherent body schema, simulator-backed world state, motor intent, local controller, reflex veto, actuator outcome ledger, emergency stop, fault matrix, software-in-loop, hardware-in-loop and only then supervised canary. Digital browser/Matrix/tool organs provide the first safe implementations of the same semantics.

## 12. Coding-entry checklist

Coding may start when the four readiness protocols and CNS protocols compile, every loop has a profile and fallback, clock and generation rules are frozen, the actuator owner and outcome observer are distinct where required, emergency stop is independent, simulator/fault fixtures exist, and all real hardware claims remain external gates.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `SensorCalibrationManifestV1`
- `RealTimeLoopProfileV1`
- `EmergencyStopReceiptV1`
- `ActuatorReconciliationReceiptV1`

Closed documentation gaps:

- `RDY-GAP-EMB-001`
- `RDY-GAP-EMB-002`
- `RDY-GAP-EMB-003`
- `RDY-GAP-EMB-004`
- `RDY-GAP-EMB-005`
- `RDY-GAP-EMB-006`

Bound work packages:

- `BROWSER-WEB-C1`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `EMB-0-EMBODIED-CONTRACTS`
- `EMB-1-SENSOR-BUS-BODY-SCHEMA`
- `EMB-2-REFLEX-MOTOR-ACTUATION`
- `EMB-3-HIL-SIM-TO-REAL-QUALIFICATION`
- `INFER-V4-T4`
- `INFER-V4-T5`
- `MATRIX-1-CHANNEL-BOUNDARY`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`
- `NEU-1-LOCAL-MODEL-BAKEOFF`
- `P0.7A-RUNTIME-BOOTSTRAP`
- `P0.7B-B0-VERIFIED-USE`
- `P0.7B-B2-TOOL-NET-FS`
- `P0.7B-B3-BOUNDARIES`
- `P0.7B-B4-CALLSITE-PROOF`
- `P0.7D-FAULT-MATRIX`
- `P0.8A-AST-RATCHET`
- `P0.8B-READINESS`
- `P0.8C-RESOURCE-BUDGETS`
- `P0.8D-VERTICAL-SLICE`
- `RCP-1-RUNTIME-CONTROL-PLANE`
- `TASKFLOW-1-EXECUTION-BOUNDARY`
