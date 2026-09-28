# runtime.fleet: implementation and execution dossier

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`  
Current state: `docs/modules/runtime.fleet/CURRENT_STATE.json`  
Execution binding: `docs/modules/runtime.fleet/EXECUTION_BINDING.md`  
Scoped local evidence: `docs/modules/runtime.fleet/LOCAL_VALIDATION.json`  
Lane: `LANE-B-RUNTIME`  
Owner/deputy: `fleet-runtime` / `runtime-control`

## 1. Scope and claim boundary

This dossier records repository-controlled source implementation, actual scoped local checks and outstanding qualification for PR #1060. The branch is `codex/runtime-fleet-durable-owner-v1-2026-09-27`. The last source-change anchor is `3b3285b007e822911bafd867404316c010fe6d5e`; the frozen integration base is `a126987b84737dbc2ee2592442a314117bddb4a2`. Later documentation commits require their own exact-candidate receipt; the code anchor is not such a receipt.

Complete repository-controlled source closure and named-product lifecycle closure are not asserted. Complete containment/quiescence-to-release composition, stop-only recovery for already-running expired/revoked scopes and final Cargo/merge execution evidence remain outstanding. This dossier grants no deployment, independent acceptance, promotion or release. The existing `hepta-supervisord` remains the single named Fleet owner; no parallel writer is introduced.

## 2. Public owner operations

| Operation | Native entry point | Durable/effect boundary |
|---|---|---|
| register Agent | `FleetRegistry::register` | Fleet-wide lock, workspace reservation, staging rename, directory sync |
| read one registration | `AgentManifest::read_registered` | Bounded physical manifest read without registry mutation or unrelated-Agent scan |
| transition lifecycle | `FleetRegistry::compare_and_transition` | Fleet-wide lock, immutable lifecycle generation, directory sync |
| resolve boot incarnation | `DurableFleetOwner::resolve_host_incarnation` | Opaque boot identity checked against a persisted monotonic generation |
| observe capacity | `DurableFleetOwner::refresh_capacity` | Stable operation ID, selected-host observer, immutable Fleet generation |
| calculate local shares | `calculate_local_allocation_v1` | Authority-free deterministic calculation only |
| map resources | `map_logical_to_physical_v1` | Versioned mapping policy and digest receipt |
| issue allocation | `DurableFleetOwner::issue_with_authority` | Final authority revalidation and atomic durable publication |
| renew/revoke | `DurableFleetOwner::renew_or_revoke` | Lease-generation/epoch/digest fences; authorization retirement does not erase physical holds |
| collect expiry | `reconcile_expired_idempotent` | Operation-ID-first owner-time observation; physical reservations retained when held |
| persist revocation | `DurableFleetOwner::persist_revocation_snapshot` | Signed update/ack snapshot in immutable generation |
| verify final use | `verify_final_use_with_revocation` | Current grant plus fresh converged revocation cut |
| prepare physical effect | `DurableFleetOwner::prepare_execution` | Intent before effect; independent context, duplicate identity and aggregate-budget checks |
| reconcile held group | `DurableFleetOwner::reconcile_execution_group` | Library all-or-none quiescence gate; complete native product adapter not yet composed |
| inspect existing state | `lock_fleet_snapshot` / `read_fleet_snapshot` | Read-only existing-state/frontier validation; no initialization or repair |
| maintain product state | `run_supervisord_product` | Existing supervisor owner; ordinary pressure/shrink separated from integrity failure |
| admit physical process | Unix `ProcessDriver` wrapper and `ProcessBinding` | Registered requirements, independent host binding, durable intent and shared fence across the raw effect |

## 3. State and transaction design

The durable owner stores hosts, boot incarnations, observations, active grants, terminal history, expiry index, retained execution holds, resource totals, revocation update/acknowledgements, workspace-reservation digest and operation receipts. Successful issue stores its authority witness in the same immutable generation as the grant.

Mutations serialize through `owner.lock`. A candidate is validated in memory, published as a checksummed immutable generation and followed by an independently checksummed `latest-frontier-v1.json`. State and frontier directory synchronization complete before success is returned.

The frontier is monotonic. Writer recovery may advance it only when descent from the pinned state digest is proved. Tail deletion, missing nonzero frontier, same-generation drift or unverifiable gaps fail closed. Read-only status does not silently perform that repair.

Physical totals are rebuilt from active grants and retained execution holds. The allocation reservation is counted once, while aggregate execution demands within that allocation must fit its grant. Missing or unsuccessful quiescence evidence preserves the reservation across owner reopen.

## 4. Allocation, capacity and resource semantics

The deterministic local allocator reserves minimums first and distributes remaining capacity by stable discrete weighted max-min fairness. It is explicitly non-authorizing.

`ResourceVectorV1` defines canonical units and the supported-axis mask. Logical compatibility types convert to canonical vectors. Physical mapping uses a reviewed `ResourceMappingPolicyV1`, with a receipt binding policy, logical and physical digests.

The native process requirement comes from the registered manifest rather than the grant under test. `HEPTA_FLEET_RESOURCE_MAPPING_PROFILE` must identify a bounded, physical, operator-owned profile outside the entire Fleet root. Without a mapping, logical requirements remain logical; unsupported axes are not discarded and CPU coefficients are not invented. Agentd and Matrixd have separate execution contexts, so their allocation must cover the sum of retained mapped demands. Simultaneous-role mapping and budget qualification remain required.

Selected-host capacity comes from operating-system observation. A same-generation shrink below commitments is rejected atomically. Stale observations deny issue and renew. The new-process boundary independently samples current capacity/pressure before preparing intent. A boot identity is not an ordered generation; a committed incarnation separately orders boots and fences predecessor authorization without deleting physical holds.

## 5. Active/history split and bounded compaction

The lifetime-limit design is addressed by separating live grants from terminal history. `MAX_ACTIVE_GRANTS` limits simultaneous active grants. Revocation, expiry and host-generation replacement remove active authorization entries and append terminal records; the indexed expiry path does not claim that a running execution stopped.

The ledger's authorization release and the durable physical release are different operations. Retained physical pins survive terminal authorization until complete selected-host quiescence is proved. The current native wrapper does not automatically release pins on parent exit, a signal or a changed generation.

Terminal history and operation receipts have bounded windows and chained compaction digests. Indefinite searchable replay detection remains an external audit-retention obligation. Compacted absence is not proof of noncommit. Execution holds are not disposable terminal-history debris.

## 6. Authority and revocation

Allocation issue computes binding from the grant rather than accepting a caller-provided scope. The generic authority lease is revalidated at the final owner mutation boundary. Its persisted witness is audit evidence, not authority for a new operation.

Revocation persistence contains signed evidence only. Feed/node trust roots arrive independently through `FleetStartTrustProfileV1`. Final use requires a fresh converged cut and local node `Ready`; catch-up, quarantine and stale feed deny use. Current grant selection excludes revoked and expired entries and requires an unambiguous principal match.

Process preparation checks independently obtained host/boot/incarnation, registered resources and execution context against that authority. A shared validated owner fence remains held across synchronous raw spawn/adopt. This source binding does not establish executable-file immutability or kernel containment.

## 7. Named product composition

`hepta-supervisord` opens the existing registry and durable Fleet owner, refreshes capacity every 20 seconds with a 60-second TTL, reconciles authorization expiry and requires an immutable Fleet start trust profile. Ordinary pressure/capacity shrink is not automatically a fatal Supervisor error; integrity failures are not reclassified as ordinary capacity events.

The product scopes admission over the Unix driver. Agent and Matrix new spawns persist intent before raw effects. Adoption requires a matching retained intent and the raw driver's process/control-socket identity checks. The same immutable borrowed specification is framed and consumed. Command framing retains non-UTF-8 Unix bytes, argument boundaries, ordering and paths.

A managed-process monitor requests stop after authority denial and escalates while the process is still polled. Neither a stop signal nor observed parent exit releases the durable physical pin. Existing pins after ambiguous spawn or failed recovery remain conservative reservations.

Two product components remain unclosed: complete selected-host containment/quiescence-to-release composition, and stop-only recovery authority for an already-running expired/revoked scope after Supervisor restart. Normal execution adoption cannot substitute for that stop-only authority. Unscoped legacy library compatibility remains outside the named product scope and is not a product proof.

## 8. Current implementation and actual evidence

### Existing and newly composed source surfaces

Source includes the durable registry and lifecycle, workspace serialization, owner clock, canonical resources and mapping, local allocator, active/history/expiry/compaction ledger, authority-bound issue, signed revocation state, non-rollback frontier, monotonic incarnation, Linux capacity observer, named maintenance, read-only status, independent process binding, durable physical intent and aggregate execution checks.

The Supervisor test-helper shadowing repair, monotonic incarnation, read-only snapshot helper and strict status parsing were already present on the incoming candidate. This delivery reviewed and retained them, added the execution binding and receipt hardening, and corrected stale completion and capacity-release claims.

### Regression sources and required commands

Regression sources cover lifetime grant churn, simultaneous limits, exact expiry and revocation, stale observations, digest mutation, overlapping registration, publication failure, durable reopen, revocation restore, final-use fences, frontier tampering, procfs parsing, boot identity and pressure classification. New sources add duplicate/renamed execution identity, aggregate overspend, unavailable quiescence, unchanged rejected state, read-only registration and raw Unix command bytes. The owner-level child tests use a real controlled `/bin/sleep` process but do not cover arbitrary descendants or the complete Agentd/Matrixd product.

Cargo tests, named-binary compilation and Clippy are execution requirements, not tests that have passed merely because they appear in this section.

### Checks actually run locally

The selected-file reconstruction was not a complete Git checkout and had no usable Cargo/compiler toolchain. Eight source-file blobs matched the remote code anchor. `LOCAL_VALIDATION.json` contains exact commands, file digests and complete local logs:

| Check | Actual result | What it does not prove |
|---|---|---|
| Python qualification-mechanism regressions | 16 passed, exit 0 | Rust compilation/tests, real product execution |
| Repository-artifact Rust 1.95 rustfmt on six selected changed Rust files | Exit 0, with existing stable-channel configuration warnings | Whole-workspace formatting, type checking or Clippy |
| Eight local/remote Git blob comparisons | Matched | Full source tree or synthetic merge qualification |

No local Cargo test, binary compilation, strict Clippy, whole-workspace formatting, full exact-source or synthetic-merge qualification, protected-host test or Agentd/Matrixd containment/crash E2E result is claimed. `skip_children=true` in the selected-file formatter invocation is explicitly not a package-level formatting result.

### Remaining acceptance gates

Obtain final exact-source and deterministic merge receipts; compose and execute complete containment/quiescence release and stop-only crash recovery; qualify actual concurrent process budgets and mappings; exercise the protected host, pressure, long backlog and cancellation; retain deployment-required multi-node revocation and external audit evidence; obtain independent acceptance and release authority separately.

## 9. Failure semantics

Pre-publication validation failures reject without publishing the candidate. State/frontier publication that may be visible but was not confirmed durable is `IndeterminateCommit`. Retained same-ID/same-digest operations reconcile to their receipts; conflicting digests reject. A missing compacted receipt is unresolved history, not noncommit.

Stale authority, revoked/expired grants, non-ready revocation nodes and missing or ambiguous current grants deny new execution. Duplicate held execution identity or aggregate overspend rejects intent preparation. An unavailable selected-host quiescence probe retains every hold in the group. Corrupt state/frontier/resource totals fail closed. Ordinary capacity shrink does not erase holds or become a fabricated zero observation.

A committed execution intent is not proof of process start or completion. Parent exit, missing PID and a successful signal are not full containment quiescence receipts.

## 10. Capacity and performance profile

Source ceilings include 256 hosts/nodes where specified, 4,096 local candidates, 16,384 simultaneous grants, 32,768 terminal records and execution holds where specified, 16,384 operation receipts and eight retained generations. These are bounds, not selected-host performance or filesystem durability measurements.

Bounded one-Agent registration reads and removal of a redundant admission metrics reload avoid unnecessary work. Synchronous owner/final-use I/O, maintenance scheduling, lock contention and long-backlog recovery remain measurement and optimization tasks. No fully nonblocking lifecycle or sustained-latency target is claimed from the local checks.

## 11. Security controls and their boundary

Controls include independent trust roots, physical bounded profiles, current signed revocation state, owner time, no request-supplied capacity, single named writer, independently bound registered execution requirements, versioned byte framing, durable intent and no release on ambiguous process evidence.

These controls do not prove kernel resource enforcement, executable-file identity, complete descendant containment or successful restart cleanup. The raw driver's identity check remains required on adoption. A shutdown-only recovery path must not gain new execution authority. Missing product controls remain blockers, not implicit guarantees supplied by the documentation.

## 12. Observability

Read-only snapshot status exposes persisted grant/host/reservation facts and snapshot-derived diagnostics. Another process's volatile counters are explicitly unavailable/null, not zero. Missing/corrupt/unsealed state and invalid CLI arguments fail rather than returning healthy empty Fleet state. Unsupported preflight, dry-run, mutation and Prometheus modes are not presented as implemented services.

`OPERATIONS.md` retains the operational metric vocabulary and thresholds while distinguishing persisted facts from live-owner diagnostics. It contains the supported JSON status commands and references the executable CLI regression sources. Source availability is not a final-candidate test result.

## 13. Rollback and migration

Source rollback may restore a compatible binary, but durable Fleet state must not be rolled back by deleting generations, lowering the frontier or deleting execution pins. A predecessor binary that does not understand the current state/frontier must not become owner. Restore requires authenticated backup and a migration preserving generation/digest lineage.

Already running legacy processes without matching durable intent are not silently adopted by manufacturing an intent. Migration must establish their actual scope and authority, stop/reconcile them through approved ownership where required, and then use normal admission. The current delivery does not claim that complete migration/recovery acceptance has occurred.

## 14. Qualification commands and identities

The focused qualifier retains:

```text
cargo fmt --all -- --check
cargo test --locked -p codex-hepta-fleet --all-targets
cargo test --locked -p codex-hepta-supervisor --all-targets
cargo check --locked -p codex-hepta-supervisor --bin hepta-supervisord
cargo clippy --locked --no-deps -p codex-hepta-fleet --all-targets --all-features -- -D warnings
cargo clippy --locked --no-deps -p codex-hepta-supervisor --all-targets --all-features -- -D warnings
```

`python3 -B -m unittest discover -s scripts -p test_runtime_fleet_qualify.py -v` tests the qualification mechanism separately. Its success does not stand in for the commands above.

Exact qualification requires the declared immutable source HEAD/tree. Synthetic qualification additionally requires ordered base/source parents and a tested tree equal to `git merge-tree --write-tree` for those commits. The qualifier validates clean candidate identity before, between and after commands, retains a complete tracked source archive and binds command exits/logs/archive/receipt digests to runner/workflow provenance. Candidate/infrastructure failures remain non-passing outcomes. Evidence lives outside source in a new attempt directory; no qualification command repairs or pushes source.

A queued, cancelled, historical or different-SHA workflow is not acceptance. Protected target-host execution is a separate gate. The current-state source anchor and this document's date cannot substitute for final execution receipts.

## 15. Completion statement

This delivery contains pushed source repairs, updated documentation and explicitly scoped local validation. It does not close complete product source composition, actual process containment/reclamation, stop-only crash recovery or final-candidate Cargo/merge qualification. `CURRENT_STATE.json` keeps those dimensions separate and unproved; independent acceptance, deployment and release remain false.
