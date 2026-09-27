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
lease or discards its handle. Current binding/release validation before adoption
is still a separate recovery gap and is not relaxed by this change.

Matrix fencing invalidates readiness before a signal is attempted. A failed kill
remains retryable even if the main Agent later looks healthy. Fenced companions
cannot regain readiness from a later probe. Polling still observes exit after a
failed signal. After one exact exit, only durable cleanup is retried; a failed
sync does not cause repeated signaling or polling. Normal missing leases reject;
only a retained failed-publication witness allows initial absence. Changed,
corrupt or reappearing leases do not authorize cleanup.

## Failure-domain separation

Explicit Kill collects main and companion results independently. It attempts the
main signal before entering the companion driver. Main registry/CAS failure
fences the already-owned process and still attempts both terminations, while
returning failure rather than claiming durable completion. Generation fencing
also invalidates serving state before attempting main then companion signals.
Main tick failure still advances companion containment and retains a bounded
secondary fault. These synchronous operations do not establish per-Agent latency
isolation or a deadline guarantee under stuck kernel/filesystem calls.

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

## Still requiring implementation or qualification

Internal driver setup failures after OS spawn, pre-adoption hydration or
binding failures, rejected/unproven adoption lease disposition, daemon death
before a recoverable lease, directory-inode replacement, durable Stop/Kill
supersession, restart predecessor/replacement identity, cross-daemon deadlines
and exit finalization remain separate gaps. The local launch/cleanup witnesses
do not close any cross-daemon requirement. Matrix stop retry/deadline semantics
must also be qualified independently from the fenced hard-kill path.

Current exact-head/source-merge Rust, formatting, strict lint and full product
receipts remain mandatory. Named Linux/macOS artifact-bound fault/load runs,
256 real instances and independent security/operator acceptance remain unproved.
