# Writer admission, response, observation and capacity boundaries

Updated: 2026-09-29. Implementation is a candidate; execution and release status
remain governed by exact CI receipts and the external gates in CURRENT_STATE.

## Actual baseline and preserved ownership

The reviewed baseline is `a9fa9b4d0629bcab149026ac76a5f1470ee8363d`.
It had one bounded FIFO with immediate rejection and a reserved shutdown slot.
It did not have three round-robin queues, a ten-second enqueue wait, a
`NativeControlPort::call`, or a separate publication-ticket worker. Those
assumptions must not be used as implementation evidence.

This revision retains NativeControlPort -> NativeJournalWriterHandle -> one
DurableInferenceControl owner. No provider await enters that writer, no second
journal is introduced, and no recovered effect is automatically dispatched.
The existing output-protection and signed-recovery paths remain in force.

The owner acquires a stable lifecycle sidecar lock before active journal
open/replay and retains it across checkpoint inode replacement. The active
generation also retains an inode lock for compatibility. Do not remove the
sidecar after shutdown or maintenance; its stable identity is part of the
writer fence.

## Native record staging and publication

`commit_native` stages the event's single target record through the same reducer
used for replay, retaining the owner's complete authoritative map. Reserve first
checks identity, pinned maximum and held slots against that full map; a one-record
projection alone cannot decide admission. Serialization, the complete candidate,
its return receipt and insertion key are prepared before journal append. After
append, flush and `sync_all` succeed, only the target record and maximum-in-flight
value are installed. Validation failure leaves state and bytes unchanged; uncertain
append failure poisons the owner without publishing the candidate.

`CheckpointReference` cannot use this path. Compaction separately stages the full
checkpoint and retains its existing replacement and poisoning rules. Reserve still
scans retained identities for held capacity, and the 16384 distinct-record ceiling
still applies. Avoiding the full-journal clone is not a claim that every mutation
is O(1), nor a measured host-performance result.

## Admission and response are different outcomes

`Overloaded` and `Closed` from admission mean the command was not delivered to
the actor. Neither proves anything about an earlier attempt with the same ID.
After successful admission, `AcceptedDeadlineExceeded` means only the caller's
response wait expired. `AcceptedReplyLost` means the accepted command's response
channel closed without a usable response. Both leave the durable outcome
unknown to that caller: neither cancels the command nor authorizes an effect
retry, reservation release, or journal deletion.

A dropped waiting future also does not remove an admitted command. The writer
continues applying it and records a lost successful reply if the durable method
succeeds but the reply cannot be delivered. `successful_replies_lost` counts
successful method results, including idempotent successes; it is not a count of
new commits or provider effects. Durable `record`/signed reconciliation remains
the source of truth. Unknown after dispatch retains its slot.

Response and shutdown budgets are configurable independently. Neither is a
filesystem syscall cancellation mechanism. A blocked writer retains its actual
lifecycle lock until it exits. A shutdown timeout never certifies cleanup.

Exact-plan bind, authorized dispatch and settlement, and signed recovery/retirement
sample authority freshness at writer application time. A queued command cannot
keep an expired proof live by supplying its earlier admission-time timestamp.

## Two admission quotas, one FIFO ordering

Ordinary commands and completion/lifecycle commands have separate bounded
quotas. Started, cancel, pre-effect stop/abort/rejection, authorized settlement,
and verified recovery/retirement use the completion quota. Both quotas feed one
FIFO, preserving ordering between earlier dispatch, cancellation and terminal
transitions. There is no strict-priority bypass and no unbounded pending sender
list. One additional slot is exclusively reserved for the shutdown barrier.

A full ordinary quota cannot consume completion capacity. A full completion
quota is still an explicit rejection, not guaranteed settlement. Shutdown seals
all handle clones and follows every accepted command, even when both quotas
are full. Operators must size completion capacity for the declared concurrent
lifecycle burst. The reserve is not a claim of bounded filesystem latency.

## Read consistency and metrics

`record` and `metrics` retain serialized owner semantics. `published_metrics`
returns one immutable Arc containing the last explicitly completed metrics
barrier, or None before the first refresh. Reading it does not enqueue a command
or scan the journal. It may be stale: its monotonic age is available through
`age_millis`, and its optional wall-clock publication time is metadata only.
The expiration counts retain the caller time of the explicit metrics barrier.
It cannot be used for admission, current authorization, or deciding to replay.
Only the owner publishes; callers cannot hold a watch-channel borrow across
await or mutate the snapshot. No per-task cache or second state store is added.

Queue observations include separate ordinary/completion enqueue-to-dequeue and
writer-apply windows, active-command age, high-water mark, rejection counts,
and lost successful replies. Each percentile is nearest rank over the most
recent 256 observations of that stage/class. `observed` is the lifetime sample
count; `samples` is the bounded window size. Sorting occurs outside admission.
Writer-apply time includes the whole command and is not falsely labelled fsync,
provider latency, or commit-to-external-publication latency.

## Host selection, not arbitrary capacity inflation

NativeWriterLimits and each worker/recovery/maintenance CLI accept:

- `--writer-ordinary-capacity` (default 256) and `--writer-terminal-capacity` (64);
- `--writer-reply-timeout-ms` and `--writer-shutdown-timeout-ms` (30000 each).

Both capacities must be positive with total at most 65536. Deadlines must be
positive and at most one hour. Defaults are engineering choices, not selected
host qualification. Changing them does not change authority or effect budgets.

`scripts/hepta_inference_capacity.py PROFILE.json` evaluates an explicit host
profile with `host`, `peak_commands_per_second`, `assumed_service_bound_ms`,
`ordinary_burst`, `terminal_burst`, `queue_wait_budget_ms`, `reply_budget_ms`,
`shutdown_budget_ms`, and `maximum_utilization`. It checks headroom and the
conditional full-FIFO drain budget. It never changes runtime settings or sets
production qualification. A declared service bound must separately be tested
against real disk faults, maintenance, scheduling and provider/vault workloads.

## Tests and evidence scope

`native_record_staging_tests.rs` adds four source regressions:

- `staged_admission_counts_all_held_records_and_preserves_compacted_history`: full-map capacity, retained unrelated records and checkpoint metadata survive staged commits and reopen.
- `late_reducer_failure_does_not_install_mutated_target_or_append`: revision overflow after candidate mutation leaves authoritative state and journal bytes unchanged.
- `actual_append_failure_discards_target_and_first_admission_candidates`: a real read-only journal descriptor fails append, retains old records/budget, poisons the owner and reopens the prior durable cut.
- `mismatched_event_identity_and_checkpoint_are_rejected_before_append`: mismatched target identity and checkpoint events cannot reach this append path.

These are test-source identities; passing candidate receipts and performance
qualification remain separate evidence.

`control_actor_boundary_tests.rs` drives the actual journal actor, including
accepted timeout followed by commit, lost terminal reply and restart, exact-ID
idempotence/payload drift, full ordinary quota with completion and shutdown,
and immutable observations under a deliberately paused real writer. The pause
is test-only fault injection into that same owner, not another executor.

`actor_mailbox_boundary_tests.rs` checks quota isolation, FIFO fairness,
concurrent producers and shutdown. Its ignored `mixed_fifo_contention_curve`
reports queue/apply percentiles under a named synthetic service delay. That
curve is not a disk-fault, real-provider or target-host performance receipt.
Vault boundary tests exercise UID, socket/config identity and permissions; they
do not prove an independent encryption service or signed deletion confirmation.

Current-state tests require actual source paths and resolvable Rust function
identities. Generated projections remain navigational, never self-asserted
exact-head successes. Global implementation-map failures in other modules stay
visible and blocking; they must not be relabelled as native test failures.


The additional signed post-effect fixture runs the unchanged production plan
verifier and authorized actor settlement, drops the actual reply receiver,
checks digest-only output protection, and reopens the journal. It does not
simulate a provider call and is not a real-provider acceptance receipt.

`hepta_inference_boundary_native.py` creates diagnostic Cargo manifests outside
the checkout, pointing at the actual core/host Rust source files. Its scope is
a minimal dependency closure, not the entire App Server/Agentd product package.
The generated manifests, lockfile, source SHA/tree and raw logs must be retained.
Normal full-workspace source-head/base-merge qualification remains required.
Lane evidence refuses incomplete inventories, boolean exit codes, dirty or
mismatched source identities, and detached/tampered logs. Passing these metadata
checks is not independent authentication or release authorization.

`real_writer_mixed_query_terminal_contention_curve` adds 128 real-journal
terminal operations per capacity setting under saturated ordinary queries.
It reports actual owner queue/apply windows, including storage work, without
calling those windows isolated fsync or provider latency. It is a runner-local
pilot, not selected-host pressure/failure acceptance. Shutdown uses one shared
deadline across acknowledgement and thread joining; timeout still cannot stop
a blocked filesystem syscall or certify released ownership.
