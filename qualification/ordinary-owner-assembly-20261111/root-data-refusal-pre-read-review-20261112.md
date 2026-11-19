# Root data refusal: pre-read durability and finalization review

Date: 2026-11-12 UTC

## Status and source identity

This is a static source review and implementation plan. It is not a native test result, a cold-recovery qualification, or evidence that the ordinary A-to-C learning path is complete.

The published Source pin, Source handoff, capture worker, and protected-store implementations were re-read through GitHub at commit `6e4842b5ed28ab6f948646c051651a6c75085085`. The exact relevant paths are:

- `codex-rs/hepta-agentd/src/authority_host_historical_source_pin.rs`
- `codex-rs/hepta-agentd/src/authority_host_historical_source_handoff.rs`
- `codex-rs/hepta-agentd/src/authority_host_historical_source_transport.rs`
- `codex-rs/hepta-agentd/src/authority_host_historical_source_session.rs`
- `codex-rs/hepta-contracts/src/authority_host_store.rs`

That published snapshot is used only for the statements about these files. It is not asserted to be byte-identical to the subsequent local RunStart retention branch.

The complete local RunStart branch was last committed at `80ce48d0811bc6937ec198d40de5d3d1de8e159a`, tree `d13bff8765507b3016288c27f4c95ba70289b609`. Its parent implementation at `f0bfa9b4df7b8f6ed056024ac1d5995df30f4cbb` received a separate source review. Commit 80ce48d added the physical-corruption/restore cross-process counterexample. The last local executor ran as UID 1000; this ignored UID0 test was written, not executed. GitHub returned “No commit found” for 80ce48d during this preservation attempt, and the Root coordinator confirms that this local chain was not uploaded.

After that commit, a private durable-arm helper and RunStart store/transport edits existed as local, uncommitted WIP. The final formatting/check output was not retained completely. Those WIP bytes and their final hashes are unavailable while the executor is unavailable. No exact recovery, formatting pass, compilation pass, or execution pass is claimed for that WIP. Source pin and Source handoff had not yet been modified for this repair.

## Confirmed failure mechanism

The original Root records have an in-memory poisoned state and a main-record fence. On the published Source implementations, and on the reviewed local RunStart implementation, fencing first loads and decodes that same main record.

A concrete source-level counterexample is:

1. A valid completed/finalized main record exists.
2. Its physical JSON bytes are corrupted.
3. A physical read detects the damage and returns an error.
4. The ordinary fence path also fails because it cannot decode the damaged main record.
5. The process exits, losing its in-memory poisoned state.
6. The former valid main bytes are restored.
7. A new process opens the restored main record and reconstructs an unpoisoned handle.

A marker written only after step 3 does not fully repair the mechanism: a process can exit between the failed read and that marker's durable write.

The local counterexample test name is:

`authority_host_service::generation_initial::run_start_store::tests::root_run_start_physical_corruption_then_restore_remains_refused_across_processes`

Its private child test is an implementation detail and must not be counted as an independently completed Root-parent case. The predicted old-source failure is a source deduction; it has not been presented as a native failure.

## Required independent refusal protocol

Use one private Root-owned refusal record for each main-record slot. Its record binds schema, purpose, data kind, complete target binding, monotonically increasing attempt sequence, and a state of Ready, Armed, or Refused.

The marker owner key must follow the main store's actual scope slot. In the published Source stores, the primary owner is derived from `scope_digest(target.scope())`. Deriving the marker owner solely from the complete target digest would give different targets sharing that primary scope distinct coordination markers. Instead, the owner must share the primary scope namespace, while the marker contents still bind and compare the complete target digest. A different complete target then fails before it can read the primary record through another gate.

The three data kinds are closed implementation choices: RunStart retention, Source pin, and Source handoff. No peer supplies a marker owner, phase, attempt number, or serialized refusal record.

For each protected operation:

1. Load and validate the existing Ready marker without reading the primary record.
2. Increment its attempt with `checked_add`.
3. Durably CAS the entire exact Ready record to Armed with that new attempt.
4. Open/read the primary, perform any intended primary CAS, and compare the complete physical readback inside the same operation.
5. Perform all required original-context, receipt, and absolute-deadline postchecks for that operation.
6. Only after those steps succeed, CAS the exact same Armed record to Ready.

Any error, panic, or process exit during the primary operation leaves Armed. Cold recovery rejects Armed. It never completes an unfinished operation from current file contents.

The existing `HostAuthorityFrontierStore` uses a per-owner nonblocking file lock and an exact expected-value comparison for CAS. The helper also needs a local gate, but that local mutex is not the cross-process safety mechanism. A stale handle cannot clear another handle's arm because completion compares the complete record, including the attempt number. A concurrent Refused transition also makes the old Armed-to-Ready CAS fail.

Explicit refusal must persist through the independent record before trying to decode or fence the primary. It must work when the primary cannot be parsed. If the refusal storage itself is unavailable or its CAS cannot be acknowledged, return an honest error. Do not report that refusal was durably recorded when it was not.

## Fresh creation and recovery remain separate

Fresh registration creates an Armed refusal record before the primary is initialized or observed. It becomes Ready only after the whole initialization/observation operation has completed and its exact primary readback and required postchecks succeed.

Recovery opens an existing marker and primary only. A missing or malformed marker is an error. A previous primary with no marker cannot acquire historical eligibility by a recovery-time marker initialization. In a fresh-creation attempt, an existing-primary conflict must leave the fresh marker Armed and fail; it must not be mistaken for the distinct case where an already-existing valid marker permits exact idempotent readback.

Missing-marker handling must not read the old primary merely to decide whether to create a marker. Such a read would occur outside the durable arm.

## Source pin: the arm must precede observation

In the published `capture_initial_source_pin`, the real Source reader runs before `RootHistoricalSourcePinV1::retain`. Adding a helper only inside `retain` would miss failures in:

- opening/checking the original Source witness;
- opening the historical Source reader;
- its first complete physical publication observation;
- comparison with the original identity, fence, configuration, and target.

Therefore the outer capture operation, already bound to the actual fixed slot/target and original Root writer context, must establish its durable Armed state before those physical operations. The same arm must cover the complete return from `with_initial_publication_context`, including its original pidfd/session/revocation postchecks, not merely the callback body.

The exact pin-record IO can be moved into private unchecked functions called only inside that outer operation. Do not nest another arm of the same data kind inside `retain`, `readback_digest`, or the capture callback.

A first failed observation with no pin still leaves the refusal marker Armed. Restoring Source bytes cannot turn that failed first attempt into a new capture after restart.

The data pin remains data. Its presence is not proof of original RunStart authentication, terminal Outcome, retirement, Dataset admission, or learning authority.

## Source handoff: finalization covers the final checks

A successful original peer ACK transitions the primary from Pending to PeerAcknowledged in its existing original context. The full context must return successfully before finalization is attempted.

For finalization, one Handoff arm must contain:

1. the PeerAcknowledged-to-Finalized primary CAS;
2. exact physical readback of that Finalized primary;
3. the associated Source pin's current protected readback and exact digest comparison;
4. the actual same-session capture receipt check and its original absolute deadline;
5. only then, completion of the Handoff marker to Ready.

A Source pin guard nested inside a Handoff guard is a different data kind and can be reasoned about separately. Re-entering `open_finalized` for the same Handoff while its own arm is held is invalid; it would either reject the arm or accidentally introduce an unguarded path. Use private unchecked main-record comparisons in the same arm instead.

Cold `open_finalized` must similarly include its physical primary read and associated pin comparison inside its protected operation. Valid Pending or PeerAcknowledged bytes remain ineligible and are never promoted. Their ineligibility alone need not be treated as evidence of physical corruption.

A Finalized record proves completion of the preceding context and specified data checks. It does not prove that the final reply reached the peer, and it does not issue a grant. The final transport reply and normal EOF do not revoke an already completed durable data handoff.

## RunStart finalization

The local repair plan keeps the real nonterminal retention protocol and the existing live seam: append plus sync, release the Objective owner mutex, validate current AuthBus trust, await Root retention, recheck ready/current generation/current AuthBus trust, then invoke execution.

The proposed RunStart finalization arm contains the Observed-to-Finalized primary CAS, exact physical readback, actual bounded response encoding, and the actual original request-end postcheck. Clearing Armed immediately after the primary CAS and performing the last deadline check outside the helper would leave the same crash window.

The registration-time physical prefix digest/length and actual parser frame boundaries remain data checks. Neither an offset nor a Root data receipt can replace the later authentication, Cell, Ledger, observer/outbox, and real-retirement joins.

## Required tests and evidence separation

The repair needs actual Root-owned directories and physical records, not an in-memory replacement store:

- Retain the existing corruption/restore test as an independently identifiable counterexample.
- Add a child process which exits inside the protected primary-read operation, before its error handler can run. After restoring only primary bytes, a fresh process must reject the still-Armed marker.
- Exercise first-observation failure before a Source pin exists, then restore Source bytes and prove that recovery cannot initialize a pin.
- Exercise the Root crash stage after the main Finalized CAS but before final context/receipt completion; cold recovery must reject the unfinished arm.
- Exercise cross-handle attempt sequencing and a stale completion after another handle has refused the slot.
- Reject missing/corrupt markers and old-primary-without-marker recovery without creating new eligibility.
- Preserve exact idempotency and no-overwrite assertions. If an intentionally stricter refusal policy changes an old liveness expectation after an observed conflict, identify that semantic change explicitly; do not silently weaken or discard the old assertion.

No retry, deadline extension, synthetic Root identity, or reduced JUnit roster is part of this plan. UID0 tests must remain identified as unexecuted until the authorized actual Root runner produces fresh exact-source records.

## Limit of the guarantee

This protocol addresses an observed primary-data failure, an interrupted verification, and restoration of primary bytes while the independent protected refusal history remains. The underlying Root store explicitly does not promise protection against Root compromise or rollback of the whole protected host/store history. A loss of the storage required to durably arm or refuse must remain an error, not a claimed successful durable fence.
