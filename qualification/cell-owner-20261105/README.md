# Cell lifecycle owner: execution boundary and qualification record

## Verdict and fixed source

**DENY_ALL for physical Cell lifecycle activation.** This change closes specific
native entry and persistence gaps. It does not establish a complete physical
Cell Split owner, independent signer custody, provider-atomic authorization, or
power-loss qualification.

The fixed implementation baseline is
`5bf9e9eb7dc49ef56caf5143531f3a705fcd0e52` (PR #4812), a descendant of main
`732e934ba496d90fbe042b8d41d479ef901643e5`. The baseline already includes complete
claim-head binding, fresh external frontier observation at FinalUse entry,
TaskFlow immediate writer transactions, and restricted Artifact host mutation
methods. These inherited changes are not counted as new work here.

During verification, PR #4812 advanced by one non-overlapping commit to
`484ce165522026d915c4cf526cd7df2effab632c`. That commit was integrated by a
fast-forward before final verification; it changes the host PQ endpoint checks
and their evidence, not these three packages. Baseline and negative-control
results retain their original `5bf9e9e` source identity. The final combined run
uses the `484ce165` integration base. The inherited host package's tests are not
included in the three-package result reported here.

No test key is a production host/operator/observer identity. No synthetic grant,
signature-format check, local callback, or unit test is accepted as evidence of
independent custody or the real last-use point of a remote provider.

## Changes in this source combination

1. The durable operation owner serializes the final synchronous adapter entry
   with operation lease renewal, generation handoff, and recovery writers. The
   already committed `dispatching` row remains the crash boundary. The final
   entry must recheck the exact operation, worker, lease, generation, and fence
   after awaited reads, then classify the result while retaining the writer
   transaction. A failed/unknown disposition must not refund authorization or
   infer that no effect occurred. An opaque origin-owner tag also rejects an
   in-flight token transferred to another opened database instance, including
   an old snapshot copy. Normal store clones preserve the same owner identity.
2. The Unix FinalUse store retains the claims file identity and expected durable
   length. Observed truncation/replacement/append drift freezes the owner. Final token
   entry also checks the live store, so a previously claimed token cannot skip
   this check merely because it needs no new claim append. After that local I/O,
   a fresh trusted-clock sample must still satisfy the grant's validity window;
   the consumer/dispatch witness uses that final sample. This preserves the
   existing storage format. These checks do not authenticate same-inode,
   same-length content changes, replacement of the owner-lock namespace, or a
   snapshot restored before startup. Cold rollback protection still requires an
   independently authenticated current frontier.
3. The public governed topology migration and recovery APIs refuse execution
   before grant consumption or the migration callback. The current source has
   no durable CNS route owner or independently retained lifecycle recovery
   floor. A public callback must not stand in for those missing mechanisms.
   Read-only topology inspection and proposal construction remain available.

The native Linux baseline passed 264 tests with one pre-existing ignored test.
The tests-only negative control ran seven selected tests: the existing CAS
failure/recovery positive control passed, and all six new attack regressions
failed against the original implementation. The combined candidate passed 277
tests with that same one pre-existing ignored test. After correcting the new
contention fixture to retain the repository's SQLite connection shim and
integrating the upstream commit, the final combined run also passed 277 tests.
These runs are separate observations, not additive test counts.

The ignored test is `destination_recovery_binding::destination_crash_worker`;
it is the pre-existing child-process helper invoked by parent recovery tests.
The new contention fixture configures `busy_timeout=0` on every acquired shim
connection before returning the pool, while preserving its WAL/FULL/FK settings.
It does not replace pool connection options or add a Clippy exception.

Raw commands, logs, source identities and digests are retained in this directory.
Filtered tests in the negative control are not additional skipped qualifications.
Native fixtures remain implementation evidence, not independent signing custody
or a physical power-loss verdict.

### Recorded checks

| Check | Observed result | Record |
| --- | --- | --- |
| Original three-package baseline | 264 passed, 1 existing ignored helper; exit 0 | `native-baseline.json`, `native-baseline.log.gz` |
| Original code plus selected regression tests | 7 run: 1 positive control passed, 6 expected failures; exit 100 | `native-red.json`, `native-red.log`, `native-red-test-only.patch.gz`, `native-red-tests.tar.gz` |
| Initial combined implementation | 277 passed, 1 existing ignored helper; exit 0 | `native-green.json`, `native-green.log` |
| Final composition after the explicit integration and fixture correction | 277 passed, 1 existing ignored helper; exit 0 | `native-final-green.json`, `native-final-green.log` |
| Scoped Clippy fix and repository format | Both passed, exit 0; neither changed the final tested sources | `native-final-style.json` and corresponding logs |
| Critical dependency source identity | 760 files checked, no differences; three cached package archives match Cargo.lock and vendored SQLite matches the fixed Git tree | `dependency-critical-source-checksums.json` |

The full test command, run from `codex-rs`, is:

```text
just test -p codex-hepta-contracts -p codex-hepta-operations -p codex-hepta-runtime --locked --retries 0
```

`input-source-manifest.json` describes the initial pre-format candidate, not the
final source. `final-source-manifest.json` and `qualification-summary.json` bind
the published code checkpoint, final source bytes and actual verification scope.

## Required authority separation

| Role | May produce | May not do |
| --- | --- | --- |
| Cognitive | Authenticated, scoped read requests; inference results | Mint execution grants, publish candidates, mutate Cell registries, retain an active reader after its authorization ceases to be valid |
| Learning | Immutable candidate proposals and measured candidate evidence | Register live parameters/scope, create live children, cut over routes, commit or roll back execution |
| Control | The sole lifecycle admission and commit decision; fenced phase capabilities | Treat a proposal, untrusted digest, or observer verdict as execution authority; reset spent authorization after rollback |
| Evidence | Append-only observations and independently signed verdicts | Execute the operation it observes, overwrite receipts, grant admission, choose a new effect identity after an unknown result |

The native domain services can persist their own facts only as subordinate
effect adapters. They must require Control-issued, exact-phase authorization at
their actual mutation point. A public Rust trait, constructor, boolean, or
caller-supplied identity is not such a capability. OS/process/credential custody
must also enforce this division; a Rust API alone cannot constrain arbitrary
code already holding the same OS authority.

## Reviewable lifecycle specification (not yet a connected executor)

Every operation must bind the same source identity, candidate digest, parent
Cell, child set, scope, parameter manifest, predecessor, operation identity,
owner generation, writer fence, and trust profile. Every transition appends a
durable intent and an observed disposition. A stage name or successful function
return is insufficient evidence of a native effect.

| State | Required transition evidence | Next state |
| --- | --- | --- |
| `DENY_ALL` | Independently authenticated current host/operator/observer trust, owner lease, monotonic safety floor, and a complete executable adapter composition | `ADMITTED` |
| `ADMITTED` | Exact staged immutable Artifact CAS result, with no runtime publication; candidate/schema/source validation and binding | `CANDIDATE_VALIDATED` |
| `CANDIDATE_VALIDATED` | New child identities, parameters and scopes are staged and nonserving; their receipts match the operation | `CHILDREN_STAGED` |
| `CHILDREN_STAGED` | Parent admission stopped; active work drained to a stable watermark; no unknown effects | `DRAINED` |
| `DRAINED` | Native old-writer fence committed, with independently observable generation/lease disposition | `OLD_WRITER_FENCED` |
| `OLD_WRITER_FENCED` | Durable snapshot and migration transfer bound to Artifact and independent predecessor snapshot | `MIGRATED` |
| `MIGRATED` | Candidate readback, content/scope checks, destination recovery and execution checks pass against the same state digest | `DESTINATION_VALIDATED` |
| `DESTINATION_VALIDATED` | New generation/fence installed; stale owners cannot write; destination is still nonserving | `NEW_WRITER_FENCED` |
| `NEW_WRITER_FENCED` | Durable CNS compare-and-swap from the exact old route to the new route; independent readback | `CUTOVER_COMMITTED` |
| `CUTOVER_COMMITTED` | TaskFlow disposition, parent retirement/tombstone and safety floor are durable and independently observed | `RETIRED` |
| Any submitted phase | Timeout, cancellation, lost acknowledgement, uncertain CAS or interrupted fsync | `INDETERMINATE` |
| `INDETERMINATE` | Authoritative lookup of the original operation proves applied or absent; incomplete or unavailable lookup is insufficient | Applied: append the original authoritative receipt and resume the verified phase. Proven absent: only the original operation/phase may be resubmitted under fresh final-use authorization. Otherwise remain fenced. |
| Any reversible phase | New authorized compensation operation with a higher generation, exact predecessor and independent receipts | `COMPENSATING` then a newly committed state |

`RETIRED` does not mean that evidence or the consumed authorization can be erased.
No recovery transition may decrement the generation, retirement floor,
revocation floor, or consumed-use history. There is no `INDETERMINATE -> new
operation ID -> retry` edge. A clean shutdown and a power-loss recovery must
reconcile the same identity and the same monotonic floor.

## Last-use and concurrent revocation

A signed final-use binding must include the operation and effect digest, scope,
issuer/trust profile, owner generation, destination, lease, nonce, revocation
generation, quota reservation and last-use disposition. Claims are durable
consumption, not a promise that the effect succeeded. An unsuccessful attempt
does not make its nonce reusable.

All awaited preparation must finish before the final owner admission check.
In the patched `DurableOperationStore::execute_authorized`, the final check and
synchronous local submission share one operation-writer transaction and the
same live FinalUse dispatch boundary. A competing recovery or handoff against
that same operation database cannot commit between the check and local
submission.

This does **not** make a later network effect atomic with a remote revoke. The
destination must enforce the same operation identity and fence at its actual
last-use point, through a shared admission lease or provider transaction.
Queueing work locally is an observable submission, not proof of a completed
remote effect. Fresh external-frontier observation alone still leaves a remote
observation-to-use interval; it cannot be advertised as distributed exactly-once
or immediate cancellation of an already admitted effect.

## Required separation of persistence domains (not implemented by this patch)

The following separation is a required design contract. This patch does not
provide the independent monotonic security-state backend.

| Reorganizable data/projection domain | Monotonic safety domain |
| --- | --- |
| Learning candidates, model parameters, replayable derived state, speculative plans, data-ledger branch selection | External effect intent/disposition; consumed grants/nonces/quota; last-use; revoked/retired signer floors; owner generations and fencing; Cell tombstones; authenticated current anchors |

A data reorganization or old-snapshot restore must join the current safety
domain; it cannot restore an old copy of that domain. Rollback is compensation
under a new generation. It cannot undo an external effect, unspend a grant,
revive a retired signer, or lower a revocation floor. If the current floor cannot
be authenticated, recovery remains `DENY_ALL`.

Revocation can refuse future reads or uses. It cannot make a recipient forget
plaintext already delivered by a previously authorized read. Historical audit
images and active runtime reader capabilities must therefore remain distinct.

WAL recovery must distinguish an incomplete unacknowledged final frame from a
complete corrupt frame and from loss of an acknowledged frame. Only the first
can be trimmed, and only when an independent current anchor permits it. The
existing FinalUse 40-byte claims format is preserved by this patch; it must not
be described as a newly checksummed WAL or an automatically recoverable torn
tail protocol.

## Open blockers and required evidence

The coordinator, durable CNS integration, mandatory phase capabilities, joint
last-use protocol and live Memory reader boundary are unfinished engineering
work. Missing real signing sources also prevent activation and qualification;
they must not be used to imply that the engineering work is already complete.
New generic adapters, test owners or caller-constructible receipts do not close
these implementation gaps.

| Blocker | Required closure evidence |
| --- | --- |
| Unified physical lifecycle executor | One actual source/toolchain/config composition drives Artifact CAS, child/scope/parameter registration, migration, CNS, TaskFlow and retirement; every effect entry rejects a missing/wrong Control capability |
| Durable CNS route and generation recovery | Real durable route CAS, native fence enforcement, current independent floor, old-generation replay rejection after clean and power-loss restart |
| AuthBus/FinalUse joint last-use | Scope, policy revision, lease, nonce, quota and revocation serialized with the actual consumer, including revoke-during-await and competing owner cases |
| Memory reader capability | Caller-created `CognitiveAccess` is insufficient for runtime retrieval; current Control-bound capability rechecked after awaits and before use; historical audit views cannot become active readers |
| Monotonic security-state backend | Independent storage/custody of consumed uses, retirement and revocation floors; reorg and old backup cannot reset them; unknown external CAS cannot be treated as absent |
| Independent signatures | Host, operator and observer are separately pinned real principals with independently controlled signing sources and current revocation; three local test keys do not satisfy this |
| Physical recovery | Clean restart and actual interruption/power-loss campaigns on the fixed composition, independently observed; local file mutation tests are only implementation regressions |
| Platform qualification | Native Linux results below have their actual scope; macOS/Windows and cross-host behavior require their own recorded execution |

## Acceptance rules

- A rejected entry must demonstrate zero native submissions/effects, not merely
  a final error returned after a callback has already run.
- Unknown CAS or provider results are queried by the original operation ID.
  Only authoritative complete absence can enable a retry; local missing receipt
  files are not absence proofs.
- Competing writers must be observed using independent connections/processes,
  with their fence/revision histories retained.
- Source-only audits, format checks, synthetic signer fixtures, native local
  regressions, independent host qualification and production admission remain
  distinct evidence levels.
- No subset of green tests changes the physical lifecycle verdict from
  `DENY_ALL`. The missing composition and signing/recovery sources must first
  be supplied and independently verified by the actual execution owner.
