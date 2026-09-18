# control.engineering: implementation design

Parent: `docs/modules/control.engineering/TECHNICAL.md`. Lane: `LANE-G-ENGINEERING`.
Status: deterministic scheduling and integration-eligibility source implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `tools/hepta-engineering-control`.
Packages: `ECP-1-ENGINEERING-CONTROL-PLANE`, `SELF-1-CODE-CANDIDATE-PIPELINE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`issue_work_envelope(source_receipt, package, owner, path_lease, budget) -> ParallelLaneEnvelopeV1`; `schedule_ready_packages(dags, capacities, conflicts) -> AssignmentProposal`; `generate_candidate(iteration_envelope, grammar) -> CandidateSet`; `request_independent_review(candidate, evidence) -> ReviewRequest`. Exact source inventory and declared roots are inputs, not permission to alter arbitrary files.

## 3. State records and transaction design

`work_assignment_projection` and `integration_decision` record exact package/source/tree, owner/co-owners, allowed paths, lease expiry, dependency and contract hashes, sandbox/test budget and candidate state. Candidate artifacts and logs are immutable evidence references. Live PR/CI/branch observations carry freshness and remain external observations rather than cached global source-selection authority.

## 4. Deterministic algorithm and scheduling

Topologically identify development-ready packages; exclude path conflicts; reserve shared-type ownership for a contract integrator; issue bounded assignments; generate no-change plus permitted mutations in credential-free sandboxes; run mandatory tests; compare against frozen independent oracles; request review. Base drift invalidates affected envelopes. Generated tests undergo mutation testing; the candidate cannot modify tests/evidence that judge itself.

## 5. Capacity and performance profile

Canonical <=32 candidates, <=8 parallel sandboxes, <=100 changed files, <=1 MiB textual diff, <=2 retries for infrastructure-only failures and zero semantic retry for an unchanged rejected candidate. Sandboxes have explicit CPU/memory/disk/process/network/time limits. Review/CI capacity is a scheduler input, not permission to bypass gates.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

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

The canonical implementation is `tools/hepta-engineering-control/control_engineering_v2/`.
The legacy top-level `hepta_engineering_control.py` remains compatibility-only and is
not a production/native mapping authority.

- **Implemented entrypoints:** `issue_verified_work_envelope` in [tools/hepta-engineering-control/control_engineering_v2/orchestration.py](../../../tools/hepta-engineering-control/control_engineering_v2/orchestration.py); `plan_engineering_work` in [tools/hepta-engineering-control/control_engineering_v2/orchestration.py](../../../tools/hepta-engineering-control/control_engineering_v2/orchestration.py); `persist_orchestration_generation` in [tools/hepta-engineering-control/control_engineering_v2/orchestration.py](../../../tools/hepta-engineering-control/control_engineering_v2/orchestration.py); `generate_candidate_bundle` in [tools/hepta-engineering-control/control_engineering_v2/candidate_bundle.py](../../../tools/hepta-engineering-control/control_engineering_v2/candidate_bundle.py); `sandbox_candidate_bundle` in [tools/hepta-engineering-control/control_engineering_v2/candidate_bundle.py](../../../tools/hepta-engineering-control/control_engineering_v2/candidate_bundle.py); `verify_integration_evidence` in [tools/hepta-engineering-control/control_engineering_v2/evidence.py](../../../tools/hepta-engineering-control/control_engineering_v2/evidence.py); `record_integration_decision` in [tools/hepta-engineering-control/control_engineering_v2/seal.py](../../../tools/hepta-engineering-control/control_engineering_v2/seal.py); `build_product_receipt` in [tools/hepta-engineering-control/control_engineering_v2/product_caller.py](../../../tools/hepta-engineering-control/control_engineering_v2/product_caller.py); `DebianSandboxAdapter` in [tools/hepta-engineering-control/control_engineering_v2/assimilation.py](../../../tools/hepta-engineering-control/control_engineering_v2/assimilation.py).
- **Work orchestration:** the production-facing planner consumes authenticated predecessor completions, worker skill/capacity/path scopes, review slots, CI capacity, expected value, architecture-debt reduction and rollback cost. It emits bounded worker assignments, deterministic integration order and merge-queue proposals. The durable SQLite owner still records immutable assignment generations/frontiers; a proposal grants neither worker write authority nor merge authority.
- **Source identity:** production-facing envelope issuance verifies a signed `CanonicalSourceReceipt` against the exact local Git commit/tree, repository remote, freshness and document-set digest before persisting the envelope. Raw `EngineeringStore.issue_work_envelope` remains the trusted owner primitive for local/internal composition.
- **Candidate pipeline:** the single-mutation API remains compatible, while `CandidateBundle` adds atomic multi-file changes and rename. Test/evaluator paths are unconditionally protected by path classification in addition to configured protected prefixes. Strong qualification still requires the actual Bubblewrap profile.
- **Capacity and retry:** `HostSandboxLimiter` enforces at most eight cross-process sandboxes on one host; `execute_with_infrastructure_retries` permits at most two retries and only for enumerated infrastructure failures. `evaluate_mutation_probes` rejects generated-test evidence when any declared mutant survives.
- **Distributed boundary:** SQLite remains a single-host owner store. Multi-host worker writes require a fresh signed `DistributedWriteGrant` with leader epoch, fencing token, source identity and exact path scope. This is an adapter contract, not a bundled consensus implementation.
- **Audit and key custody:** the local hash chain exports an audit head that must be signed by an external audit-anchor identity. Production verifier custody is represented by a fresh non-exportable hardware-backed `KeyCustodyReceipt`; `HmacTrustStore` remains reference/test-only.
- **Product composition:** `.github/workflows/hepta-consolidated-source.yml` contains the named read-only `engineering-product-gate-v2` caller. It composes exact source issuance, multidimensional orchestration, durable generation persistence and exact-source/synthetic-merge evidence through v2 only. A successful run is product-execution evidence, not independent acceptance or deployment authority.
- **Source tests:** [tools/hepta-engineering-control/test_control_engineering_v2.py](../../../tools/hepta-engineering-control/test_control_engineering_v2.py), [tools/hepta-engineering-control/test_consolidated_engineering.py](../../../tools/hepta-engineering-control/test_consolidated_engineering.py), [tools/hepta-engineering-control/test_full_orchestration_closure.py](../../../tools/hepta-engineering-control/test_full_orchestration_closure.py), [tools/hepta-engineering-control/test_candidate_sandbox_hardening.py](../../../tools/hepta-engineering-control/test_candidate_sandbox_hardening.py), [tools/hepta-engineering-control/test_production_readiness.py](../../../tools/hepta-engineering-control/test_production_readiness.py), and the assimilation tests.
- **Implementation and operating references:** [docs/modules/control.engineering/IMPLEMENTATION.md](../../../docs/modules/control.engineering/IMPLEMENTATION.md), [docs/modules/control.engineering/OPERATIONS.md](../../../docs/modules/control.engineering/OPERATIONS.md), [tools/hepta-engineering-control/README.md](../../../tools/hepta-engineering-control/README.md), [tools/hepta-engineering-control/INTEGRATION_HANDOFF.md](../../../tools/hepta-engineering-control/INTEGRATION_HANDOFF.md).
- **Remaining external work:** the exact PR/head and deterministic synthetic-merge jobs must pass before `productExecutionProved` can be advanced. Independent reviewer acceptance, externally controlled production keys, external audit anchoring, a selected multi-host coordination backend when multi-host execution is enabled, authorized target deployment, canary/promotion/release and rollback rehearsal remain external gates. The dormant Debian adapter is still not a live service controller.
