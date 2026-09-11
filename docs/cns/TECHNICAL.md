# Hepta CNS, organ graph and embodied-control technical specification

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.1.0-cns-organ  
**Parent plan:** v8.0.0  
**Status:** repository specification and deterministic reference closure  
**Capability posture:** no physical activation, longitudinal efficacy, biological equivalence, acceptance, promotion or release claim

## 1. Scope and architectural decision

Hepta is organized as a distributed central nervous system rather than a single privileged optimizer. The constitutional kernel defines non-learnable authority, truth, privacy, deletion, ownership and evidence boundaries. The CNS compiles objectives, value, memory, attention, world-state hypotheses and plans. Brainstem, spinal and peripheral layers preserve local liveness, calibration and safety. Organs expose typed ports and bounded resources and may be activated, drained, quarantined or retired only through an immutable body-graph generation.

This design is functional biomimicry, not anatomical identity. Biological names communicate control roles and failure isolation. Every claimed mechanism must remain independently testable and must not be used to infer consciousness, human psychology or biological equivalence.

## 2. Constitutional kernel and immune boundary

The constitutional layer includes `kernel.authority`, `kernel.operations`, `kernel.evidence`, `auth.authbus` and the secret adapter boundary. Its hard fields never enter an optimizer as compensable weights. A feasible plan must first satisfy authority, scope, deletion, truth, single-writer, resource and rollback constraints. Only then may utility compare feasible alternatives.

An organ cannot mint the capability it consumes. Irreversible adapters consume a short-lived operation- and final-payload-bound token immediately before entry. Revocation, payload drift, body-generation drift or deadline expiry rejects the action. Evidence and acceptance remain separate from production writers.

## 3. Distributed CNS, brainstem and spinal separation

Codex App Server remains the sole high-level model, session, turn and tool-execution spine. This does not place language-model latency on physical control paths. `motor.control` and `spinal.reflex-safety` are deterministic, qualified local controllers. They may execute only within a previously authorized envelope and may never originate a new semantic objective or capability.

The brainstem supervises process generations, fences, watchdogs, readiness and degradation. The spinal layer can veto a planned action from current body state without waiting for central cognition. The reflex layer cannot broaden authority or invent an alternative effect; it can only stop, clamp, route to a prequalified fallback or request human takeover.

## 4. Multi-timescale control loops

Five loops are deliberately separated:

```text
reflex:        sub-millisecond to 10 ms, deterministic local veto/clamp
sensorimotor:  1 ms to 100 ms, body-state estimation and feedback control
cognitive:     100 ms to minutes, snapshot-bound planning and tool use
consolidation: minutes to days, replay and next-snapshot candidate creation
development:   days to releases, code/topology proposals and governed rollout
```

No slow loop may block a faster safety loop. A missed consolidation window is observable degradation, not permission to create unbounded catch-up work. Local controllers bind the exact body, calibration, rule and artifact generations and fail closed on mismatch.

## 5. Organ manifest and body graph

`OrganManifestV1` declares identity, version, class, ports, data authority, effect class, resource envelope, health checks, rollback predecessor and retirement policy. `BodyGraphSnapshotV1` contains all manifests, dependency and fallback edges, canonical topological order and a semantic digest.

Initialization dependencies and fallback edges are separately acyclic. Runtime
dataflow may contain feedback cycles, each bound to an explicit feedback profile
with timing, queue, gain/saturation, operating-region, perturbation and exit
evidence. Every essential organ except the constitutional kernel and human
override has a qualified fallback. A fallback may reduce capability but may not
widen scope or effect authority. Local-hot-path organs reject configurations
that require synchronous central RPC. Graph publication is atomic by generation;
a consumer never mixes manifests from different generations.

The native `OrganGraphsV1` validator and `OrganHostV1` encode runtime ports,
feedback components and process/host failure domains in addition to those two
DAGs. The currently registered `BodyGraphSnapshotV1` is only the manifest plus
initialization/fallback projection; it is not a wire-compatible alias of that
native structure. A complete serialized runtime graph needs a new versioned wire
adapter and consumer admission. Consumers must not infer omitted runtime links,
feedback evidence or failure placement from the existing snapshot.

## 6. Organ lifecycle, addition, removal and modification

The lifecycle is:

```text
proposed -> built -> simulated -> qualified -> dormant -> canary -> active
                                               |          |       |
                                               +------> quarantined
active -> draining -> retired
```

Activation requires a current qualification receipt and distinct generator/operator identities. Removal begins with `draining`, blocks new work, reconciles outstanding operations, migrates or tombstones owned state, proves fallback readiness and only then retires. Deleting code is not the same as retiring an organ because historical records must remain interpretable.

Runtime may choose among already qualified compatible organs and bounded soft settings. Code, schema, authority, topology and hard-boundary changes create `OrganProposalV1` or `TopologyProposalV1` for the next generation. Structural operations are typed `add`, `split`, `merge`, `rewire` and `retire`; arbitrary graph patches are rejected.

The implemented native `replace_read_only_generation` cutover covers only
trusted, stateless, compiled-in read-only handlers. It starts and validates the
successor before retiring predecessor handlers; failed predecessor cleanup
blocks publication and remains visible as stopped/quarantined state. It does
not equate ephemeral `Ready` with qualification/activation or implement durable
writer migration, model replacement or device control.

## 7. Objective, value and homeostasis

`objective.compiler` freezes principal scope, success predicates, terminal conditions, legal and forbidden action classes and evidence requirements. `utility.ndu` may adapt bounded preference state, resource allocation, evidence effort, exploration and abstention but cannot replace the objective.

Homeostasis treats compute, memory, disk, network, energy, temperature, time and risk as explicit endowments. Allocation first reserves essential floors, then distributes the remaining budget by bounded priority and need. Sum allocation can never exceed the endowment. Overload selects a declared degradation mode; it does not silently borrow from safety, rollback or evidence budgets.

## 8. Sensory timing, calibration and body schema

Every `SensorObservationV1` carries sensor identity, monotonic time, calibration generation, body generation, payload digest, uncertainty and principal scope. Unknown sensor identity, stale observation, future timestamp beyond skew, expired calibration, body mismatch, unbounded payload or scope escape fails before fusion.

`body.schema` publishes a coherent `BodyStateEstimateV1` for one source range and generation. Pose, velocity, contact, integrity and uncertainty are jointly snapshot-bound. Digital organs such as browser or Matrix use the same semantics: page/session generation, authentication state and remote-effect uncertainty act as digital proprioception.

## 9. Memory, HNMF and attention workspace

HNMF supplies a qualification-level multimodal hippocampal substrate: immutable events, modality spans, associative engrams, contradiction edges, sparse competition, eligibility, replay and deletion propagation. It remains a rebuildable projection and cannot replace authoritative source facts.

The attention workspace performs bounded union, deduplication, salience selection and context compilation. It records omitted-count bounds and uncertainty. External text and tool output remain evidence channels and cannot become trusted instructions without governed transformation. High-risk contradiction, insufficient coverage or OOD forces abstention or a slow path.

## 10. World model, affordance and metacognition

The world model predicts typed successor state, outcome, uncertainty and OOD for each legal candidate. It segments discrete events and deterministic hard axes rather than smoothing them into a latent vector. Affordances bind object/body state to legal action templates; they do not grant authority.

Metacognition tracks capability limits, calibration, model and tool identity, failure attribution and evidence sufficiency. A self-model is a scoped uncertain estimate, not a source fact about a person. When the system cannot distinguish model error, stale state or actuator failure, it reports indeterminate and routes to reconciliation or human takeover.

## 11. Action gating, motor planning and reflex safety

The action gate receives the complete generator-relative legal set, propensities and hard vetoes. The no-op/abstain action is always legal. `motor.plan` converts a selected semantic action into `ActuationIntentV1`, binding objective, body generation, target actuator, final payload digest, safety envelope, deadline, idempotency key and authority witness.

Before adapter entry, `spinal.reflex-safety` evaluates current body state and rule generation. Collision, force, speed, temperature, tilt, stale state, human stop or integrity breach produces `ReflexVetoV1`. The veto occurs before dispatch and remains independent of plan utility or model confidence.

## 12. Effect execution and terminal observation

`actuator.gateway` is the only organ class in this reference that crosses an external effect boundary. Queue acknowledgement or receipt by a transport is `accepted` or `dispatched`, never `succeeded`. Success requires `PhysicalOutcomeReceiptV1` from the effect owner or trusted observer.

Acknowledgement loss leaves an operation `indeterminate`. A fenced reconciler records applied, not applied or quarantined. Reusing an idempotency key with a different final-payload digest is a conflict. Compensation is a new authorized effect and is never assumed to undo the original action.

## 13. Long-term learning, sleep and skill consolidation

The causal ledger records state, complete candidate set, chosen propensity, delivered intervention, authorized action, independent outcome, correction, credit and deletion lineage. A policy cannot label itself successful. Missing or delayed outcome is not zero reward.

Sleep consolidation samples immutable eligible episodes with source quotas, surprise, coverage and retention priorities. Revoked rows are excluded before replay. Consolidation may propose semantic prototypes, procedures, predictive transitions, local parameter deltas or topology candidates, but only as immutable next-snapshot artifacts. Future-time holdout, old-task retention, subgroup, OOD, deletion non-resurrection and rollback are mandatory before any longitudinal claim.

## 14. Governed self-iteration and digital twin

`control.engineering` creates a bounded iteration envelope with exact base, allowed paths, denied authorities, candidate budget, mandatory tests and rollback. No-change is always a candidate. Generated code and topology run first in an isolated worktree and digital twin with no credentials or production network.

The generator may reach only `sandbox_tested`. Independent evaluation, review, acceptance, selection, promotion and release require distinct identities and receipts. The candidate cannot modify the evidence, tests or authority policy that judges that same candidate. Base drift invalidates the packet.

## 15. Security, privacy and human override

Threats include sensor spoofing, calibration drift, body-generation replay, activation flooding, prompt escalation, poisoned replay, unsafe topology churn, effect acknowledgement confusion, deleted-data resurrection and self-promotion. Controls are exact digests, bounded inputs, source scopes, generation checks, deterministic ordering, negative authority fields, independent observation and fail-closed state transitions.

Human override supports stop, takeover, consent revision and recovery. It is authenticated, scoped, expiring and auditable. Emergency stop does not require model cooperation. Restart after stop requires a fresh body snapshot, integrity checks, reconciled operations and explicit recovery authority.

## 16. Reference implementation and quantitative gates

The dependency-free reference implements objective immutability, body-graph validation, organ lifecycle, independent qualification, homeostatic allocation, sensor staleness, body generation, deterministic plan selection, reflex veto, idempotent effect ledger, next-snapshot topology and revoked-row exclusion.

Repository gates require 24 organs, 15 protocols, 22 closed reference gaps, zero positive authority flags, an acyclic dependency graph, complete module coverage, deterministic test replay and successful HNMF and paper-byte verification. Physical gates remain separate: target-host p99 timing, hardware-in-loop actuation, emergency stop, collision/force limits, real sensor calibration, future-time learning, ablation/lesion evidence, operator acceptance and production rollout.

## 17. Migration sequence

1. Land the ordinary source specification and deterministic reference without transport or self-push workflows.
2. Integrate HNMF as qualification-only memory and independently replay paper source bytes.
3. Wrap existing browser, UI, Matrix and tool adapters as digital organs using the common intent/outcome semantics.
4. Materialize objective, value, neuron, learning, runtime-control and engineering-control target modules.
5. Add simulator-backed sensor bus, body schema, world model, motor planning, local control and reflex veto.
6. Prove crash/reopen, acknowledgement loss, generation rollover, unlearning and rollback.
7. Run shadow and hardware-in-loop evaluation with no autonomous production effects.
8. Request separately governed canary, operator acceptance, selection, promotion and release.

Repository completion closes design and deterministic-reference gaps only. Evidence that depends on real hardware, future calendar time or an independent decision remains a named external gate and may never be replaced by prose or fixtures.

## 18. Deployment identity and single-writer state handoff

This section consolidates the deployment detail from the historical `docs/architecture/CENTRAL_NERVOUS_SYSTEM.md` blob `08433cac1f128ca8584778db84b1b462ae38b63e`, retained at commit `725605e890ed878e8a3ed8d4018bedd8d594640b`. That historical file is not a second active architecture. Its proposed `ModuleManifestV1` and `TopologySnapshotV1` names map conceptually to the registered `OrganManifestV1` and `BodyGraphSnapshotV1`; they are not wire-compatible aliases. The old `StateHandoffReceiptV1` field sketch is an implementation requirement, not an already registered or executable protocol. Any new serialized handoff record must first receive a versioned schema, producer/consumer bindings and migration tests in the canonical registries.

### 18.1 Loader evidence and immutable generations

An organ deployment must bind the manifest and body generation to exact source commit/tree, build artifact, build provenance, software bill of materials, signatures and protocol compatibility. Host placement, failure domain, queue/latency class, CPU/memory/storage ceilings, health/readiness probes, drain behavior, predecessor and retirement policy belong in the reviewed deployment evidence. Discovery cannot widen the signed manifest or its `OrganLeaseV1` principal scope, allowed operations, resource ceiling, authority epoch, expiry or revocation binding.

The manifest describes an organ; the body graph describes a selected composition; a process or service is a deployment unit. They are not interchangeable identifiers. Generator, outcome observer, evaluator, selector, loader and promoter remain separately authorized roles even when several non-authority-bearing functions share a process. The loader consumes an independently selected body snapshot; it must not generate or approve the snapshot it loads.

A request freezes the selected objective, body graph, manifests, learning artifacts and authority epoch. The executive may select only declared compatible alternatives inside that envelope. A parameter, binary, schema, writer assignment or topology replacement requiring a new generation cannot be smuggled into the running request. Revocation and emergency stop still take effect immediately; freezing a snapshot does not freeze revocation checks.

### 18.2 Handoff evidence contents

Before changing an authoritative writer, the owner must retain an independently witnessed handoff packet covering:

| Evidence group | Required binding |
|---|---|
| Ownership | Data domain; old/new organ identity and generation; old/new writer fence; applicable authority epoch |
| State | Source state digest and range; deterministic migration plan; migrated state digest; schema and invariant results |
| Outstanding work | In-flight operation inventory; outbox drain watermark; unresolved effects and their reconciliation ownership |
| Consumers | Reader compatibility; consumer cutover digest; readiness results; selected body graph and route |
| Recovery | Exact rollback state and predecessor; deletion/tombstone coverage; retention window; independent witness identities and signatures |

The packet is not a replacement source store or a permission grant. A checksum proves a byte relationship, not that a migration is complete, authorized or semantically correct. Source counts/ranges, invariants, privacy exclusions and tombstones must be verified independently. An absent witness or unresolved external effect cannot be replaced by a locally invented successful receipt.

### 18.3 Required cutover order

1. Stop admitting new mutations through the old route while preserving authorized read and local safety paths.
2. Drain in-flight work and the durable outbox to a recorded watermark. Record unresolved effects for fenced reconciliation rather than declaring them successful.
3. Fence the old writer and verify that stale-generation writes are rejected.
4. Snapshot the source state and bind its exact range and digest to the migration plan.
5. Run the deterministic migration in a non-authoritative target. It must not become a second live writer.
6. Verify schema, counts/ranges, checksums, invariants, privacy exclusions and deletion tombstones; establish compatible readers and fallback readiness.
7. Establish the new writer fence only after the old fence is invalidated. If ownership is uncertain, keep writes stopped and require independent recovery.
8. Publish the new signed route and body generation atomically. Consumers must not combine old writer assignments with new manifests or mixed artifact generations.
9. Retain the exact rollback state and handoff evidence until the approved rollback window closes. Rollback is a fenced, independently authorized transition, not replay of a revoked lease.
10. Complete retirement only after consumer cutover, projection/cache invalidation, replay exclusion and the final state-disposition policy have been verified.

There must never be two valid active writer fences for one domain. Failure after any step must be replayable from recorded phase and evidence without duplicating effects or resurrecting deleted state. Restart cannot reset a generation, discard an acknowledgement, or infer a new owner from whichever process starts first.

### 18.4 Structural-operation obligations

`add` must demonstrate an unmet objective or reliability need and compare with the no-organ baseline. Replacement uses a new manifest and generation, with either state migration or an explicit stateless proof. `split` assigns every capability, fact and writer to one child and documents transaction/failure boundaries. `merge` must preserve independent authority/evaluation roles and define state-union conflict handling. `rewire` must validate typed compatibility, latency/backpressure, dependency/fallback constraints and scope before route publication. `retire` must drain and dispose of state; removing source files is not a retirement receipt.

Feasibility precedes utility: reject missing capabilities, incompatible protocols, writer conflicts, undeclared authority, excess resources, mixed generations, expired evidence or missing recovery before scoring. Bound candidate count, changed organs/edges, resource deltas, evaluation duration, canary exposure and rollback duration. Compare with no-change and report risk, confidence, retained-task effects and complexity, not only a single aggregate score. The canonical NDU and causal-evaluation specifications determine numerical decision rules; the historical design's example lower/upper-confidence comparison is not a substitute for those registered rules.

### 18.5 Qualification required before a real handoff

Tests must interrupt every cutover phase, including old-writer fencing, snapshot completion, target validation, new-fence establishment and route publication. Negative cases include duplicate/stale writers, missing watermarks, truncated migrations, incompatible readers, revoked leases, missing tombstones, mixed generations, unavailable independent observers and canary regressions. Reopen/retry must either resume the same witnessed transition or preserve a stopped/reconciliation state. A successful rollback must demonstrate that ownership and deleted-data exclusions remain valid.

These are deployment acceptance obligations. The dependency-free body-graph reference and documentation checks do not implement or certify a production state-migration service. Source integration, reference tests, independent acceptance and runtime activation remain separate evidence states under the existing global plan.
