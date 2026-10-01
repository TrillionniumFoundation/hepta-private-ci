# runtime.supervisor adversarial audit — 2026-09-30 to 2026-10-01 (UTC)

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
`69d2dba57f70fe5d1e095cee0bf69970b251ce56`, tree
`74356ef5b8411cd70c94982376a684f712e5e1a4`. Subsequent audit/map metadata
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
| P2 | HOL qualification holds a read projection guard while awaiting owner snapshots, introducing a read-to-owner lock dependency into the measured scenario; all-target strict lint also fails in valid fixture helpers and redundant CLI clones. | Copy the selected 64 IDs and release the read guard before owner awaits; document only function-local fixture panic expectations and remove equivalent redundant copies. |
| P2 | Implementation-map callers point to obsolete functions, source objects omit active modules, and stale observations describe already repaired behavior. | Bind real product entry points and exact candidate blobs while retaining the historical provenance anchor and all unestablished production gates. |
| P2 | Product qualification still requires CLI test names removed by the pinned-bundle interface; suite enumeration omits `hol-256`. | Use current test identities in every lane and recognize numeric suite names. |
| P2 | Status validation accepts an overall implemented claim with unfinished capability rows or dormant source modules. | Reject contradictory claims and require the relevant implementation to be connected to the crate graph. |

## Second adversarial pass

The published first-pass head `6ac309b73e8a196d7f4905e8e336b4cf5f682627`
was rechecked against the current branch and PR inventory. Its default native
library suite independently passed the same 287 selected cases before this
pass changed source. The first-pass exact-head and merge workflows still had
queued/pending jobs with no execution result at the next remote observation.

PR #1303 at `3491447b9856763514998360c077d71368a5498f` is a separate integration
alternative based on older `main`, rather than a descendant replacement for
this candidate. It adds hosting, module-selection and authority work but omits
existing constructor/retry repairs and cautious status documents. It was
compared read-only and was not merged. Its local model-authority private-key
reader/signer also needs an explicit separate ownership contract: the registered
supervisor still denies `secret_read`, model/tool authority and self-issued
grants. More source files do not resolve that role mismatch or supply acceptance.

| Priority | Additional failure trace | Repair |
| --- | --- | --- |
| P1 | A catalog-admitted release is revoked while Running; automatic restart dispatches its cached command without current admission. An absent catalog entry also lets a cached registered descriptor fall back to a local fixture. | Re-admit before every main launch; privately retain catalog origin and restrict catalog-free fallback to explicit nonproduction plant descriptors whose entry is physically absent. |
| P1 | A failed explicit rollback restores its source, but signed recovery recognizes only the rollback target. Constructor terminal reconciliation can also ignore external CAS generation drift. | Bind intent and transaction exactly, select the exact source or target generation/predecessor frontier, and share that classification with constructor reconciliation. |
| P1 | Recovery publishes its terminal transaction, then terminal intent publication fails. A same-owner retry rejects the already-terminal transaction and cannot finish acknowledgement without a restart. | Resume only the exact signed decision's terminal pair, reconstruct and verify its original journal bindings, retry acknowledgements without process effects, and avoid charging control revision twice. |
| P2 | A historical signed-intent status includes the digest of a later unrelated unsigned transaction. | Omit unrelated transaction digests instead of presenting mixed journals as one observation. |
| P1 | Lease/restart readers check a path then open/read it unbounded; a substituted link or FIFO can bypass the check or stall the owner. A successful lease publication can leave a staging hard link across a crash. | Use one bounded, nonblocking, nofollow descriptor reader with stable identity/owner/link/permission checks; publish 0600 leases and unlink staging before directory acknowledgement. |
| P1 | The client accepts an Agent-B snapshot for an Agent-A request or a mutation response with the wrong operation, prestate or signed receipt. Unexpected payload diagnostics can echo large authority-bearing data. | Validate each response against its request, verify the kernel peer before writing, cap canonical diagnostics and emit fixed payload-kind errors. |
| P2 | Robrix permits duplicate roster identities or health counts beyond the fleet limit; serving eligibility is confused with retained main/Matrix ownership during containment. | Enforce bounds/uniqueness and validate real unhealthy retained-owner states without granting readiness. |
| P2 | Periodic projection obtains a full snapshot, cloning log/event rings it never consumes. | Share a metadata-only snapshot builder; retain the complete public diagnostic snapshot and prove status/CAS parity with populated rings. The maximum avoided log-payload copy is a capacity bound, not a benchmark. |
| P1 | The validator plan runs real Python tests but has a zero-test minimum and no Python runner grammar, so receipt assembly rejects its truthful passing record. | Declare a positive source-bound unittest inventory and require a complete, ordered, all-pass verbose transcript; preserve separate nextest binary requirements. |
| P2 | A concurrent source edit after global preflight is overwritten by materialization; one rollback failure stops restoration of all remaining files and can obscure the original publication error. | Recheck file identity before each atomic leaf replacement, preserve externally substituted paths, attempt every restoration and report original error plus all incomplete rollback paths. |

Cross-review caught and repaired an invalid predecessor/terminal digest equality
in the new client validator: successful recovery changes journal digests. It
also caught serving-only assumptions that rejected real retained process owners.
The unchanged reply shape cannot authenticate a predecessor-to-terminal hash
transition by itself; exact signature/journal/frontier validation remains with
the daemon owner. This does not close the atomic recovery-observation capability.

Materialization remains an authoring transaction under trusted parent directories
and exclusive editing. Last identity checks detect observed conflicts; they are
not a filesystem-wide concurrency lock or a crash-durable multi-file commit.
The descriptor reader similarly protects the final Unix path component, not
untrusted ancestor directories. Target-host deployment must enforce those
ownership boundaries.

## Completion assessment

The baseline capability inventory has 16 rows: 12 marked implemented, one
partial and three not implemented. These are source classifications, not a
75% production-completion score. A single missing crash/authority invariant can
block production irrespective of the number of implemented rows.

| Dimension | Assessment |
| --- | --- |
| Technical development documentation | Detailed; current claim matrix is substantially more cautious than some historical amendment documents. |
| Native lifecycle implementation | Substantial, with concrete retry, recovery and daemon-boundary defects addressed by this audit. |
| Dormant exit/witness/atomic-observation prototypes | Files exist but current `lib.rs` does not compile or call those prototypes; presence cannot close runtime composition. |
| Repository qualification | Selected local library execution and strict compilation passed; unfiltered product and exact-head/merge CI remain unestablished. Older run success or source references are insufficient. |
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

Latest local verification completed. The unsigned
[`LOCAL_EXECUTION_OBSERVATION_20261001.json`](LOCAL_EXECUTION_OBSERVATION_20261001.json)
preserves the 131-file executed manifest, named passing inventory, exclusions and
final source comparison. It is a local observation, not a qualification receipt.

- Mandatory `just fmt`: passed; 46 unrelated formatter edits were excluded.
- Scoped `just fix -p codex-hepta-supervisor --locked --offline`: passed for
  default and `qualification,offline-authority-tools` configurations.
- Final strict Clippy: both configurations passed with
  `--locked --offline --all-targets --no-deps -- -D warnings`. This compiles
  the configured library, daemon, recovery CLIs and integration-test targets;
  it does not execute those integration targets. An existing `hepta-ndu`
  dependency deprecation warning remains outside the scoped result.
- Default native library: **323/323 selected tests passed**, total inventory
  331. `qualification,offline-authority-tools` library: **328/328 selected
  tests passed**, total inventory 336, including five additional durability
  qualification cases. Both ran through `just test`/nextest on the same frozen
  131-file native manifest; no source drift occurred between the two executions.
- Exactly eight Unix-socket cases were externally excluded after this environment
  had returned `EPERM` for socket creation. Their source was not disabled or
  rewritten to skip. This is not an unfiltered package or Linux/macOS product pass.
- Subsequent native changes were limited to three test fixture files: two
  automatic test-lint fixes, removal of an unfulfilled lint expectation, and
  formatting. All production native blobs still match the executed checkpoint.
  The final strict checks compiled that cleanup; native tests were not rerun
  after final `fix`/`fmt`, following `AGENTS.md`.
- Seven Python suites: **95 tests passed**. The actual six-module hosted
  validator command executed **65/65 named cases** and its complete transcript
  and truthful receipt were accepted. Ruff formatting preserved the ASTs of all
  six changed Python files. `hepta_supervisor_status.py check` passed.
- Isolated materialization from immutable base
  `e8f8f2d0ca399b0a68abba4da90a3be5114d0735` and identical repeat execution:
  passed, checking 420 files. Nine materializer regressions exercise marker,
  late conflict, substituted leaf, publication and incomplete rollback handling.
- The generated Robrix corpus has 72 cases; native parser/schema/fixture parity
  and independent manifest length/digest checks passed.
- `git diff --check`: passed.

The second pass's first native execution had 319 passes and four failures.
These exposed incorrect fixture assumptions: constructor rejection publishes
Failed, a terminal journal must bind the prepared CAS generation, a sealed
catalog removal must preserve directory permissions, and successfully contained
stale Matrix ownership returns no recovery fault. Fixtures now prove the actual
states, exact ownership/events, absent catalog entry and no extra dispatch.
Runtime checks and the eight environmental exclusions were not weakened.

Native coverage includes exact restart lineage/claim acknowledgement, constructor
owner retention, transient control retries, catalog re-admission before every
main launch, explicit rollback source restoration, exact prepared CAS generation
and predecessor, real signed recovery through eight writer fault cuts, expired/
changed/tampered decision denial, once-only revision, bounded descriptor reads
with deterministic file substitution, one-link lease durability, retained-owner
observations and metadata/CAS parity. The no-Matrix fixture still executes 40
idle ticks without consuming a budget write fault.

The earlier first-pass 287 selected default tests and 84 Python tests remain
historical checkpoints; they do not replace these newer results.

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

The complete unfiltered Linux/macOS product suite and exact source/merge
qualification still require the published candidate's CI. At the last remote
observation before publication, the first-pass PR jobs were queued and had no
execution result. The newly published source requires its own head/merge runs.
Source-head execution does not substitute for the frozen real-process target-host
matrix or independent acceptance. A pending, skipped
or failed CI step is not qualified execution.

After the repairs, separate audit agents rechecked the changed recovery, release,
daemon, evidence and materialization paths. The final cross-review found no new
reproducible failure in the repaired scope. This bounded result does not close
the explicitly listed implementation obligations or prove that no future
optimization exists.
