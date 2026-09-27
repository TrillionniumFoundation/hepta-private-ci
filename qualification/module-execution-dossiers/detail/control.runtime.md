# control.runtime: implementation design

Parent: `docs/modules/control.runtime/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status authority: `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`, projected into `CURRENT_STATE.json` and `CURRENT_PRODUCT_PATH.md`. This dossier describes source semantics, not a second completion database. Read-only Agentd source composition is distinct from global production publication, exact-candidate execution and independent acceptance. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `docs/readiness/CONTROL_RUNTIME_EXECUTION.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-control-plane`. Owner-local package: `RCP-1-RUNTIME-CONTROL-PLANE`; NDU integration package: `RCP-2-NDU-HIERARCHY-INTEGRATION` in `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact symbol and test mappings are in `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

The planner is distinct from the desired-state FSM, organ host, runtime module registry, local cart controller and timing reference. Its storage primitive is a separate maturity component. Agentd retains ownership of its authenticated control listener, canonical cognitive read, retrieval and ranker consumers. The planner has no effect or capability issuance authority.

## 2. Native operations and contract details

Implemented source operations include:

```text
collect_snapshot(SnapshotRequestV1, OwnerSummaryV1[]) -> GlobalStateSnapshotV1
prepare_plan(snapshot, PlanningRequestV1) -> PreparedPlanInputV1
bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1) -> NduPlanEvaluationV1
finalize_plan(snapshot, prepared, ndu_evaluation, now) -> FeasiblePlanReceiptV1
request_execution_grants(snapshot, prepared, receipt, now) -> GrantRequestSetV1
PlannerJournalV1::{append, record_decision, select_plan, revoke, reopen}
PlannerDecisionEnvelopeV1::{from_plan, decode, persist, load, revalidate}
PlannerStoreV1::{create, open, append, get, compact, backup, restore_current, retain_generations}
```

Planning remains two-stage. `prepare_plan` owns snapshot, owner and resource-floor feasibility. `utility.ndu` independently computes its evaluation. `finalize_plan` consumes a digest-bound projection and validates complete candidate coverage. Control does not replace NDU's utility/Pareto semantics. `planner.rs` now rejects noncanonical or unbounded inputs before forwarding to the retained deterministic `planner_kernel.rs`.

Every prepared input, evaluation binding, plan receipt and grant-request set is `AuthorityPosture::DENY_ALL`. A grant request, archive or storage acknowledgement is not a capability.

## 3. Snapshot, state and transaction design

`GlobalStateSnapshotV1` binds exact objective, body generation, configuration, revocation frontier, owner revisions, observation/expiry times, readiness, source frontiers and support. Missing, stale and unavailable owner masks are explicit. Missing owners remain observable; owner summaries outside the declared required set now reject. Native use rechecks both snapshot expiry and each owner's age against current monotonic time.

`PreparedPlanInputV1` retains source and resource-feasible candidate-set digests. It records candidates rejected by essential resource floors. Missing resource axes reject instead of becoming zero. Intrinsic abstain must remain feasible and cannot carry effect payloads. Duplicate payload digests reject instead of silently normalizing an ambiguous request.

`NduPlanEvaluationV1` binds the NDU owner's opaque evaluation digest plus the exact evaluated, rejected, Pareto and advisory projection consumed by Control. Candidate collections are bounded before sorting. Its binding digest is recomputed at finalization.

`FeasiblePlanReceiptV1` binds snapshot, configuration, revocation frontier, candidate sets, resource rejections, NDU policy/evaluation/binding digests, disposition, uncertainty, selected plan and expiry. It claims only a result over the bounded supplied set.

`PlannerJournalV1` remains the bounded digest-only reference with sequence, predecessor hashes and revocation semantics. `PlannerDecisionEnvelopeV1` adds complete canonical consumed projections with native digest parity. `PlannerStoreV1` retains framed bodies under an exclusive OS lock and independently signed current checkpoint. Successful publication requires both synchronized file bytes and verified external compare-and-swap. A write/anchor error poisons the handle until reopen. Only an unacknowledged suffix is truncated; missing committed bytes fail closed.

## 4. Deterministic algorithm and scheduling

1. Bound and validate the closed owner set before canonicalization.
2. Reject mixed objective/body/configuration and future timestamps.
3. Compute missing, stale and unavailable masks and exact snapshot expiry.
4. Bound candidates and resource axes; reject duplicate payloads and effectful abstention before sorting.
5. Reserve essential floors from each endowment.
6. Reject over-budget candidates before NDU evaluation.
7. Require abstain in the feasible set.
8. Bind the independently produced NDU evaluation and exact candidate partition.
9. Reject omitted/injected candidates, binding drift or inconsistent disposition.
10. Publish a bounded-set receipt or unresolved slow-path result.
11. Recheck current owner ages, snapshot, prepared input, receipt, payload and expiry before grant requests.

No global planner call is permitted in a qualified reflex, actuator watchdog or emergency-stop loop. A central outage leaves those local controls independent.

## 5. Capacity and performance profile

Planner ceilings remain 32 owners, 128 candidates, 32 required owners per candidate, 64 final payloads per candidate and 32 resource axes. The reference journal and current store retain at most 4096 records. The file store additionally bounds one envelope to 1 MiB and a complete generation to 64 MiB. Physical generation compaction does not remove semantic history or create unlimited lifetime capacity.

The read-only Agentd listener retains at most 1024 issued context receipts with a one-second monotonic lease. The generic context helper ceiling and Agentd response/metadata budgets remain separate. No raw query or context body is retained in the volatile receipt ledger.

Metrics still require selected-host implementation and measurement: source ages, missing/stale/unavailable masks, resource rejection counts, feasible candidate count, Pareto size, NDU disposition, preparation/finalization latency, journal/store reopen time, anchor latency, receipt-capacity rejection and grant-request count. p95/p99 values require named-host measurements and must not be inferred from source bounds.

## 6. Concrete verification cases

The original acceptance cases remain:

- `RCP-01`: stale or missing required owner blocks preparation.
- `RCP-02`: essential floors filter an over-budget candidate before NDU while preserving abstain.
- `RCP-03`: changed snapshot, body, configuration or revocation frontier invalidates a prepared plan.
- `RCP-04`: local fallback/stop remains independent during central outage.
- `RCP-05`: missing resource axes reject instead of becoming zero.
- `RCP-06`: evaluated and rejected NDU IDs partition the exact feasible set.
- `RCP-07`: tampered NDU binding or uncertainty rejects finalization.
- `RCP-08`: grant requests bind final payloads and remain deny-all.
- `RCP-09`: journal reopen preserves selection.
- `RCP-10`: journal truncation/tampering fails closed and revocation prevents reselection.

Additional source tests cover undeclared owners, repeated payloads, effectful abstention, oversized projections, use-time owner age, canonical record/body mismatch, plan-receipt substitution, profile/generation drift, monotonic expiry, bounded listener receipts, native envelope hash parity, every-byte envelope corruption/truncation, process lock exclusion, partial store tails, lost anchor replies, stale backups and complete-history generation retention.

Test identities are not execution receipts. The process-lock child probe does not substitute for kill-at-every-write-boundary crash qualification. Real ENOSPC, sustained capacity, target-host timing, actual executor revocation and final-payload drift, partial fan-out reconciliation, canary and rollback rehearsal remain open.

## 7. Integration, rollback and capability ceiling

Control consumes objective and NDU facts through typed, digest-bound inputs while their owners remain authoritative. It cannot write objective, preference, utility, independent evaluation or terminal effect outcomes. `kernel.authority` independently decides every concrete grant immediately before an effect boundary.

The real Agentd socket path now passes through `ContextPlanReceipts::response`. `plan_authenticated_context` consumes canonical exact-ID records and computes count/bytes; it does not accept a caller's claimed verified count. Host membership binds the unmodified native plan digest to the exact response, request/query, owner, generation and current retrieval/ranker profiles. Final use retains all existing canonical owner-cut/item checks and repeats lease/profile checks afterward. A lower-level internal state call is not the guarded socket boundary.

Rollback revalidates current owners, frontiers, body/configuration generation and compatible prior policy. It never reuses stale grants. Store restoration must match the independently current signed frontier; an old valid signature is insufficient. Migration from the digest-only journal requires authoritative complete bodies and a separately qualified importer, which is not implemented by compaction.

The target global path remains durable decision publication, an existing independent authority consumer, a named effect executor and terminal reconciliation. No generic storage callback or successful context read establishes that composition. Exact qualification, independent review, deployment and activation remain separate. No model, provider, tool, network, secret, Matrix, fleet, physical-effect, acceptance, merge, promotion or release authority is issued here.

## 8. Current native implementation

`examples/cart_closed_loop.rs` runs the typed cart sensor/controller/actuator loop and emits a bounded CSV trace using the same Q24 simulator. Simulation ticks are not elapsed real time; no hardware, HIL or physical-safety qualification is implied.

- **Planner:** public admission in `codex-rs/hepta-control-plane/src/planner.rs`; retained deterministic kernel and original fixtures in `planner_kernel.rs` and `planner_tests.rs`; NDU evaluation and observed-context helpers remain separate.
- **Durability candidate:** `planner_store.rs` and `planner_envelope.rs` are included in the crate's module tree. There is no configured production anchor adapter or global writer. Store generation compaction, backup and retention are bounded source APIs, not a qualified production migration service.
- **Named read-only caller:** `codex-rs/hepta-agentd/src/control.rs`, `control_context_receipts.rs`, `state_control.rs`, `cognitive_context.rs`, `cognitive_context_planner.rs` and `cognitive_ranker.rs` provide the source call chain. Listener receipt state is explicit and volatile; full production transport/effect/learning terminal accounting remains outside this claim.
- **Organ host and registry:** `OrganHostV1` in `organ_runtime.rs`, module registry in `module_runtime.rs`, and `admit_compiled_body_graph_v2` in `organ_wire.rs`. Trusted compiled-in read-only handlers are not a sandbox or effect executor. Failed migration restoration quarantines dispatch; partial fan-out remains explicitly reported rather than made atomic.
- **Embodiment reference:** `SyntheticCartIoV1` in `embodiment/io.rs` owns an in-memory Q24 plant. Sensor checks include age/calibration; synthetic dispatch checks actuator identity, observation binding and DENY_ALL. Recreating the adapter resets this plant; it is not physical-device recovery.
- **Source tests:** original planner, journal, organ runtime, organ wire and embodiment tests remain. New tests are `planner_admission_tests.rs`, `planner_store_tests.rs`, `planner_envelope_tests.rs`, Agentd `control_context_receipts_tests.rs` and `cognitive_context_planner_tests.rs`. These identify test source, not passing execution at this revision.
- **Operating references:** `docs/readiness/CONTROL_RUNTIME_EXECUTION.md`, `docs/modules/control.runtime/STORE_AND_RECOVERY.md`, `codex-rs/hepta-control-plane/src/ORGAN_RUNTIME.md`, `ORGAN_WIRE.md` and `docs/readiness/EMBODIED_TYPED_IO.md`.

The canonical map and generated current-state files retain separate component states, immutable historical source provenance and exact current source observations. Native test execution, source/merge qualification, independent acceptance and activation must not be advanced by editing this dossier.
