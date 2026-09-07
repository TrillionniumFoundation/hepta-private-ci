# Implementation contracts for the forty-module design

Parent authority: `docs/DEVELOPMENT.md`, plan 8.0.0. This is a subordinate implementation companion, not another global plan. Module identity, data ownership, work packages and Development/Activation/Evidence DAGs remain canonical. The versioned profiles here are proposed implementation contracts until their native producer/consumer and compatibility changes are admitted by the existing owners.

## 1. Authoritative read set

Read the stable module guide, its existing `detail/<module>.md`, the corresponding row in `IMPLEMENTATION_PROFILES.json`, then the applicable shared contracts below. The JSON contains a distinct API, state/encoding, linearization/recovery, bounded algorithm and acceptance oracle for every registered module. It is the editable owner of those supplemental module-specific choices; do not copy them into another independent registry.

| Contract | Required consumers |
|---|---|
| `PERSISTENCE.md` and `COGNITIVE_STORE.sql` | stateful owners, read adapters, supervisor, integration |
| `C1_EXECUTION.md` | runtime, memory, objective, learning, adaptive-policy lanes |
| `ORGAN_EVOLUTION.md` | engineering, plasticity, authority, operations, supervisor |
| `EMBODIMENT.md` | body/sensor, world model, motor/reflex, evaluation |
| `ASSIMILATION.md` | nine existing assimilation components and federation |
| `LEARNING_EXPERIMENT.md` | NDU, neural mechanisms, evaluator, artifacts |
| `NATIVE_BINDINGS.json` | implementers and independent reviewers |

The source observations in `NATIVE_BINDINGS.json` are deliberately bounded: five inspected source files, not forty proven deployments. The remaining native mappings must be produced by implementation packages. No source path, function name, digest or generated profile establishes a production call, physical effect or accepted capability.

## 2. Separate entry and exit gates

Design entry requires an existing package, exact source/tree, permitted write roots, reviewed public contract, algorithm, errors, deterministic fixtures, resource bounds and rollback design. A proposed symbol is allowed here and must be explicitly marked proposed. Do not circularly require a completed implementation or future experiment before its first contract-first coding task.

Source exit additionally requires real native symbols, compiled consumers, physical-format mapping, tests and exact source/merge CI. Integration exit requires named host/process configuration, real owner stores, authenticated observers, crash/reopen, current revocation and new-process reload. Capability exit adds the applicable nine external gates. Physical or future-window evidence is never manufactured by passing a document validator.

The flags `productTestsExecuted`, `deploymentQualified`, `longitudinalEfficacy`, `functionalBiomimicry`, `selfIteration`, `independentAcceptance` and `allGapsClosed` remain false in this document-delivery profile. They describe what this delivery does not prove; they do not erase independently obtained evidence elsewhere.

## 3. Common operation envelope

Every externally serialized operation binds schema/profile version, principal/purpose, module/organ/body generation, operation ID, semantic payload digest, expected predecessor, monotonic deadline with clock identity, resource budget and permitted effect class. Critical unknown fields reject. Do not implement a generic `execute(shell_text)` port.

Stable IDs retain the existing grammar and equality; case folding, trimming or Unicode normalization cannot turn one principal into another. SHA-256 digests are exact bytes or canonical lowercase hex, not approximate numeric values. Serialized u64 counters use an exact representation across Rust/TypeScript/Python. Numeric values additionally bind units, shape, scale, rounding and overflow policy. Wire witnesses are not reconstructible consumable authority tokens.

Common result classes are Rejected, Unsupported, Unavailable, Exhausted, Conflict, CancelledBeforeEntry, Entered, Indeterminate, Applied, NotApplied and Quarantined, mapped to existing native enums by an explicit adapter. A narrower existing enum is not silently given a new meaning. `Unsupported` and `Exhausted` cannot be relabelled infeasible, and transport acceptance cannot be relabelled applied.

## 4. Native binding packet

Each implementation package publishes the existing eighteen dossier fields with concrete values: source receipt; guide digest; source roots; entrypoints; consumer callsites; host runtime identity; binary/artifact digest; configuration/body generation; physical state; schema/migration; writer fence; terminal observer; revocation source; fault results; resource measurements; fallback; rollback predecessor; external-gate disposition.

Entrypoints bind language-qualified symbol, source path/blob and build target. Callsites identify the real product path, not merely a test invocation. A host binds executable, argv/configuration digests, OS/architecture, process generation, failure domain and owner-issued handles. A state binding declares actual path/mount/filesystem or absence with a no-owned-state test. Never invent a database for a stateless type/wire/read-only module.

A design packet may explicitly say `binding_required`. An integration pass may not. `none_by_design` requires the corresponding executable absence test, not an empty string. The validator's source/hash matching remains lexical source evidence, not a compiler or runtime proof.

## 5. Revocation, dispatch and cancellation

Use one serialized authority admission gate per relevant scope. Revocation durably advances its frontier before return; new entries compare the current frontier and consume their final-payload token under the same ordering mechanism. Record entry order without keeping a global lock across network/provider work.

An operation admitted before revocation can remain in flight. Stop later entries, request supported cancellation and reconcile its actual outcome. Do not promise that a local revoke retroactively prevents a remote effect already admitted. Stronger remote fencing or physical stop guarantees require the destination's independently tested mechanism.

Any software reflex clamp that changes the transmitted payload occurs before final hashing/authorization. A later payload change invalidates the token and requires re-binding or veto. A hardware saturation limit may constrain observed motion, but cannot be used to claim that a different command payload was authorized. Cancellation before entry differs from cancellation requested after entry; unknown completion never becomes a refund or a retry permission.

## 6. Ownership and persistence

A library, organ role, process and durable owner are different identities. Agentd and intelligence composition keep handles and snapshot references; they do not acquire new all-purpose domain stores. Owner adapters alone perform mutations. Cross-owner changes retain local transaction -> durable publication intent -> governed outbox -> destination dedupe/apply -> acknowledgement -> fenced reconciliation.

Before any mutation, preflight counter overflow, bounds, expected predecessor and current authority. An error after validation must not leave a partially advanced in-memory projection or persistent record. In particular, native cognitive append wrappers must test sequence exhaustion before publishing record changes. Failure atomicity is an implementation acceptance case, not implied by this documentation change.

`PERSISTENCE.md` distinguishes the observed in-memory CognitiveStore from native durable learning and neural journals. No documentation edit replaces their existing physical bytes. Proposed stores/migrations require owner review, parity tests and rollback before admission.

## 7. Seven-lane execution contract

The canonical lanes remain A foundation, B runtime, C memory, D objective/value, E learning, F adaptive policy, G engineering. A single contract integrator publishes shared types/protocols and holds the relevant path lease. Other owners implement private internals and fixture adapters behind frozen contracts. Parallelism is limited by source-root conflicts and CI/reviewer capacity, not only by available coding agents.

Use I0 exact source, I1 compiled types, I2 real stores, I3 deterministic read-only product path, I4 shadow data/artifacts, I5 new-generation load plus future/retention evidence, I6 bounded iteration, and I7 qualified embodiment/assimilation. These checkpoints do not override package predecessors. Separate engineering reload proof from future-calendar efficacy inside I5.

Each PR binds one package or co-owned integration checkpoint, exact contracts, allowed paths, tests, resources, rollback and stop conditions. Infrastructure-only retries are bounded; unchanged rejected semantics are not retried until they happen to pass. Base drift refreshes only affected envelopes through explicit dependency analysis; it never silently preserves stale evidence.

## 8. Document and evidence closure

`IMPLEMENTATION_COMPLETION.json` enumerates this delivery's finite design requirements and their traceability. `specified` means an inspectable contract exists. A local reference pass checks only tested algebra, state transitions and document consistency. Independent semantic review, full repository CI, native protocol admission, real host/model/hardware, future outcomes and release decisions remain separate.

Do not delete a discovered gap, weaken a threshold, label an implementation gap external without explanation, or collapse all classes into a green `complete`. New defects are recorded with owner, reproducer, required evidence and blocker class. The coding plan can advance on eligible bounded packages while incompatible or unqualified capabilities remain disabled.
