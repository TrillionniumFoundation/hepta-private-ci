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

- **Implemented entrypoints:** `schedule` in [tools/hepta-engineering-control/hepta_engineering_control.py](../../../tools/hepta-engineering-control/hepta_engineering_control.py); `decide_integration` in [tools/hepta-engineering-control/hepta_engineering_control.py](../../../tools/hepta-engineering-control/hepta_engineering_control.py); `DebianSandboxAdapter` in [tools/hepta-engineering-control/control_engineering_v2/assimilation.py](../../../tools/hepta-engineering-control/control_engineering_v2/assimilation.py).
- **State and recovery:** The base scheduler consumes immutable package/dependency/path-lease inputs and returns bounded assignments. Integration eligibility binds exact source/base/ordered synthetic-merge identities; supplied booleans or receipts are not GitHub execution or release authority. DebianSandboxAdapter provides consent-expiry-checked query_version/query_health/read_status over a disposable Debian rootfs. Each read reopens the pinned root inode, walks every child through directory descriptors with O_NOFOLLOW, and rechecks directory/file identity before and after reading. Regular single-link files must stay on the root device; version/unit/status reads are bounded to 16 KiB/64 KiB/2 MiB. A separate disposable counter-service target now exercises actual unprivileged child readiness, SQLite commit/restart and lost-acknowledgement reconciliation; it grants no live-service authority. The read-only Debian adapter identity and receipt state are process-local; unit-file presence is metadata, not running-service health, and no shell/service-manager/network calls occur.
- **Source tests:** [tools/hepta-engineering-control/test_hepta_engineering_control.py](../../../tools/hepta-engineering-control/test_hepta_engineering_control.py), [tools/hepta-engineering-control/test_integration_identity.py](../../../tools/hepta-engineering-control/test_integration_identity.py), [tools/hepta-engineering-control/test_assimilation_sandbox.py](../../../tools/hepta-engineering-control/test_assimilation_sandbox.py). Named fixture regressions `test_parent_symlink_swap_during_open_never_reads_outside_root` and `test_parent_directory_replacement_during_read_discards_observation` cover parent-path escape and drift rejection. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [tools/hepta-engineering-control/README.md](../../../tools/hepta-engineering-control/README.md), [tools/hepta-engineering-control/INTEGRATION_HANDOFF.md](../../../tools/hepta-engineering-control/INTEGRATION_HANDOFF.md).
- **Remaining work:** Bind live repository/CI/independent review identities and authorized handoff. Scheduling eligibility does not itself merge, deploy, release or complete autonomous development. The fixture adapter does not discover or control live Debian services. Its supplied consent/identity still requires a trusted owner; independently witnessed target parity, live service observation and authorized production deployment remain outside this read-only fixture implementation.
