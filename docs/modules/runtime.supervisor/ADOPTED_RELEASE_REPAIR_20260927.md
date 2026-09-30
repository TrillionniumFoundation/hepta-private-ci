# Release conversion after process adoption

## Candidate scope

This amendment continues PR #1057 from source commit
`c2a67f7729138f354fca382de515efb20ded2c4b` and tree
`c7258191eb4123645d17e87e269e2981de4eabb0`. It fixes the main-process
release-conversion ownership gap identified in the preceding adoption and exit
amendments. It does not certify their execution or close the five-stage program.

## Failure boundary

The preceding recovery path retained the adopted handle on a catalog lookup
error, but `AgentRelease::try_from` could return early before that handle was
installed. The conversion validates both Agentd and optional Matrix commands.
A conversion failure therefore bypassed the catalog-error containment path.

`recover_slot` now installs the exact adopted handle before catalog lookup or
command conversion. The private recovery helper consumes the existing catalog
result and validates the complete bundle before changing `active_release`,
`previous_release` or `last_command`. Its release ID must match the retained
process lease. This helper is visible only within recovery, not public product
API, and adds no alternate catalog, writer or authority source.

Lookup, identity and either command-conversion failure take the same containment
path: invalidate health, logically fence the retained process, attempt kill,
and retain it for observation/retry. Successful signal return alone records
Killing and KillRequested; a failed signal leaves Stopping with an immediate
retry deadline. A subsequent lifecycle CAS error does not remove the handle.
An already fenced adopted process cannot regain admission through this helper.

The rejected bundle never overwrites the selected release metadata. Neither a
failed kill nor a failed registry transition authorizes replacement or lease
removal. Existing tick and exact-exit cleanup remain responsible for termination
retry and finalization.

## Regression source

`recovery::adopted_release::tests` adds seven test functions:

| Case | Invariant |
| --- | --- |
| Invalid Agentd command | Retain and fence the exact handle; preserve metadata and lease |
| Invalid Matrix command | No partial installation of an otherwise valid Agentd bundle |
| Catalog error and failed kill | Retain ownership, no false kill acknowledgement, retry the same process |
| Wrong resolved release identity | Reject even a structurally valid but unrelated release |
| Valid complete bundle | Update metadata without signalling the adopted process |
| Valid resolution after rejection | Never undo fencing or reopen release admission |
| Lifecycle CAS failure | Retain fenced ownership and preserve the newer registry generation |

Fixtures use actual temporary FleetRegistry and lease files, but inject decoded
`RegisteredRelease` results and deterministic process signals at the private
post-adoption boundary. They do not prove that the real catalog can return those
malformed values, nor do they execute real Agentd, PID reuse or target-host faults.
Existing end-to-end recovery-driver test sources remain in place.

## Validation boundary

The original `recovery.rs` bytes matched Git blob
`b939b847240f232b07d1beccf9ce5e8a278ce3c7` before editing. Local checks cover
scoped Git whitespace, patch applicability and exact applied-file bytes. Native
compilation, rustfmt, Clippy and all seven new test executions are unverified:
the editing environment has no Rust toolchain. GitHub Actions is the available
execution path; a queued or pending run is not a successful test receipt.

Targeted command for a correctly provisioned repository checkout:

```sh
cd codex-rs
just test --locked -p codex-hepta-supervisor --lib recovery::adopted_release::tests
```

Run the complete supervisor library and relevant product profiles as well; this
narrow command does not replace their required qualification.

## Remaining gates

Only the main adopted-release conversion ownership item is addressed here.
Rejected-release early return still prevents companion recovery in that path;
Matrix adoption/termination ownership needs a separately coherent repair.
Startup hydration before adoption, failed lease publication after spawn, durable
stop/kill supersession, predecessor/replacement restart identity, cross-daemon
cleanup and directory-inode security remain outstanding.

Per-Agent mutation concurrency, 256-process mixed load, named Linux/macOS
fault/soak runs, full authority distribution/rotation/revocation, actual product
caller-to-audit execution and independent security/operator acceptance are not
established by this patch. Candidate CI was pending, not green, at the pre-edit read.
No CI-policy, dependencies, trust roots, production flags, branch protections,
main reference, activation or release are changed. Previously blocked CI-policy
edits are not included or retried through another route.
