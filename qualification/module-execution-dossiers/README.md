# Hepta module execution dossiers

This qualification companion is subordinate to `docs/DEVELOPMENT.md` (plan 8.0.0) and the V8.2 readiness layer. It is not a second global plan. Canonical module ownership, source roots, contracts, data authority, work packages, the three DAGs, readiness, CNS and HNMF registries remain authoritative.

## Read order

1. [TECHNICAL.md](TECHNICAL.md): shared execution and evolution obligations.
2. [MODULE_DOSSIERS.json](MODULE_DOSSIERS.json): forty-module classification and eighteen required receipt fields.
3. [EXECUTION_SEMANTICS.md](EXECUTION_SEMANTICS.md): objective, NDU, sequential evaluation, numeric compatibility, handoff, organ and assimilation semantics.
4. [DETAILS.json](DETAILS.json): exact forty-module design hashes, lanes, roots and work packages.
5. The module-specific detail linked below: proposed operations, logical records, transaction order, algorithms, capacity and four named native acceptance-test designs.
6. [STATE_HANDOFF.schema.json](STATE_HANDOFF.schema.json): bounded same-owner cardinality-preserving handoff evidence schema and phase oracle.
7. [DETAIL_GAPS.json](DETAIL_GAPS.json): bounded audit dispositions and preserved external gates.
8. [STATUS.md](STATUS.md): generated classification/depth projection, not an independent acceptance record.
9. [IMPLEMENTATION_CONTRACTS.md](IMPLEMENTATION_CONTRACTS.md): coding-entry, native binding, final-gate ordering, cross-owner composition and seven-lane implementation rules.
10. [IMPLEMENTATION_PROFILES.json](IMPLEMENTATION_PROFILES.json): concrete API, state/encoding, linearization/recovery, algorithm and acceptance contracts for all forty modules.
11. [NATIVE_BINDINGS.json](NATIVE_BINDINGS.json): five exact inspected source exports, explicitly distinguished from proposed implementations and real deployment evidence.
12. [PERSISTENCE.md](PERSISTENCE.md) and [COGNITIVE_STORE.sql](COGNITIVE_STORE.sql): proposed cognitive durable adapter, actual format boundaries, commit/acknowledgement, deletion, rotation, backup and recovery.
13. [ORGAN_EVOLUTION.md](ORGAN_EVOLUTION.md): separate graph types, typed extension admission, composite migration, single-writer barriers and rollback after successor writes.
14. [C1_EXECUTION.md](C1_EXECUTION.md): real-host vertical composition, independent outcomes, durable learning, new-process loading and exact rollback.
15. [LEARNING_EXPERIMENT.md](LEARNING_EXPERIMENT.md): preregistered estimands, real future windows, support, cluster/fold separation, ablations and unlearning.
16. [EMBODIMENT.md](EMBODIMENT.md): a concrete simulated cart/controller, clocks, scheduling analysis, watchdog and physical-evidence boundaries.
17. [ASSIMILATION.md](ASSIMILATION.md): one enrolled rootless Debian service, typed operations, provenance, reversible adaptation and destination-specific qualification.
18. [IMPLEMENTATION_COMPLETION.json](IMPLEMENTATION_COMPLETION.json): sixteen enumerated implementation-design dispositions and remaining evidence; overall closure remains false.

The corrected authoritative NDU mathematics is in [NDU_FBSDE_SPEC.md](../../docs/learning/NDU_FBSDE_SPEC.md), with its exact Git blob in `ALGORITHM_SPECS.json`. General covariance regression solves `Z Sigma = B`; division by time alone requires the declared standard covariance. A companion cannot silently change a serialized production protocol or reinterpret old artifacts.

## Forty implementation designs

| Module | Primary lane | Detail |
|---|---|---|
| `platform.types` | `LANE-A-FOUNDATION` | [platform.types](detail/platform.types.md) |
| `platform.wire` | `LANE-A-FOUNDATION` | [platform.wire](detail/platform.wire.md) |
| `kernel.authority` | `LANE-A-FOUNDATION` | [kernel.authority](detail/kernel.authority.md) |
| `kernel.operations` | `LANE-A-FOUNDATION` | [kernel.operations](detail/kernel.operations.md) |
| `kernel.evidence` | `LANE-A-FOUNDATION` | [kernel.evidence](detail/kernel.evidence.md) |
| `auth.authbus` | `LANE-A-FOUNDATION` | [auth.authbus](detail/auth.authbus.md) |
| `secrets.heptabao` | `LANE-A-FOUNDATION` | [secrets.heptabao](detail/secrets.heptabao.md) |
| `runtime.supervisor` | `LANE-B-RUNTIME` | [runtime.supervisor](detail/runtime.supervisor.md) |
| `runtime.fleet` | `LANE-B-RUNTIME` | [runtime.fleet](detail/runtime.fleet.md) |
| `runtime.agentd` | `LANE-B-RUNTIME` | [runtime.agentd](detail/runtime.agentd.md) |
| `runtime.codex` | `LANE-B-RUNTIME` | [runtime.codex](detail/runtime.codex.md) |
| `inference.control` | `LANE-B-RUNTIME` | [inference.control](detail/inference.control.md) |
| `inference.worker` | `LANE-B-RUNTIME` | [inference.worker](detail/inference.worker.md) |
| `automation.taskflow` | `LANE-B-RUNTIME` | [automation.taskflow](detail/automation.taskflow.md) |
| `channel.matrix` | `LANE-B-RUNTIME` | [channel.matrix](detail/channel.matrix.md) |
| `browser.servo` | `LANE-B-RUNTIME` | [browser.servo](detail/browser.servo.md) |
| `ui.control` | `LANE-B-RUNTIME` | [ui.control](detail/ui.control.md) |
| `ui.native` | `LANE-B-RUNTIME` | [ui.native](detail/ui.native.md) |
| `cognitive.types` | `LANE-C-MEMORY` | [cognitive.types](detail/cognitive.types.md) |
| `cognitive.store` | `LANE-C-MEMORY` | [cognitive.store](detail/cognitive.store.md) |
| `cognitive.read` | `LANE-C-MEMORY` | [cognitive.read](detail/cognitive.read.md) |
| `memory.retrieval` | `LANE-C-MEMORY` | [memory.retrieval](detail/memory.retrieval.md) |
| `memory.federation` | `LANE-C-MEMORY` | [memory.federation](detail/memory.federation.md) |
| `knowledge.graph` | `LANE-C-MEMORY` | [knowledge.graph](detail/knowledge.graph.md) |
| `compact.engine` | `LANE-C-MEMORY` | [compact.engine](detail/compact.engine.md) |
| `prompt.registry` | `LANE-C-MEMORY` | [prompt.registry](detail/prompt.registry.md) |
| `context.compiler` | `LANE-C-MEMORY` | [context.compiler](detail/context.compiler.md) |
| `objective.compiler` | `LANE-D-OBJECTIVE-VALUE` | [objective.compiler](detail/objective.compiler.md) |
| `utility.ndu` | `LANE-D-OBJECTIVE-VALUE` | [utility.ndu](detail/utility.ndu.md) |
| `control.runtime` | `LANE-D-OBJECTIVE-VALUE` | [control.runtime](detail/control.runtime.md) |
| `learning.ledger` | `LANE-E-LEARNING` | [learning.ledger](detail/learning.ledger.md) |
| `learning.operator` | `LANE-E-LEARNING` | [learning.operator](detail/learning.operator.md) |
| `learning.eval` | `LANE-E-LEARNING` | [learning.eval](detail/learning.eval.md) |
| `learning.artifacts` | `LANE-E-LEARNING` | [learning.artifacts](detail/learning.artifacts.md) |
| `neuron.runtime` | `LANE-F-ADAPTIVE-POLICY` | [neuron.runtime](detail/neuron.runtime.md) |
| `intuition.policy` | `LANE-F-ADAPTIVE-POLICY` | [intuition.policy](detail/intuition.policy.md) |
| `prompt.optimizer` | `LANE-F-ADAPTIVE-POLICY` | [prompt.optimizer](detail/prompt.optimizer.md) |
| `learning.plasticity` | `LANE-F-ADAPTIVE-POLICY` | [learning.plasticity](detail/learning.plasticity.md) |
| `intelligence.control` | `LANE-F-ADAPTIVE-POLICY` | [intelligence.control](detail/intelligence.control.md) |
| `control.engineering` | `LANE-G-ENGINEERING` | [control.engineering](detail/control.engineering.md) |

## How to use the designs and implementation profiles

Start with `docs/modules/<module>/TECHNICAL.md`, the canonical registry projection and readiness overlay, then the existing detail and the matching `IMPLEMENTATION_PROFILES.json` row. Preserve existing compatible APIs and owner stores. Proposed operations are not assertions of identically named exported native symbols. A library, directory or source observation is not a process, production caller, physical store or independently accepted capability.

Each implementation package records design-operation-to-native-symbol mappings, actual consumers, physical formats/migrations, configuration, clocks, fences, observers, target measurements and recovery results. A test-only caller is labeled as such. Stateless modules prove absence of storage/effects. Separate Python and SQL fixtures are qualification oracles, never a second production ledger, authority service, scheduler or model spine.

The eighteen receipt fields in TECHNICAL.md remain mandatory integration evidence. New APIs and wire/profile meanings require canonical versioned admission before runtime use. The new SQL is a proposed testable persistence design, not a declaration that the existing in-memory cognitive store is durable. Existing durable learning and neural journals retain their actual codecs and anchored recovery.

## Refinement and compatibility rules

Objective conflict extraction is inclusion-minimal and pays feasibility-oracle cost. Sequential policy value requires a history-conditioned estimand, support and clustering rather than a single-decision certificate. Numeric profiles have explicit conversion and digest boundaries; applicable thresholds combine by stricter intersection. Writer lease validity is distinct from business admission. Runtime feedback and initialization/fallback graph constraints are distinct. A composite split/merge cannot reuse the same-owner handoff schema as if cardinality or ownership were unchanged.

Rollback after new-generation writes must preserve those accepted writes and the current deletion/revocation frontier, or refuse rollback and require roll-forward/quarantine. Historical acceptance is not a fresh grant. Current revocation and stop remain effective across frozen snapshots.

## Validation

```bash
python3 scripts/hepta-implementation-dossiers.py self-test
python3 scripts/hepta-implementation-dossiers.py generate-status --check
python3 scripts/hepta-implementation-dossiers.py verify
python3 scripts/hepta-technical-closure.py self-test
python3 scripts/hepta-technical-closure.py verify
python3 qualification/module-execution-dossiers/implementation_contracts.py self-test
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-bundle
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository
python3 scripts/hepta-readiness.py verify
python3 scripts/hepta-docs.py verify
```

`verify-bundle` checks the exported new design surface and explicit nonclaims; it does not require or certify a whole repository. `verify-repository` additionally requires the complete committed checkout, canonical module/lane/root/package bindings, exact observed native source blobs and the corrected NDU blob registry. Existing source-head and deterministic synthetic-merge workflows run both new oracle tests and repository verification without granting write permissions. The existing `verify-details --fixture-dir` remains a separate companion-only check of the original forty detail files.

A machine pass proves its coverage/hash/path/algebra/schema assertions, not semantic completeness, native product execution, future efficacy or independent review. Product acceptance cases remain designs until executed by their native packages. Local oracle results and current repository CI are recorded in the candidate's external evidence, not hard-coded into this README as permanently current facts.

## Closure and authority boundary

`DETAIL_GAPS.json` and `IMPLEMENTATION_COMPLETION.json` retain overall closure false. Native handoff admission, real deployment bindings, complete current CI and independent semantic review remain explicit. Unknown gaps found during implementation are added rather than suppressed to preserve a green count.

All nine `RDY-EXT-*` gates remain external and non-self-certifiable. Real models, future-calendar improvement, empirical biomimicry, target hardware, owner consent, independent acceptance and canary/selection/promotion/release require their own exact evidence. No document, source inspection or oracle grants runtime/effect authority, permits uncontrolled propagation, weakens branch protection or allows a generator to accept itself.
