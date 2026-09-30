# runtime.supervisor adversarial audit — 2026-10-01

## Candidate and scope

The audit starts from `e8f8f2d0ca399b0a68abba4da90a3be5114d0735`
(`codex/runtime-supervisor-six-phase-closure-20260930-r4`). This is a descendant
of the full-qualification and lifecycle-evidence branches. `main` was older;
reviewing only `main` would miss the current owner, process-lifetime, restart
cancellation, read-projection and verifier-bundle implementation.

Review covers the native supervisor, daemon dispatch and wire bounds, durable
restart and release transitions, qualification receipts, source materialization
and current technical documentation. Failure cases include daemon death between
durable writes, retry after filesystem failure, blocking-pool exhaustion, a full
256-Agent response and substitution of historical evidence for a current build.

The repaired native source is pinned to
`348b24673c3f2f7e5d3e8d3bd5229620e170b0f5`, tree
`d1bb7f6eeff365eed351a931d088351fcf7b9dec`. Subsequent audit/map metadata
commits preserve those observed source blobs.

This is a repository audit and repair record. It does not provide independent
operational acceptance, target-host deployment evidence, activation or release.

## Documentation and project role

Detailed technical development documentation exists. The primary entry point is
`docs/modules/runtime.supervisor/TECHNICAL.md`, supplemented by
`PROCESS_OWNERSHIP.md`, `PROCESS_LIFETIME.md`, `OWNER_AND_READ_ISOLATION.md`,
`RECOVERY_AND_QUALIFICATION.md`, `PRODUCTION_CONTROL_RUNBOOK.md`,
`PRODUCTION_BOUNDARY.md`, the qualification profiles and implementation map.
The machine-readable capability matrix and generated current status distinguish
source presence from executed qualification and production acceptance.

`runtime.supervisor` is the lifecycle execution plant. It starts, observes,
drains, stops, kills and replaces generation-fenced processes. Fleet supplies
immutable release bytes and current allow/revoke admission facts; Agentd owns
turn/RPC admission and drain acknowledgement. Kernel authority and operations
remain the authority and operation-truth boundaries. Supervisor readiness is
neither user-task success nor permission to invoke models, tools or secrets.

Optimization therefore prioritizes preserving lifecycle ownership through
failure, making retries recoverable, keeping observation independent of the
single writer, and proving that qualification refers to the actual candidate.
Per-Agent writer partitioning requires measured target-host latency and explicit
Fleet/CAS ordering; source-level throughput speculation is insufficient.

## Findings and repair obligations

| Priority | Failure trace | Required repair |
| --- | --- | --- |
| P1 | A healthy replacement reaches durable `Running` before restart lineage/budget completion; recovery clears the local pending flag and no later healthy tick completes the durable remainder. | Retry completion from the exact replacement identity while Running; never complete a predecessor as the replacement. |
| P1 | Restart intent is durable but daemon death precedes predecessor drain/stop; recovery adopts the healthy predecessor without resuming retirement. | Restage generation-bound predecessor control from durable restart lineage and retain ownership across signal failure. |
| P1 | Release health handling removes its pending transition before release-state CAS/journal completion; a transient write failure loses the continuation. | Retain the transition until all required durable completion steps succeed and make retries idempotent. |
| P1 | Constructor recovery acquires exact main/Matrix owners, then a damaged journal aborts the whole constructor and drops those handles while processes remain live. | Return per-Agent recovery denial with retained owners; fence serving and retry exact containment/exit cleanup independently. |
| P1 | Exact bound control retry failures are classified as corrupted evidence, causing a second constructor Kill and losing the original Stop/Drain deadline. | Distinguish transient bound driver faults from damaged/admission evidence; retain the original control and still restore independent signed intent. |
| P1 | A rejected no-owner replacement spawn redispatches indefinitely under one charged restart claim; failed cancellation can leave an unacknowledged same-owner witness. | Cancel the exact charged operation, retain failed acknowledgement for writer retry and reject ordinary Start until it is settled. |
| P1 | No-main replacement dispatch returns UnresolvedLease before polling a live Matrix, starving its exact exit observation; ordinary Start can take over a pending release. | Poll the retained companion first, wait for exact exit/lease cleanup and deny public Start during the owned transition. |
| P1 | A valid `RecoveryRequired` intent denies daemon dispatch but direct public Start and lower tick paths can resume execution. | Enforce admission at the Supervisor API and automatic/Matrix continuation boundaries; preserve Stop/Kill containment and signed recovery. |
| P1 | Production Stop followed by Start selects another allowlisted release without a signed transition; a valid grant can bind an unregistered source fixture. | Bind Start to durable selected release and signed transitions to canonical catalog-admitted source commands. |
| P1 | Healthy publication overwrites an unrelated release CAS generation or recovery loses a revoked historical predecessor. | Compare the exact source frontier, permit only the exact idempotent next generation and preserve durable predecessor identity independently of executable admission. |
| P1 | An explicitly signed rollback fails at the target and restores its source, but signed completion recognizes only an Upgrade restoration. | Classify source restoration from an exact terminal transaction for either transition kind; do not leave the signed intent queued indefinitely. |
| P2 | Automatic rollback source launch fails and the following RecoveryRequired journal publication also fails; the continuation is removed and later ticks cannot settle it. | Retain the failed transition until durable outcome acknowledgement, without duplicate source spawn or premature failure events. |
| P2 | Release and signed journals use unbounded reads that can follow links or block on a FIFO. | Enforce bounded regular-file, ownership, permissions and named/opened identity checks before and after reading. |
| P1 | The owner executes in `spawn_blocking`, then waits for another resolver in the same pool; one blocking thread deadlocks owner/tick/shutdown. | Resolve Fleet/catalog data synchronously inside the already-offloaded owner. |
| P1 | A legal 256-Agent roster exceeds the 64 KiB request frame ceiling reused for replies, and the server drops the response. | Separate bounded request/reply ceilings and exercise the complete roster through the real socket/client. |
| P1 | A well-formed historical target receipt passes without matching the current checkout, workflow run or built binary. | Compare receipt identities to requested Git/run/OS/lockfile/artifact values at the workflow boundary. |
| P1 | Source materialization edits files before a later exact-marker failure; its followup does not match the generated indentation, and generated status overclaims unfinished capabilities. | Validate main and followup changes together before publication, support exact whitespace-aware blocks, preserve partial status and regenerate the status projection. |
| P2 | Every 40 Hz no-Matrix tick publishes an already empty Matrix restart budget, creating avoidable filesystem writes and surfacing irrelevant write faults. | Skip empty-budget publication; restore the exact prior budget/backoff state if a nonempty cleanup write fails and retry without changing the main claim. |
| P2 | Implementation-map callers point to obsolete functions, source objects omit active modules, and stale observations describe already repaired behavior. | Bind real product entry points and exact candidate blobs while retaining the historical provenance anchor and all unestablished production gates. |
| P2 | Product qualification still requires CLI test names removed by the pinned-bundle interface; suite enumeration omits `hol-256`. | Use current test identities in every lane and recognize numeric suite names. |
| P2 | Status validation accepts an overall implemented claim with unfinished capability rows or dormant source modules. | Reject contradictory claims and require the relevant implementation to be connected to the crate graph. |

## Completion assessment

The baseline capability inventory has 16 rows: 12 marked implemented, one
partial and three not implemented. These are source classifications, not a
75% production-completion score. A single missing crash/authority invariant can
block production irrespective of the number of implemented rows.

| Dimension | Assessment |
| --- | --- |
| Technical development documentation | Detailed; current claim matrix is substantially more cautious than some historical amendment documents. |
| Native lifecycle implementation | Substantial, with concrete retry, recovery and daemon-boundary defects addressed by this audit. |
| Newly added journal/witness/observation code | Files exist but baseline `lib.rs` does not compile or call them; presence cannot close runtime composition. |
| Repository qualification | Must execute against the repaired final candidate; older run success or source references are insufficient. |
| Target-host qualification | Not established by this audit; requires the frozen real-process, filesystem, fault and latency matrix. |
| Independent acceptance | Not obtained; code, security and operations acceptance must remain distinct evidence. |
| Activation and release | False. |

Remaining implementation obligations include cross-daemon exit finalization,
the launch-before-lease ownership boundary, complete predecessor/replacement
lineage and the normative atomic production-recovery observation. The dormant
observation payload does not bind all required Matrix, release/admission,
control/transaction, authority-bundle, sequence and expiry facts; merely wiring
it into `lib.rs` cannot establish the production gate. Incremental per-Agent
projection is a measured-performance followup rather than evidence of broken
lifecycle authority.

The receipt validator can enforce declared identities and distinct reviewers,
but establishing reviewer independence and private-key custody still needs
trusted external audit material. Cross-platform binaries have distinct digests;
production acceptance must bind the digest of each host artifact.

## Verification

Local verification completed:

- Mandatory `just fmt`: passed; unrelated formatting was excluded from the audit commits.
- `just fix -p codex-hepta-supervisor`: passed before the final lifecycle and
  Matrix cleanup changes. It is not a strict `-D warnings` result.
- Default and `qualification,offline-authority-tools` all-target checks passed
  at earlier repair checkpoints. These checks do not qualify later changes.
- Final default native library regression: **287/287 selected tests passed**
  from a 295-test inventory. Eight Unix-socket tests were externally excluded
  by the nextest expression after this environment returned `EPERM` for socket
  creation. The tests themselves were not disabled or rewritten to skip.
- Seven Python suites (receipt, evidence, status, workflow, CI and transactional
  materializer): **84 tests passed**. `hepta_supervisor_status.py check` passed.
- Isolated materialization from the immutable base and repeat execution:
  passed; marker/publication failure tests preserve original source bytes.
- `git diff --check`: passed.

The native regression includes exact-identity restart completion, predecessor
retirement recovery, repeated failed-spawn cancellation and directory-sync
acknowledgement, damaged-journal owner retention, transient control retry,
canonical signed source admission, release-frontier drift, revoked predecessor
identity, explicit-rollback source restoration, Matrix exit cleanup and failed
budget-clear retry. The no-Matrix test executes 40 ticks, verifies unchanged
budget bytes/mtime/inode, and proves an armed budget-write fault was not consumed.

The eight environmental exclusions are:

- `daemon::shutdown_tests::dropping_server_future_aborts_and_reaps_idle_connections`
- `daemon::shutdown_tests::shutdown_drains_accepted_connection_before_owner_can_be_replaced`
- `daemon::tests::unresolved_signed_intent_keeps_daemon_reachable_but_not_ready`
- `unix::drain_tests::malformed_or_wrong_generation_drain_frames_still_reject`
- `unix::drain_tests::missing_or_closed_socket_never_becomes_a_drain_acknowledgement`
- `unix::drain_tests::only_exact_closed_admission_with_no_running_turns_is_drained`
- `unix::tests::health_probe_requires_exact_agent_generation_pid_and_roots`
- `unix::tests::matrix_health_transport_rejects_response_larger_than_one_mib`

The initial local `just test --locked -p codex-hepta-supervisor` attempt failed
with filesystem `ENOSPC` before test execution. After reclaiming only unused
local build variants and disabling debug/incremental output, actual native tests
were built and run through `just test`/nextest. The first executed suite exposed
11 behavioral failures plus the eight environment failures; the behavioral
failures were repaired and the final selected suite passed. Failed or excluded
attempts are not pass evidence.

Final strict lint, all-target feature builds, the complete unfiltered Linux/macOS
product suite and exact source/merge qualification must come from the published
candidate's CI. Source-head execution does not substitute for the frozen
real-process target-host matrix or independent acceptance. A pending, skipped
or failed CI step is not qualified execution.

After the repairs, separate audit agents recheck the changed recovery, release,
daemon, evidence and materialization paths for new failure traces. A clean
review of that bounded diff is not a proof that no future optimization exists.
