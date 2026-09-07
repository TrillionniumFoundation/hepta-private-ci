# control.engineering: implementation design

Parent: `docs/modules/control.engineering/TECHNICAL.md`. Lane: `LANE-G-ENGINEERING`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `tools/hepta-engineering-control`.
Packages: `ECP-1-ENGINEERING-CONTROL-PLANE`, `SELF-1-CODE-CANDIDATE-PIPELINE`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
