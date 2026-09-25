# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate and authenticated Agentd product-source composition implemented; exact-head/synthetic-merge qualification, named target-host observation, independent acceptance and activation remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no authority or effect ownership. The compiler remains stateless for domain facts. The named caller is Agentd `ObjectiveRuntimeHost::submit`: a signed AuthBus objective is authenticated against current trust before the owner-local admission context is constructed; `compile_and_publish_objective_run_v1` rebinds source, authenticated context, admission receipt, native result and canonical projection, then appends both native and protocol identities plus `RunStartSnapshotV1` to the destination-owned segmented `DurableRunStartStore` before a non-abstain run reaches `AgentRunCoordinator`. Every append and compaction transition is fenced by an independent monotonic checkpoint outside Agent home. A compiled fallback receipt returns an `ObjectiveRunExecutionBinding` copied from the exact durable record so a trusted execution owner can attach independently produced context without reconstructing or substituting the daemon snapshot. The binding grants no effect authority. Exact replay is idempotent; same-run semantic drift conflicts; restart recovery detects rollback and revalidates retained authentication against current trust.

## 2. Native operations and contract details

The implemented path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_objective_v1(envelope, profile, authenticated_context)
compile_admitted_objective_v1(admitted)
  -> compiler::compile(native_envelope)
     -> scalar_adapter::scalar_conflict(...)
        -> check_feasibility_v1(grammar, atoms, deterministic_budget)
```

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping every losslessly representable field. Unknown or unrepresentable semantics fail closed. The opaque `AdmittedObjectiveV1` type prevents ordinary downstream code from entering the compiler with a caller-constructed legacy envelope; the old raw compiler surface is available only behind the explicit `qualification-legacy-compile` Cargo feature. The admission receipt and compiler output carry no effect authority.

`abstain` is intrinsic and confirmation-free. A request cannot forbid or confirmation-gate it. An empty caller legal-action set is valid and produces `ExplicitAbstain`. The compiled action ceiling is 128 including abstain: at most 127 caller actions when abstain is implicit, or 128 when the caller supplies the valid intrinsic action explicitly.

## 3. State, identity and publication

The compiler owns no durable store. Its pure output binds request, principal, source, schema, selected profile, hard constraints, legal actions, success and terminal predicates, evidence requirements, resource/risk policy and native semantic digest. The product path uses `encode_authenticated_objective_function_v1` to recompute the admitted/native result before separately materializing the registered canonical JSON contract and protocol-wire digest; the decoder enforces semantic uniqueness, canonical order, intrinsic abstain, disjoint actions and weight bounds. Agentd publishes both identities through the destination-owned durable run-start v2 store together with ingress authentication and `RunStartSnapshotV1`. The store syncs framed appends, rotates bounded segments, compacts only expired sealed prefixes, and CAS-binds append/compaction state to an external checkpoint; it preserves exact-run idempotence and rejects native/protocol drift, missing history and rollback. Legacy v1 records are read-compatible but fail closed at Agentd final use. The compiled product fixture attaches the exact binding, obtains current final-use authority, commits dispatch before one physical App Server send, writes terminal observation to the same run and proves an exact durable retry does not resend. The deployed host and its backup/power-loss profile remain activation concerns.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are generated from `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode and normalize bounded fields, authenticate source, map registered units/IDs and stable-sort all sets. Source V1 maps only losslessly representable scalar `eq/lte/gte` hard semantics into the native scalar compatibility IR; strict/set operators fail closed. The direct typed feasibility API is richer and supports finite-enum intersection, positive action implications and immutable identities. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. These paths have separate CPU, wall-clock and metric budgets. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Pilot library bounds are 256 KiB raw input, **246 source constraints + 10 generated resource/risk constraints = 256 native hard constraints**, **128 aggregate success/terminal/evidence predicates**, 64 soft dimensions, 127 caller legal actions without explicit abstain, 128 source/compiled actions when abstain is explicit, and 257 conflict-oracle calls. The normal Agentd product route is intentionally narrower: source JSON is at most 32 KiB and the canonical signed body at most 48 KiB. Exact microsecond deadlines remain in admission and RunStart; the V1 wire and final-use millisecond boundary use a conservative floor. No network or synchronous central RPC occurs in the deterministic compiler path.

Latency claims require a named host, compiler, build profile, input class and exact source. `scripts/hepta-objective-target-measure.py` plus `docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md` provide an exact-source release-mode recorder with separate ordinary authenticated-admission and maximum-conflict p50/p95/p99 measurements. The harness is source-implemented; no target-host result is claimed until it is run on the selected host profile. A normal successful compile measurement cannot be reused as a conflict-extraction measurement.

## 6. Concrete verification cases

- `OBJ-DETAIL-01`: disjoint scalar intervals produce an inclusion-minimal conflict and remove irrelevant atoms.
- `OBJ-DETAIL-02`: equivalent reordered inputs produce identical semantic digests.
- `OBJ-DETAIL-03`: unsupported language or oracle exhaustion never weakens the legal set.
- `OBJ-DETAIL-04`: principal network prohibition dominates task text.
- `OBJ-DETAIL-05`: intrinsic abstain cannot be forbidden or confirmation-gated.
- `OBJ-DETAIL-06`: 127 caller actions plus implicit abstain compile to 128; 128 without abstain reject.
- `OBJ-DETAIL-07`: source, schema, profile, normalization or intent digest mismatch fails before native compile.
- `OBJ-DETAIL-08`: 247 source constraints reject before native expansion; success+terminal+evidence aggregate above 128 rejects.
- `OBJ-DETAIL-09`: signed objective ingress is authenticated against current AuthBus trust before admission context construction; restart reconciliation revalidates retained authentication.
- `OBJ-DETAIL-10`: `OBJ-E007` retry is variant-specific rather than code-family-wide.
- `OBJ-DETAIL-11`: canonical `ObjectiveFunctionV1` round-trips exact bytes and its protocol digest is distinct from the native semantic digest.
- `OBJ-DETAIL-12`: partial tail recovers only to the last complete frame; acknowledgement loss replays idempotently; same-run protocol drift conflicts.
- `OBJ-DETAIL-13`: generation/fence drift and legacy records without canonical protocol identity fail closed before runtime admission.
- `OBJ-DETAIL-14`: recovered signed authentication is rechecked against owner trust; revocation and key-epoch rotation reject the retained record.
- `OBJ-DETAIL-15`: source/profile/context/native-result drift, duplicate semantic identities, non-canonical ordering, confirmation-gated abstain and invalid soft weights reject before publication.
- `OBJ-DETAIL-16`: bounded segments rotate without resetting the chain; expired sealed prefixes compact through checkpointed crash cuts; missing/stale/ahead checkpoints and removed segments fail closed.
- `OBJ-DETAIL-17`: Agentd requires the objective profile and external checkpoint together; the private checkpoint has one live writer, exact binding and no placement inside Agent home.
- `OBJ-DETAIL-18`: a compiled ObjectiveStart returns the exact daemon execution identity without authority; one attached run obtains current final-use authorization, performs exactly one physical App Server turn, publishes terminal success, returns the same durable observation on exact retry and cannot resurrect after restart.

Native test files and symbols are registered in the implementation map. A green fixture proves only the tested source boundary; it is not a production-caller or efficacy receipt.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. NDU and Control consume the frozen objective but cannot mutate its hard constraints, observer requirements or legal effects. Rollback reuses a prior objective only when request/principal compatibility and current revocation checks pass; otherwise it starts a newly authorized run or abstains.

The candidate issues no model/provider/tool/effect/secret/fleet/acceptance/promotion/release authority. It does add a bounded runtime-objective **source composition** in Agentd, but deployed product activation, current-host trust/store qualification, independent review and exact-head/synthetic-merge workflow success remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `admit_objective_v1` / `compile_admitted_objective_v1` / `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs); product caller `ObjectiveRuntimeHost::submit` in [codex-rs/hepta-agentd/src/objective_runtime.rs](../../../codex-rs/hepta-agentd/src/objective_runtime.rs); authenticated canonical projection `encode_authenticated_objective_function_v1` and strict `decode_objective_function_v1` in [codex-rs/hepta-objective/src/objective_function_v1.rs](../../../codex-rs/hepta-objective/src/objective_function_v1.rs); durable publication `compile_and_publish_objective_run_v1` in [codex-rs/hepta-intelligence/src/objective_run.rs](../../../codex-rs/hepta-intelligence/src/objective_run.rs).
- **State and recovery:** The compiler remains stateless. Agentd authenticates signed ingress against current AuthBus trust, and the destination-owned `DurableRunStartStore` persists ingress authentication, admission binding, owner-native semantic bytes/digest, canonical `ObjectiveFunctionV1` bytes/protocol digest, runtime body binding and `RunStartSnapshotV1`. It rotates bounded segments, checkpoint-compacts expired sealed prefixes, reconciles acknowledgement loss, rejects rollback/missing history, preserves exact replay, rejects native/protocol drift and revalidates generation, fence, deadline and current trust before runtime rehydration. `ObjectiveRunStartCheckpointFile` supplies the private external monotonic CAS owner and writer lock. A compiled fallback receipt exposes only the exact `ObjectiveRunExecutionBinding`; `AppServerModelDriver::run_intelligence` must attach context, acquire current final-use authority, durably mark dispatch, send once and publish the observed terminal state.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [objective_function_v1_strict_tests.rs](../../../codex-rs/hepta-objective/src/objective_function_v1_strict_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs), [codex-rs/hepta-learning-ledger/src/run_start_tests.rs](../../../codex-rs/hepta-learning-ledger/src/run_start_tests.rs), [run_start_store_tests.rs](../../../codex-rs/hepta-learning-ledger/src/run_start_store_tests.rs), [codex-rs/hepta-intelligence/src/objective_run_tests.rs](../../../codex-rs/hepta-intelligence/src/objective_run_tests.rs), [codex-rs/hepta-agentd/src/objective_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/objective_runtime_tests.rs), [objective_run_start_checkpoint_tests.rs](../../../codex-rs/hepta-agentd/src/objective_run_start_checkpoint_tests.rs) and real-process [objective_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/objective_product_e2e.rs). These are source identities; pass/fail remains exact-candidate workflow evidence.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Remaining work:** obtain current exact-head and deterministic synthetic-merge green receipts for the canonical branch; run ordinary and maximum-conflict measurements on the selected target-host profile; qualify crash/restart/backpressure and deployed trust/store ownership there; retain independent semantic acceptance and activation/release as external gates.
