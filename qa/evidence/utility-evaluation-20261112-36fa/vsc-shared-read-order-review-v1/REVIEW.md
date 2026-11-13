# V/S/C original-read order and sealed sharing boundary

Status: source review only; no production implementation, Rust compilation, native execution, or qualification result. Source is fixed cc57c7198db6293ccca562253c42fffbe2a04633 / b7b357c07b5539769a068c6b9b009629f5612d1e. The accompanying source reference file pins every inspected file against the complete canonical inventory.

## Decision

The inspected original V/S/C chain does not require overlapping exchanges on the same T or E command client. A first proposal can therefore use a sealed read-only Arc over the existing client, retaining the original slot.take / None / Unavailable behavior. There is no source-grounded need here for a new queue, request protocol, Contracts method, retry policy, or larger limit.

This is not a guarantee that every legal external schedule will succeed. Separate service futures and independently initiated readbacks can contend. The existing refusal and uncertainty behavior must remain observable. Sharing does not grant one 128-request or 300-second budget per Arc.

## The actual order

1. In circuit_evaluated_retention_context.rs::require_current, the original Training readback is awaited and compared with the complete held T result before the original Evaluation readback is awaited and compared with the complete held E result. Final clock and context authentication follows both.
2. Selection::training_evidence awaits that complete owner check. Its before/after observation and journal checks are sequential; there is no concurrent T/E fan-out.
3. NextUse::predecessors awaits the complete evaluated owner check before it calls selector.readback. Hence C does not retain an in-flight T or E exchange while S recursively reads the same T/E pair. C::finish_original_readback repeats the predecessor check, then the actual Source/Cell observation and journal check in the defined order.
4. EvaluatedContinuation::read_selection awaits Version publication readback before S readback. read_completion awaits Selection, readiness, C, Selection again, and Version again. Each step completes before the next. The Candidate retained lane uses try_lock and sets failed=true until the complete operation succeeds; competing operations are refused, not queued.
5. execute_evaluated_retained_stage follows the same sequential lane. Root continue_original has one fresh stage call at a time, then original attestations and checkpoint, before choosing the next stage. Root's separate readback request path exists, so this is not a global exclusion claim.
6. Version run_original_c performs the actual read_original while holding its original state lock, checks Published/freshness, and takes the one config. That blocking operation completes and drops the lock before crate::run starts. It does not carry a T/E exchange across C execution.

## Real contention remains possible

Version::serve_original_ordinary already uses try_join for command serving, run_original_c, and the FinalUse issuer. After publication, a separately scheduled S command can overlap Version's startup/current observation; independent service callers can also initiate readbacks. This is possible contention, not an intrinsic recursive exchange required by the ordered chain. The new capability must not hide it by reissuing work or creating a new channel.

T::exchange and E::exchange take the one channel out of its mutex before awaiting the blocking original request. A second caller sees None/Unavailable (or the existing try_lock refusal). Only the winning caller restores the same channel after full response, peer, clock, signature, and retained-result validation. Dropping that winning future leaves the original slot empty; a sealed wrapper must not restore, reconnect, duplicate, or reset it. Existing remote Busy/Missing/Pending distinctions and each client's restore/fence rules remain intact.

Do not hold a new outer lock across all of C's predecessor traversal: C later calls S, and S reads the same predecessor capabilities. Such a lock would introduce a recursive wait not present in the original ordering. The minimal proposal needs no such lock.

## Version custody boundary for a later proposal

- Fresh Prepare requires the original Fresh brand, the one-shot preparation_requested swap, and the Awaiting phase; it moves original T/E custody into the actual Prepared publication. Published does not need a later exclusive take for a second Prepare.
- Successful publish returns the identical T/E clients, installs the actual original task/read owner, rechecks current/freshness, and only then records FinalUseOutcome::Published. Sharing may be considered after this real boundary under the same state lock. Installed alone is not sufficient: a late publication/current-read failure can leave Installed/T/E but no successful Published result.
- Cold construction's Published enum is not admission. read_original_recovery removes the stored reader, performs complete original reads before and after construction/reuse, checks equality and actual publication, checks freshness/lifetime, and then installs the reader. A future export must require this admitted state and perform a fresh original current check; it must not promote Recovered to NewWork.
- Any Owned-to-Shared transition must be one-way under the existing state lock and apply only to the admitted evaluated profile. It must preserve the old by-value constructor path, the exact original context/pins, and actual host placement. No public raw-client/Deref/FD/Execute escape is part of this recommendation.
- If an already consumed/failed client is wrapped, it must remain failed. Concurrent failure is not permission to remake a client.

## Scope and remaining proof

This review establishes the inspected order and identifies the source-defined custody boundary. It does not establish a completed public ten-owner run, a successful shared-client implementation, aggregate request-budget sufficiency, or absence of every external scheduling race. The original four public Bootstrap connections, 128 frames, absolute lifetime, purpose, nonce, peer/pidfd, complete signatures, and failure semantics are unchanged requirements.

The separate test-only B increment uses the already existing production PanelMember Arc field. Its private transport handlers do not exercise public permit admission and are not proof that the public four-slot deployment succeeds.

