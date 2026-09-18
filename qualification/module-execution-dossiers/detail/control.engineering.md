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

The canonical implementation root is `tools/hepta-engineering-control/control_engineering_v2`.
The historical `hepta_engineering_control.py` module is compatibility-only and is
not a product/native authority path. A permanent regression rejects product-package
imports of that legacy module.

- **Authenticated source and work admission:** `issue_authenticated_work_envelope`
  in [orchestration.py](../../../tools/hepta-engineering-control/control_engineering_v2/orchestration.py)
  verifies the signed `CanonicalSourceReceipt`, repository identity, exact Git
  commit/tree, document-set digest and freshness before persisting a work envelope.
- **Engineering orchestration:** `schedule_engineering_work` consumes authenticated
  predecessor completion receipts, worker skills/capacity, review topology/capacity,
  CI capacity, expected value, architecture debt, rollback cost, source-root conflicts
  and the durable lease frontier. It emits worker assignments, deterministic
  integration order and non-authoritative merge-queue proposals. Distributed mode
  additionally requires a signed leadership receipt and fencing epoch.
- **Durable owner state:** `EngineeringStore` in
  [control_plane.py](../../../tools/hepta-engineering-control/control_engineering_v2/control_plane.py)
  remains the sole SQLite v5 owner for envelopes, path leases, fencing, assignment
  generations/frontiers, integration decisions/seals and hash-linked audit events.
- **Candidate construction:** single-file compatibility candidates remain in
  [candidate.py](../../../tools/hepta-engineering-control/control_engineering_v2/candidate.py);
  atomic multi-file changes use `CompositeCandidate` in
  [composite_candidate.py](../../../tools/hepta-engineering-control/control_engineering_v2/composite_candidate.py).
  Autonomous candidates cannot modify test/evaluator/fixture/qualification/policy
  oracle paths even when a caller attempts to widen the candidate envelope.
- **Sandbox capacity and retry:** [sandbox_control.py](../../../tools/hepta-engineering-control/control_engineering_v2/sandbox_control.py)
  admits at most eight concurrent sandboxes per coordinator process and permits at
  most two retries for enumerated infrastructure failures. Semantic rejection is
  never retried.
- **Mutation testing:** `run_mutation_testing` in
  [mutation_testing.py](../../../tools/hepta-engineering-control/control_engineering_v2/mutation_testing.py)
  runs evaluator-owned checks against admitted source mutants; every mutant must be
  killed for the receipt to pass.
- **Integration evidence and decisions:** exact source/synthetic-merge evidence,
  independent identities, candidate binding, signed seals and replay-safe durable
  decisions remain in `evidence.py`, `closure.py` and `seal.py`.
- **Product caller:** `control_engineering_v2.product_gate` is a named repository
  caller executed by the consolidated source workflow only after strong sandbox and
  source qualification jobs succeed. It exercises the v2 orchestration path and
  emits no merge/deploy/release authority.
- **External production evidence:** [external.py](../../../tools/hepta-engineering-control/control_engineering_v2/external.py)
  verifies signed external audit anchors, key-custody receipts and deployment facts.
  `evaluate_authenticated_production_readiness` ignores caller booleans for those
  external facts and derives them from verified receipts. A distributed deployment
  cannot be ready without its fencing receipt.
- **Source tests:** [test_orchestration_v2.py](../../../tools/hepta-engineering-control/test_orchestration_v2.py),
  [test_composite_candidate.py](../../../tools/hepta-engineering-control/test_composite_candidate.py),
  [test_mutation_testing.py](../../../tools/hepta-engineering-control/test_mutation_testing.py),
  [test_external_evidence.py](../../../tools/hepta-engineering-control/test_external_evidence.py),
  [test_product_gate_v2.py](../../../tools/hepta-engineering-control/test_product_gate_v2.py),
  plus the existing control-plane, sandbox, seal and consolidated regression suites.
- **Remaining external work:** real HSM/keystore custody, external immutable audit
  service, distributed consensus/leader service when distributed mode is selected,
  independent reviewer acceptance, authorized target-host deployment, operator
  acceptance, canary/promotion/release and rollback witness remain external evidence
  gates. Repository code verifies their receipts; it does not impersonate those
  authorities.
