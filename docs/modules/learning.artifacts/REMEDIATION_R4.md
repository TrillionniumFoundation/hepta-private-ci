# learning.artifacts R4: durable withdrawal floors and evidence consistency

## Candidate identity and scope

This candidate inherits `39bb4dd5fde6ee5107eac60ec412230d6f30a191` from
`codex/learning-artifacts-qualified-host-r3-20260927`. The integration base inspected
was `a126987b84737dbc2ee2592442a314117bddb4a2`. Inherited service recovery, durable
drain and qualification-runner work is not new R4 implementation. The final Git
commit and Actions run must supply execution identity; this document is not an
execution receipt, deployment approval or authorization to merge.

The actual API is `LearningArtifactOwnerService` over
`LearningArtifactOwnerHost`, with signed CURRENT and a scoped withdrawal registry.
There is no `LatestPublishedHead` trait or unified `COMPLETE` field in the inspected
implementation. A quota reservation/refcount/GC subsystem, a production daemon and
automatic snapshot fallback must not be inferred from the previous prose audit.
This candidate does not invent those implementations or treat them as tested.

## New native protocol

`owner/durable_withdrawals.rs` holds a private `DurableWithdrawalFloor`, always
operated while the existing owner writer fence is held. `open` checks the supplied
frontier against the durable floor before returning a usable service.
`install_withdrawal_frontier` first rejects cross-scope or non-prefix changes,
retains the newer in-memory frontier, and marks durability unknown before I/O.
Only successful file and directory synchronization clears that unknown state.

The local layout is:

```text
writer/withdrawal-floor-v1/
  0000.v1  # scoped genesis
  0001.v1  # first notice chain head
  ...
```

Each UTF-8, newline-terminated record binds a format tag, artifact registry ID,
withdrawal scope digest, storage binding, canonical sequence and withdrawal chain
head. Expected bytes are computed from the independently authenticated supplied
frontier, never from the file being checked. Every existing record must be an
exact contiguous prefix. Older input, a fork, a foreign binding, a gap, a symlink,
an unknown entry, truncation or altered bytes is rejected without repair.

The directory is created with Unix mode `0700`, and files with create-only mode
`0600`, subject to a stricter umask. Each newly written file is synchronized,
followed by the floor directory, writer directory and store root. An exact retry
re-synchronizes the SAME validated file handle. A full but previously unsynced
record can be reconciled; an empty or partial record is never overwritten or
accepted as complete.

`WithdrawalDurabilityUnknown` blocks publication and authenticated current-view
issuance after uncertain installation. `is_drained` remains false while that
uncertainty exists. `withdrawal_frontier_is_durable` reports storage acknowledgement
only, not actor authentication, freshness or permission to use an artifact.

The maximum is one genesis plus `MAX_DURABLE_ARTIFACT_RECORDS` (4,096) records.
Validation and re-synchronization are bounded O(history), not a throughput claim.
No cleanup path in this candidate removes floor records.

### Remaining trust and compatibility boundaries

The embedding host still authenticates withdrawal actors, supplies trusted time,
protects all ancestor directories, provisions signer trust, and maintains an
independent newest-head/withdrawal/stop floor for whole-store rollback resistance.
A directory copied from an old backup is not made fresh by local hashing. This
implementation is not an `openat2` directory capability and does not close hostile
ancestor replacement races. A durable withdrawal floor protects future admission
and restart inputs; it does not by itself project new withdrawal notices into
already published registries or invalidate all previously issued pinned views.
That product revocation propagation remains a separate open integration task.

The durable-floor service profile is Unix-only. Other targets return explicit
`Unsupported` rather than silently claiming directory durability. Legacy stores
without this namespace require a separately authenticated current frontier at
first adoption. Downgrading to an older binary which ignores this namespace is
not safe and must be prohibited by the deployment profile. Migration, complete
backup restore and real power-loss qualification are not established by this
source candidate. Never delete an uncertain record merely to make startup pass.

## New regression source

Two service tests exercise persisted frontier installation, old-input rejection
on reopen, exact prefix extension, uncertain-write fencing and drain refusal.
Seven floor test functions include a child helper and six parent/direct tests:
monotone prefixes and forks; every truncation and byte mutation; gap/extra-entry
and symlink rejection; injected I/O boundary failures; scope/binding rejection;
and subprocess death at all 3 sequences x 4 persistence boundaries.

The subprocess suite uses readiness handshakes, parent deadlines, a child watchdog
and explicit kill/wait cleanup. It is process-crash evidence only when executed:
SIGKILL is not a physical power cut or loss of the kernel page cache. These Rust
tests have not been executed in the editing environment; no native success claim
is made here. Target-host execution must validate the actual final candidate.

## Evidence and source identity

`hepta_artifact_receipt_guard.py` binds the original implementation-map bytes to
an independently expected Git blob. It rechecks retained output budgets and
regular-file constraints, delegates exact source/run/JUnit validation, then
recomputes requirement traceability and all completion fields. Rehashing a receipt
cannot hide unmapped obligations, substitute source/test identities, or set
`requirementTraceabilityComplete` contrary to the recomputed result. Unknown
completion fields and integer substitutes for booleans are rejected.

The guard does not authenticate GitHub Actions on its own. A consuming release
system must authenticate the workflow, run, attempt, issuer and expected candidate
independently. Native execution can be qualified while requirement traceability
honestly remains incomplete; neither state grants `moduleComplete`, activation,
independent acceptance or release.

`hepta_artifact_source_binding.py` provides a read-only source-object check and an
explicit pre-commit refresh. It preserves `sourceBase` as historical provenance,
all unresolved gaps, test declarations and authority flags. For a staged candidate:

```sh
git add <owned-changed-paths>
python3 scripts/hepta_artifact_source_binding.py --tree "$(git write-tree)" --write
git add docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json
```

Qualification must never run `--write` as a silent repair. The exact-head/synthetic
merge workflow executes all artifact evidence-verifier tests and adds the bound
receipt guard after native execution. Failure/cancellation/skipping cannot become
a passing `Lane E artifacts required` result. Existing build, Clippy, format,
complete test inventory and native regression execution remain mandatory.

The 18 NEW Python regression tests were executed locally and passed (11 receipt
and 7 source-binding tests). They validate these tools against synthetic evidence
and miniature real Git repositories, not the artifact Rust runtime. The editing
environment did not contain a Rust toolchain or a full dependency-resolved checkout.
Inherited Python tests and final candidate native CI still require execution.

## Six-workstream delivery status

| Workstream | R4 change | Not yet established |
| --- | --- | --- |
| Current-candidate qualification | Explicit source rebinding and independently recomputed receipt claims | Final exact-head and merge execution; original global Lane E closure failure resolution; server-side required-check configuration |
| Production host | Durable withdrawal lower bound and uncertainty fencing in the existing service | Authenticated transport/daemon, action authorization, externally durable freshness, key lifecycle, complete backup/migration |
| Durability | Create-only withdrawal records plus file/containing-directory sync | Capability-backed ancestors, whole-store rollback protection, real power-loss behavior |
| Owner boundaries | New private withdrawal persistence module | Full owner_host refactor and narrow injected storage trait |
| Verification | Native adversarial and subprocess test source; 18 executed Python tests | Rust execution, comprehensive concurrency model/fuzzing, capacity benchmarks and migration suites |
| Status/docs/operations | Traceability consistency guard and this exact-scope addendum | Complete requirement mapping, production metrics/alerts, stable API and operational qualification |

The available GitHub connection can write source and request CI through normal
push/PR events, but does not expose administration writes. Defining an aggregate
check does not install branch protection or a release gate. An administrator must
add `Lane E artifacts required` without removing `CI required` or `Architecture
required`, then read back the effective policy. This task did not change those
server-side settings or merge/release the candidate.

## Acceptance before activation

Retain final-source and ordered-parent actual-base receipts for Linux and macOS;
all mandatory gates must execute and pass without retries hiding failure. Preserve
unknown outcomes and evidence on crash. Demonstrate old/forked withdrawal input
cannot reopen service; invalid durable bytes cannot be repaired by normal retry;
current runtime withdrawal propagation is tested separately. Require independently
provisioned trust, an authenticated product transport, backup/restore and target
filesystem qualification before any production activation. Until then the module
remains a source candidate, not an activated production writer.
