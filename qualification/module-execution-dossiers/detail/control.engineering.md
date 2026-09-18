# control.engineering: implementation design

Parent: `docs/modules/control.engineering/TECHNICAL.md`. Lane: `LANE-G-ENGINEERING`.
Status: v2 durable scheduling, resource-aware orchestration, candidate qualification, mutation testing, integration-evidence sealing and repository product-caller source are implemented; exact product execution and external production controls remain evidence-gated as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `tools/hepta-engineering-control`.
Packages: `ECP-1-ENGINEERING-CONTROL-PLANE`, `SELF-1-CODE-CANDIDATE-PIPELINE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`issue_repository_work_envelope(repository, store, envelope)` directly verifies the exact Git head/tree/remote for local composition; `issue_signed_work_envelope(store, envelope, source_receipt, trust_store)` is the authenticated remote-service admission path. `plan_engineering_work` consumes the package DAG, signed completion receipts, worker skills/capacity, CI capacity, review topology, expected value, architecture debt and rollback cost and emits bounded assignments, deterministic integration order and authority-free merge-queue proposals. `generate_candidates` supports no-change, atomic multi-file change sets and rename; `SandboxCoordinator` enforces <=8 process-local concurrent sandboxes and <=2 infrastructure-only retries; `run_mutation_testing` requires baseline pass and kills admitted code mutants with the same evaluator-owned check set. `request_independent_review` and `record_integration_decision` remain sealed-evidence transitions, not acceptance or merge.

## 3. State records and transaction design

`work_assignment_projection` and `integration_decision` record exact package/source/tree, owner/co-owners, allowed paths, lease expiry, dependency and contract hashes, sandbox/test budget and candidate state. Candidate artifacts and logs are immutable evidence references. Live PR/CI/branch observations carry freshness and remain external observations rather than cached global source-selection authority.

## 4. Deterministic algorithm and scheduling

Verify signed completion receipts and exact source identity; topologically identify development-ready packages; exclude active-lease and batch path conflicts; score deterministically from expected value minus architecture debt and rollback cost; match required skills and per-worker capacity; reserve CI and reviewer-role capacity; and publish the final assigned/blocked projection, active-lease frontier, integration order and merge-queue proposal atomically in one owner transaction. Infeasible higher-score work does not consume an assignment slot, and durable SQLite assignment truth is identical to the returned resource-aware plan. Generate no-change plus bounded single- or multi-file mutations in credential-free sandboxes; candidate test/fixture/golden paths are unconditionally immutable. The evaluator-owned mutation gate first requires the baseline to pass and then requires every admitted code mutant to fail the same check set. Base drift invalidates affected envelopes.

## 5. Capacity and performance profile

Canonical <=32 candidates, <=8 process-local parallel sandboxes, <=100 changed files, <=1 MiB textual diff and <=2 infrastructure-only retries are source-enforced. Semantic rejection is never retried. Sandboxes retain explicit CPU/memory/process/network/time limits; worker, CI and reviewer capacity are explicit orchestration inputs. These are enforcement ceilings, not throughput measurements. Distributed multi-host concurrency still requires a separately authenticated lease/fencing service and target-host measurements.

## 6. Concrete verification cases

- ECP-01: shared root collision and expired lease prevent concurrent incompatible writes.
- ECP-02: symlink/case/Unicode/mount escape and protected evaluator/policy edits reject before execution.
- ECP-03: exact-base drift invalidates old results; no-change survives candidate enumeration.
- ECP-04: generator/evaluator credential-chain collision prevents acceptance; a branch/PR creation never self-selects, merges or releases the candidate.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Coordinate all seven lanes and the C1/embodiment/authorized-assimilation integration tracks without taking ownership of their facts. Evolution transfers signed capability packages only to independently enrolled hosts. Rollback records exact code/contract/state compatibility and current revocation, with an independent selector.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

The owned disposable service supports additive schema migration with a persistent generation fence, real crash-before/after-commit tests, and old-code rollback at a new generation without restoring old data. This is one reviewed counter service, not a general host adapter or arbitrary stateful organ migration.

- **Implemented entrypoints:** `issue_repository_work_envelope`, `issue_signed_work_envelope` and `plan_engineering_work` in [tools/hepta-engineering-control/control_engineering_v2/orchestration.py](../../../tools/hepta-engineering-control/control_engineering_v2/orchestration.py); `generate_candidates` and `sandbox_candidate` in [candidate.py](../../../tools/hepta-engineering-control/control_engineering_v2/candidate.py); `SandboxCoordinator` in [sandbox_control.py](../../../tools/hepta-engineering-control/control_engineering_v2/sandbox_control.py); `run_mutation_testing` in [mutation_testing.py](../../../tools/hepta-engineering-control/control_engineering_v2/mutation_testing.py); `verify_integration_evidence` in [evidence.py](../../../tools/hepta-engineering-control/control_engineering_v2/evidence.py); sealed review/decision entrypoints in [seal.py](../../../tools/hepta-engineering-control/control_engineering_v2/seal.py); distributed-fence/audit-anchor/key-custody admission in [external_controls.py](../../../tools/hepta-engineering-control/control_engineering_v2/external_controls.py); and the named repository CI caller `build_product_receipt` in [product_gate.py](../../../tools/hepta-engineering-control/control_engineering_v2/product_gate.py).
- **State and recovery:** SQLite v5 remains the single durable coordination owner. Assignment generations bind envelope/source/active-lease frontier and now persist the final resource-aware assigned/blocked set itself; the generation semantic digest additionally binds authenticated completion frontier, worker/CI/review inputs, scoring inputs, integration order and merge queue. A completed package is never reassigned. Worker writes still require a local fenced path lease; production multi-host writes additionally require a signed distributed fence that matches the local lease epoch/token/paths/source and current revocation frontier. The current audit head can be exported for independently signed immutable anchoring. Candidate qualification remains metadata-free and strong-sandbox-only for review evidence.
- **Source tests:** [test_orchestration.py](../../../tools/hepta-engineering-control/test_orchestration.py), [test_candidate_changeset.py](../../../tools/hepta-engineering-control/test_candidate_changeset.py), [test_candidate_policy.py](../../../tools/hepta-engineering-control/test_candidate_policy.py), [test_sandbox_control.py](../../../tools/hepta-engineering-control/test_sandbox_control.py), [test_mutation_testing.py](../../../tools/hepta-engineering-control/test_mutation_testing.py), [test_external_controls.py](../../../tools/hepta-engineering-control/test_external_controls.py), [test_product_gate.py](../../../tools/hepta-engineering-control/test_product_gate.py), plus the existing consolidated, hardening, seal, migration and sandbox suites.
- **Implementation and operating references:** [docs/modules/control.engineering/IMPLEMENTATION.md](../../../docs/modules/control.engineering/IMPLEMENTATION.md), [docs/modules/control.engineering/OPERATIONS.md](../../../docs/modules/control.engineering/OPERATIONS.md), and [tools/hepta-engineering-control/INTEGRATION_HANDOFF.md](../../../tools/hepta-engineering-control/INTEGRATION_HANDOFF.md).
- **Remaining work:** observe successful exact-source and deterministic synthetic-merge execution of the repository product caller; obtain real independent review/acceptance, external HSM/KMS custody, distributed lease/fencing, immutable audit anchoring, authorized target deployment and rollback rehearsal. Those facts are authenticated external receipts and cannot be closed by repository prose or fixture booleans. Scheduling/eligibility still grants no merge, deployment, promotion or release authority.
