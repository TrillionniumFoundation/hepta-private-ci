# Process ownership during failed launch publication

This guide supplements `TECHNICAL.md` and `PROCESS_LIFETIME.md`. It describes
source implementation, not successful native execution or deployment approval.
The existing Supervisor remains the lifecycle owner. No new durable writer,
production grant, key source, acceptance authority or CI exception is introduced.

The source-only observations below belong to their original repair checkpoints.
Subsequent native outcomes are recorded in the
[R3 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R3.json)
and [R4 local observation](../../../qualification/runtime-supervisor/LOCAL_EXECUTION_OBSERVATION_20261001_R4.json),
with candidate scope and remaining gates in the
[R4 audit](../../../qualification/runtime-supervisor/ADVERSARIAL_AUDIT_20261001_R4.md).
An observation applies only to its bound source and selected commands; it does
not certify a later candidate, an unfiltered suite or target-host acceptance.

## Main Agent launch

`start_release_slot` installs the exact spawned handle in the per-Agent slot
before publishing the process lease. Publication success installs the selected
release metadata. Publication failure instead invalidates readiness, fences the
retained process, clears transient restart/control scheduling and attempts a
hard kill. A failed signal retains Stopping with an immediate deadline; only a
successful signal records Killing/KillRequested. A failed lifecycle CAS records
its fault but does not erase ownership or replace the original publication error.

The previous selected release and command remain unchanged on publication
failure. A retained runtime blocks a second launch. Killing is not Exited: the
handle and any exact partially published lease survive until exit is observed.

Already-fenced runtime polling attempts termination before registry reads and
before process polling. A failed signal does not suppress an exit observation;
a failed probe does not suppress the preceding termination attempt. This also
applies to the existing adopted-release rejection path. Ordinary unfenced
admission still uses live full-Fleet generation validation. The existing-deadline
continuation below is limited to exact already owned incarnations with an
expired Draining/Stopping phase, an admitted due Drain/Stop request or an
admitted pending Kill.

## Same-owner cleanup witness

Normal `ProcessLeaseRemoval::new` still rejects an initially absent lease.
`for_failed_publication` is a different private constructor, used immediately by
the owner that retained the freshly spawned handle across its own publication
failure. It binds the same path and complete expected lease. Only that local
witness permits an initially absent publication outcome after observed exit.

An exact partially published lease can be unlinked. A different or malformed
lease rejects. After unlink or the first absent-path sync attempt, reappearance
of any lease rejects, even if its contents match. The same witness can retry
failed directory sync and later lifecycle CAS; a new ordinary witness cannot
infer previous cleanup from absence. The witness is not serialized or recovered
from an absent path and is not cross-daemon/power-loss evidence.

If the initial Starting -> Failed CAS failed, finalization retries that exact
Starting generation after observing exit. It never overwrites a newer registry
generation. Only after cleanup and the necessary transition succeed does the
owner emit Exited and release the retained handle.

## Matrix companion

Matrix launch computes fallible deadlines before spawn, installs the acquired
handle before publication, and retains a failed publication under a private
same-owner Matrix lease-removal witness. A mismatched but exactly adopted
companion is fenced and retained; a kill acknowledgement no longer deletes its
lease or discards its handle. Recovery now installs the exact driver-proven
process before validating the current binding/release. Missing, corrupt or stale
binding/release metadata prevents serving, but cannot drop the acquired handle.
The original OS-lifetime and handshake proof is not weakened.

Matrix fencing invalidates readiness before a signal is attempted. A failed kill
remains retryable even if the main Agent later looks healthy. Fenced companions
cannot regain readiness from a later probe. Polling still observes exit after a
failed signal. After one exact exit, only durable cleanup is retried; a failed
sync does not cause repeated signaling or polling. Normal missing leases reject;
only a retained failed-publication witness allows initial absence. Changed,
corrupt or reappearing leases do not authorize cleanup.

The Matrix tick's direct fencing/kill error is retained if a later poll,
complete Fleet read or exact lease cleanup also fails. Every owning tick branch
passes the same report, preserving the original signal fault once beside the
later unresolved fault; a primary signal error is not duplicated. Real exit
with successful exact cleanup keeps the existing terminal contract. If cleanup
fails after that exit is stored, the next tick retries only cleanup and retains
the owner, without another signal or poll. This also applies to preceding
containment callers after a main-generation fence: `kill_matrix_now` marks
unhealthy/fenced and returns for a stored exit without a signal, Killing-phase
transition or MatrixKillRequested event. Two
`supervisor::tests::tick_control_fault_tests::matrix_fault_tests` cases in
`tick_matrix_fault_tests.rs` use real lease files and explicit process-driver
outcomes to cover combined poll faults and failed cleanup; source presence is
not a native execution receipt.

## Rejected identity is not process absence

`Adoption::Rejected` retains both the main and Matrix process leases. It does
not signal the unproven process and does not reconcile a durable termination
intent as completed. The main lifecycle may become Failed and the existing
OrphanRejected event is retained; this event is not evidence of process exit.
For compatibility, identity rejection alone is reported by that event rather
than changing the legacy TickReport contract. The retained lease is the
replacement fence, not the event buffer.

Before starting a main generation, the owner now checks for both an in-memory
Matrix owner and an unresolved Matrix lease. Either blocks replacement. The
normal Matrix start path already rejects an unresolved Matrix lease.

Read-view publication separately checks physical lease presence against the
captured owner handles. An unowned main/Matrix lease, or a fenced main runtime,
prevents ready=true. A failed lease read invalidates publication through the
existing error path. This is a read-only observation, not an authority token or
a new mutation gate, and retains the existing two-second cache freshness bound.
It does not promise that every unrelated readiness or quarantine condition is
covered, nor replace final-use control validation.

## Failure-domain separation

Explicit Kill collects main and companion results independently. It attempts the
main signal before entering the companion driver. The initial registry read is
now a collected error, not a question-mark early return. Main registry/CAS failure
fences the already-owned process and still attempts both terminations, while
returning failure rather than claiming durable completion. Generation fencing
also invalidates serving state before attempting main then companion signals.
Within recover_slot, the main and Matrix recovery attempts are evaluated
independently before either result is returned. Main release conversion, control
journal parsing, driver and lifecycle failures therefore do not skip Matrix
ownership recovery. If both fail, the main error remains primary and a bounded
Matrix diagnostic is retained. These synchronous operations do not establish
per-Agent latency isolation or a deadline guarantee under stuck kernel/filesystem calls.

Agentd Health/Drain and Matrix Health exchanges now share one 200 ms monotonic
transport deadline across nonblocking connect, exact kernel peer validation,
partial write and bounded read. The peer is validated before request bytes;
partial progress cannot renew the deadline. Probe failure clears the worker's
health flag through its existing failure path. A missing, timed-out or
incomplete Drain reply never proves drain completion or process exit and cannot
release an owned handle. Durable Stop/cleanup semantics remain unchanged. This
transport bound does not make kernel path lookup or filesystem calls
preemptible, nor establish per-Agent latency isolation.

## Regression source

`recovery::launch_tests` contains four filesystem-backed tests with an explicit
process-driver double: failed publication plus kill/probe failures, exact partial
publication, foreign-lease rejection, and failed initial CAS/registry reads.
`lease::removal::unpublished_tests` contains three filesystem tests: normal
absence rejection, failed-sync/reappearance rejection, and same-owner unlink
retry. The existing Matrix tick fixture is extended by eight containment tests;
four additional Matrix cleanup tests exercise the filesystem witness directly.
These nineteen functions were the original ownership repair's source inventory;
that checkpoint had no native execution. They use explicit process doubles or
filesystem fixtures and are not real-child or target-host receipts. Subsequent
native outcomes are bound separately in the observations above. The five
actual-process lifetime sources are described in `PROCESS_LIFETIME.md`.

Run both library profiles and the product qualification, not just these slices:

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::launch_tests
just test --locked -p codex-hepta-supervisor --lib lease::removal::unpublished_tests
just test --locked -p codex-hepta-supervisor --lib matrix::tick::tests::containment
just test --locked -p codex-hepta-supervisor --lib matrix::lease_removal::tests
```

## Paired recovery regression source

`recovery_ownership_tests.rs`, included as `recovery::ownership_tests`, adds ten
filesystem-backed regression functions with explicit injected process outcomes:

| Test boundary | Required observation |
| --- | --- |
| Rejected main identity | Original lease and unresolved control intent remain; no signal or spawn |
| Rejected Matrix identity | Original lease remains and blocks main replacement; no signal |
| Main release rejection and failed kills | Both acquired owners and leases remain |
| Main control parse failure | Matrix still reaches exact driver adoption/containment |
| Main driver failure | Matrix still reaches exact driver adoption/containment |
| Invalid Matrix binding | Validation occurs after ownership acquisition; failed kill retains owner |
| Kill acknowledgement followed by exit | Lease is retained before exit and finalized only after observation |
| Proven missing Matrix | Distinct absence disposition permits exact lease cleanup |
| Repeated Matrix recovery | Existing retained owner is not replaced |
| Rejected ownership readiness | Persisted unowned lease prevents ready=true |

The existing
`matrix::tick::tests::containment::failed_registry_preparation_preserves_and_terminates_both_owned_handles`
regression covers the emergency Kill ordering repair. It is not disabled or
replaced by a source-text assertion.

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::ownership_tests
just test --locked -p codex-hepta-supervisor --lib matrix::tick::tests::containment
```

At the original paired-recovery repair checkpoint, these commands had not been
executed and that editing environment had no Rust compiler, Cargo or rustfmt.
Its source blob and patch-roundtrip checks established source-delivery integrity
only. Subsequent native outcomes are recorded in the observations above.
Complete default/production product tests, strict lint and format checks on the
actual final source and ordered-parent merge remain mandatory.

## Main admission after identity acquisition

`recovery_admission.rs` separates semantic admission from the driver's exact
process acquisition. Lease/lifecycle relationship checks, control-intent parsing,
control-target binding and deadline construction are evaluated without granting
serving or signal authority. A failed result is retained until the driver has
independently proved whether it owns the process. Only `Adoption::Adopted`
supplies a signal-capable handle; Missing/Rejected do not acquire one.

An acquired main process is installed before a rejected result is propagated.
Rejection invalidates health, fences the exact retained process, clears local
scheduling and attempts termination. A failed kill retains the handle and lease
for existing tick/finalization. A successful kill is not an exit or permission
to remove the lease. Corrupt control evidence is not erased because a separate
process probe returned Missing. The paired recovery path still attempts Matrix
recovery even when main admission fails.

This closes the post-decode main lease/control/deadline admission boundary.
The constructor now attempts independent lease-bound main and Matrix acquisition
even when semantic preparation fails; a release hydration error cannot suppress
that ownership attempt. Unreadable/undecodable lease bytes still cannot supply a
process identity or authorize a signal.

## Deferred empty constructor hydration

`constructor_hydration.rs` may retain a constructor-local observation only for
a Stopped generation-zero Agent with a generation-zero empty release state.
Its slot must have no main/Matrix owner, recovery blocker, pending control,
restart, release, cleanup or signed state. Both run parents must be physical
directories; both process leases and all control, restart, release and signed
witnesses must be absent. A symlink, FIFO, missing parent or inspection error
is not absence. Initial semantic preparation and independent lease-bound main
and Matrix recovery remain in their original order.

The observation skips only a duplicate pure metadata hydration. It retains the
first complete Agent record, cannot overwrite that record on re-observation,
and is bounded to 256 Agents. `constructor_recovery.rs` settles every nonempty
observation with one fresh complete Fleet read, whole-record equality and new
witness checks. A release CAS that advances an empty release generation is
therefore detected even though it creates no run witness. Corruption in an
unrelated Agent still fails complete Fleet validation.

An observed slot whose record or evidence changed re-enters fresh original
recovery while still empty. If it has since acquired an owner, pending work or
a denial, settlement retains the exact handles and denies serving instead of
replaying adoption over them. A final Fleet read failure similarly reports
faults and denies observed slots without returning an error that would drop
the recovered Supervisor and its other owners. Control admission, ordinary tick
and release selection never consume this observation. The repeated reads and
absence checks are not an atomic multiwriter transaction or a replacement for
the required production recovery-observation envelope.

`supervisor::constructor_hydration::tests` uses real Fleet records and file
changes to cover release-generation drift, unrelated corruption, missing
Agents, each new durable witness and unsafe parent/file types.
`constructor_hydration_recovery_tests.rs` exercises the actual settlement and
denial orchestration with real Fleet files and the existing explicit process
driver doubles: final-read failure retains both owners, changed observations do
not re-adopt an owned pair, generation-only drift takes fresh recovery, and new
corrupt signed evidence denies recovery. These are named mandatory library
cases in the current CI plan. They are not real-child or target-host receipts.
Their source presence does not
establish current-head execution or startup latency. The source-counted empty
256-Agent reduction and its limits are recorded in `TECHNICAL.md`.

## Stop/Kill completion and restart cancellation cuts

The existing two owner records retain their formats and authority. Before an
unresolved Stop/Kill can be marked Completed from the existing absence/lifecycle
checks, `reconcile_absent` durably cancels the main restart in the canonical
shared restart record. Attempt count, window origin, eligibility history and
the companion restart domain remain intact. Cancellation failure leaves the
control unresolved. A crash after cancellation but before terminal publication
retries cancellation idempotently; terminal replay does not cancel a later,
separately authorized restart.

Recovery also cancels restart from an unresolved Agent-bound termination before
restoring the pending restart claim. A new explicit restart rejects while that
termination is unresolved. A stopped/failed Agent with neither owned nor leased
main/Matrix processes and no pending release transition may cancel a queued
restart without constructing a fictitious process identity. Unowned leases and
release-transition supersession do not take this idle shortcut.

Live Stop continuation reuses the original durable deadline after Matrix
deferral instead of allocating another stop_grace. Once the deadline has expired,
main termination is attempted first and Matrix termination is attempted separately;
a failing companion cannot prevent the preceding main kill. This does not yet
persist restart-internal drain deadlines or a durable Matrix quarantine.

A live Stop first checks the supplied monotonic `now + stop_grace` before
publishing its durable intent. Private Fresh/Retained preparation changes no
schema or digest: only Fresh stages that exact deadline, and only after durable
restart cancellation succeeds. Failed cancellation leaves the durable intent
retained without a new pending control, StopRequested marker or signal.
Retained pending/acknowledged Stop keeps its earlier monotonic limit and cannot
downgrade Kill. Continuation still validates current journal digest and exact
process target and rejects Stop wall-clock rollback. Only restoration with no
in-process Stop/Kill continuation reconstructs a deadline from durable wall time.

An unexpired same-spawn pending Stop with an exact deferred Stop and owned
Matrix does not bypass companion-first deferral to signal the main early.
Otherwise eligible startup/Running health remains observable during this grace
so that deferral alone does not trigger emergency Matrix Kill. At the original
deadline, main containment remains first. Tick captures its control continuation
before pending may clear; it cannot regain serving from that tick's probe, and
Stopping/Killing remains unready on subsequent successful live probes. The
Draining observation policy is unchanged.

A successful driver Drain/Stop call clears its pending retry, not the deadline
of the acknowledged Draining/Stopping phase. Repeated poll errors or an
unrelated Agent's corrupt Fleet manifest previously prevented the later expiry
branch from running. A corrupt full-Fleet read could also block an already
admitted pending request after its first signal failed. An expired, unfenced
phase, an admitted current-spawn pending Drain/Stop whose deadline is due, or
an admitted current-spawn pending Kill now permits only containment bound to
the exact retained main incarnation before registry observation and polling.
Stale or fenced pending requests grant no such continuation; not-yet-due
Drain/Stop remains behind full Fleet validation. The same tick reuses its
pre-read signal result for an unchanged generation. Drain escalation keeps
`drain_deadline + stop_grace`; a delayed tick does not allocate a new grace.
An already expired total budget can proceed directly to Kill.
A same-incarnation pending Kill remains
dominant.

Recovery validates the representability of its supplied
`now + drain_timeout + stop_grace` before acquiring process handles.
`drain_slot` repeats the checked total at the actual invocation time before
deferral, fencing, CAS or signaling. An overflow rejects the operation; it is
not an elapsed budget and cannot authorize immediate Kill.

An exact `observed_exit` remains the first branch: only finalization is retried,
without another signal or poll. Observed signal, registry and poll faults are
retained independently once on unresolved paths. Signal delivery never supplies
a DrainAck, exit or cleanup proof, and the exact owner and lease survive until
real exit and durable finalization. Ordinary admission and not-yet-due Drain/Stop retain
complete Fleet validation. This continuation changes no lease identity,
durable record format, Matrix ownership or cross-daemon exit-cleanup contract.

Five `supervisor::tests::tick_control_fault_tests::deadline_tests` functions in
`tick_control_deadline_tests.rs` exercise acknowledged Drain/Stop with repeated
poll faults, combined signal/poll failure, stronger pending Kill and unrelated
Fleet corruption. They use real Fleet files and explicit process-driver
doubles, with owner/lease retention assertions. Two child
`deadline_tests::budget_tests` cases in `tick_control_budget_tests.rs` verify
overflow rejection before any recovery acquisition and before Drain side
effects, preserving the complete Agent record, snapshot, raw lease and driver
counts. Four `tick_control_fault_tests::pending_deadline_tests` functions in
`tick_pending_deadline_tests.rs` exercise first-signal failures for Drain, Stop
and Kill against a real corrupt unrelated Fleet manifest, original deadlines,
and stale-spawn rejection. The added
`fresh_stop_retains_monotonic_deadline_while_matrix_defers_main_control` uses
two retained owners and real main/Matrix leases to cover deferral/retry, no early
signal, exact deadline, terminal-phase readiness and cleanup. These use explicit
process-driver doubles.
Test source is not actual-child, current-head or target-host execution evidence.

## Control-intent file boundary

The unchanged V1 control-intent codec now reads at most 8,193 bytes from an
opened descriptor and rejects an input exceeding its 8,192-byte bound. Unix
opens use NOFOLLOW/NONBLOCK/CLOEXEC and validate regular-file type, effective
owner, single link, non-writable group/world mode and path/descriptor stability.
FIFO, symlink, multiply linked and replaced final components reject. New intent
files are created owner-private. Parent-directory substitution, authenticated
backup rollback and cross-record transaction integrity remain separate concerns.

## Signed publication effect boundary

Signature, catalog, preflight and digest-bound status construction precede the
first durable publication attempt in signed grant application. Signed recovery
also verifies the decision, frontier, outcome and replay before terminal
transaction publication. Those pre-publication refusals remain safe rejection.
After the first publication attempt, failed publication, acknowledgement or
continuation returns `SignedMutationIndeterminate`, surfaced as
`operation_indeterminate` by the signed RPC handlers. This is true even if no
process delivery has been confirmed: possibly published bytes cannot be treated
as absent because their durability acknowledgement failed.

The same lifecycle owner retains trusted RecoveryRequired intent and bounded
original diagnostics without discarding exact process handles or leases.
Grant application makes a best-effort durable recovery-marker write; its failure
still leaves in-memory quarantine. Recovery preserves possibly published
terminal records for the same signed decision's retry, rather than overwriting
them with a recovery marker. Both terminal acknowledgements and the revision
update must succeed before quarantine is released. Failure leaves the recovery
revision unchanged; exact successful retry increments once. An indeterminate
error is neither a physical-effect receipt nor authority/operator acceptance,
and supplies no exit or cleanup proof.

A Prepared intent can be quarantined before any release transaction exists.
The supported signed recovery API requires an exact transaction and its
decision-bound digest, so it cannot terminalize this no-journal case. The
legacy offline abort writes a digest-only directive with no production
consumer; it cannot produce Aborted or authorize reuse after process exit.
This pre-existing crash cut remains blocked until a separately designed and
authorized recovery protocol exists. Do not fabricate a transaction or delete
the intent to bypass this boundary.

Three `daemon::authority_tests::effect_boundary_tests` functions in
`signed_effect_boundary_tests.rs` exercise pure rejection and real signed-intent
publication faults before and after driver Drain delivery. The existing
`supervisor::tests::release_retry_tests::signed_recovery` source-restoration
case in `release_signed_recovery_tests.rs` adds terminal transaction/intent
fault cuts and exact decision retries. They use real durable files and explicit
process-driver doubles, not actual target-host or current-head execution receipts.

## Public authority-bundle input boundary

Startup captures regular-file metadata for the pinned public authority bundle
and opens its final component with Unix NOFOLLOW/NONBLOCK/CLOEXEC. A FIFO
substituted after the metadata check therefore cannot wait for a writer before
descriptor validation. The descriptor must be regular, bounded, unchanged in
device/inode, effective-user owned, single-link and private to that user before
the bounded read. There is no after-read metadata recheck. Canonical and external
pinned digests still validate the read bytes before verifier construction;
protected parent directories and external provisioning remain requirements.
This reader changes no process, lease, grant or recovery ownership.

The Unix `authority_bundle::open_tests` regression in
`authority_bundle_open_tests.rs` uses real regular-file-to-FIFO replacement and
must reject before its old-path watchdog releases a blocked open. It is source
coverage rather than a native execution or deployment receipt.

## Regular-file and parent-directory I/O

Supervisor's private regular-file reader checks opened type and existing bounds
before maximum-plus-one reads. Matrix binding uses 64 KiB and compares the
opened inode with prior metadata; external signer request paths retain 8 MiB;
the three final-use seed tools retain exactly 32 bytes plus effective-user,
private-mode, single-link and Zeroizing checks. The bundle-construction CLI
public-key reader has an 8 KiB input bound and keeps absolute-path,
32-raw-byte/64-trimmed-hex validation. Stdin and explicit key-fd stream semantics
remain unchanged. Unix NOFOLLOW/NONBLOCK/CLOEXEC prevents special-file open
waits without granting new authority.

Fleet's independent private reader uses captured file length for registry and
lifecycle text and the existing 32 KiB bounds for release JSON/frontier input.
Copy/hash reads at most captured length plus one and rejects a final length
different from the original, without adding a binary-size ceiling. Opened
regular type/size/inode checks supplement full global catalog, canonical,
immutable mode, digest/seal and CAS validation. The dependency edge is only
existing workspace `libc` on Unix, with no version change. Its two actual
registry/catalog FIFO source tests carry no platform-pass credit here.

Durable journal publication, main lease sync, Matrix cleanup and bundle CLI
parent sync use a shared Unix directory open with O_DIRECTORY/NOFOLLOW/NONBLOCK/
CLOEXEC, descriptor-directory validation and `sync_all`; Fleet applies the
same pattern privately. Existing durability hooks/errors and Windows behavior
remain. A real directory-to-FIFO replacement regression rejects before a
watchdog release. No failed sync releases the exact owner, manufactures cleanup
or proves parent-inode binding. Regular storage and ancestor integrity remain
host prerequisites; this adds no preemption or latency SLO.

## Added regression source and execution boundary

Eight `recovery::admission_tests` functions exercise retained ownership after
corrupt or mismatched control, invalid lifecycle distance, failing deadline
construction, signal retry and repeated containment. Fifteen
`control_intent::completion_tests` functions cover cancellation/terminal crash
cuts, companion/history preservation, failure/retry, later-restart independence,
lease/Agent rejection, bounded file inputs, idle cancellation, live original Stop
deadlines, main-before-Matrix escalation and unresolved-control restart denial.
Two of those fifteen functions are Unix-only file-boundary tests.

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::admission_tests
just test --locked -p codex-hepta-supervisor --lib control_intent::completion_tests
just test --locked -p codex-hepta-supervisor --lib
just test --locked -p codex-hepta-supervisor --features production-authority --lib
```

These 23 functions were the added source inventory at a checkpoint without
Rust/Cargo/rustfmt, rather than passing execution evidence from that checkpoint.
Source-byte and patch checks were not native compilation, formatting, Clippy,
product or selected-host evidence. The observations above record later native
outcomes and their limits. Full default/production/product/source/merge gates
remain mandatory for the final candidate.
No workflow, receipt requirement or branch protection is relaxed.

## Still requiring implementation or qualification

Post-acquisition driver initialization failures now retain acquired handles in
`unix_initialization.rs`; execution evidence must be matched to the candidate.
The constructor acquisition, durable operator intent, original Stop deadline and
limited idle-cancellation paths described above supersede the original repair's
open-item list. Undecodable lease identity, daemon death before a recoverable
launch record, directory-inode replacement, complete release/control supersession
and predecessor/replacement crash coverage, restart-internal cross-daemon
deadlines and durable exit-cleanup witnesses remain separate gaps. Unresolved
owners never qualify for the idle-cancellation shortcut.
Matrix recovery now owns a successfully proven child before semantic hydration;
this does not establish a durable main-fault Matrix quarantine across reopen.
An earlier prepared Stage A+B transformation was not execution or acceptance
evidence. Current `restart_lineage.rs` remains partial under
`CAPABILITY_STATUS.json`; local launch/cleanup witnesses do not close the
cross-daemon requirement. Matrix stop retry/deadline semantics must also be
qualified independently from the fenced hard-kill path.

Current exact-head/source-merge Rust, formatting, strict lint and full product
receipts remain mandatory. Named Linux/macOS artifact-bound fault/load runs,
256 real instances and independent security/operator acceptance remain unproved.
