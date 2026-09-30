# Process ownership during failed launch publication

This guide supplements `TECHNICAL.md` and `PROCESS_LIFETIME.md`. It describes
source implementation, not successful native execution or deployment approval.
The existing Supervisor remains the lifecycle owner. No new durable writer,
production grant, key source, acceptance authority or CI exception is introduced.

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
control still uses live registry generation validation.

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

## Regression source

`recovery::launch_tests` contains four filesystem-backed tests with an explicit
process-driver double: failed publication plus kill/probe failures, exact partial
publication, foreign-lease rejection, and failed initial CAS/registry reads.
`lease::removal::unpublished_tests` contains three filesystem tests: normal
absence rejection, failed-sync/reappearance rejection, and same-owner unlink
retry. The existing Matrix tick fixture is extended by eight containment tests;
four additional Matrix cleanup tests exercise the filesystem witness directly.
All nineteen new ownership test functions use explicit process doubles or
filesystem fixtures. None has been compiled or executed in the editing
environment; none is a real-child or target-host receipt. They are separate from
the five actual-process lifetime Rust test sources in `PROCESS_LIFETIME.md`.

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

These commands and source tests have not been executed by this continuation.
The editing environment has no Rust compiler, Cargo or rustfmt. Exact source
blob checks and Git patch roundtrips establish only source-delivery integrity.
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
Unreadable/undecodable lease identity and the earlier `Supervisor::recover`
hydration path remain separate: no identity is invented from corrupt bytes.

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

## Control-intent file boundary

The unchanged V1 control-intent codec now reads at most 8,193 bytes from an
opened descriptor and rejects an input exceeding its 8,192-byte bound. Unix
opens use NOFOLLOW/NONBLOCK/CLOEXEC and validate regular-file type, effective
owner, single link, non-writable group/world mode and path/descriptor stability.
FIFO, symlink, multiply linked and replaced final components reject. New intent
files are created owner-private. Parent-directory substitution, authenticated
backup rollback and cross-record transaction integrity remain separate concerns.

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

These are 23 written Rust test functions, not 23 passing executions. The editing
environment did not have Rust/Cargo/rustfmt; source-byte and patch checks are not
native compilation, formatting, Clippy, product or selected-host evidence. The
full existing default/production/product/source/merge gates remain mandatory.
No workflow, receipt requirement or branch protection is relaxed.

## Still requiring implementation or qualification

Post-acquisition driver initialization failures now retain acquired handles in
`unix_initialization.rs`; their native regressions still require execution.
Hydration in `Supervisor::recover` before `recover_slot`, undecodable lease
identity, daemon death before a recoverable launch record, directory-inode
replacement, durable Stop/Kill release-change supersession and no-runtime paths
with unresolved owners, restart predecessor/replacement identity, restart-internal
cross-daemon deadlines and exit finalization remain separate gaps.
Matrix recovery now owns a successfully proven child before semantic hydration;
this does not establish a durable main-fault Matrix quarantine across reopen.
The previously prepared Stage A+B transformation is not source closure or an accepted v2
restart-lineage implementation. Its replacement-exit, original predecessor
control/deadline and durable Matrix-quarantine boundaries still require repair.
The local launch/cleanup witnesses do not close any cross-daemon requirement. Matrix stop retry/deadline semantics
must also be qualified independently from the fenced hard-kill path.

Current exact-head/source-merge Rust, formatting, strict lint and full product
receipts remain mandatory. Named Linux/macOS artifact-bound fault/load runs,
256 real instances and independent security/operator acceptance remain unproved.
