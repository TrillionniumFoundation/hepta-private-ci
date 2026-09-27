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

## Failure-domain separation

Main tick failure still attempts companion containment and retains a bounded
secondary fault instead of discarding it. A generation-fence companion error
cannot prevent the subsequent main-process kill attempt. This change does not
yet repair every explicit Kill or Matrix launch/adoption path; those remaining
paths are listed below and must not be inferred complete from this main fix.

## Regression source

`recovery::launch_tests` contains four filesystem-backed tests with an explicit
process-driver double: failed publication plus kill/probe failures, exact partial
publication, foreign-lease rejection, and failed initial CAS/registry reads.
`lease::removal::unpublished_tests` contains three filesystem tests: normal
absence rejection, failed-sync/reappearance rejection, and same-owner unlink
retry. These seven test sources have not been compiled or executed in the
editing environment. They are not real-child or target-host fault receipts.

Run both library profiles and the product qualification, not just these slices:

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::launch_tests
just test --locked -p codex-hepta-supervisor --lib lease::removal::unpublished_tests
```

## Still requiring implementation or qualification

Matrix failed publication and mismatched adoption need the same retained-owner
semantics. Explicit Kill must attempt main termination despite a companion
error. Internal driver setup failures after OS spawn, pre-adoption hydration
failure, daemon death before a recoverable lease, directory-inode replacement,
durable Stop/Kill supersession, restart predecessor/replacement identity,
cross-daemon deadlines and exit finalization remain separate gaps. This local
launch witness does not close any of those cross-daemon requirements.

Current exact-head/source-merge Rust, formatting, strict lint and full product
receipts remain mandatory. Named Linux/macOS artifact-bound fault/load runs,
256 real instances and independent security/operator acceptance remain unproved.
