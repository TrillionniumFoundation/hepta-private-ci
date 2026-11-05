# Canonical Intelligence process-loss recovery review

## Scope and result

Reviewed exact candidate `1d87082c0d5afd2b474a2c453ea98005fd540dea` (#4848 initial implementation), without changing the frozen A arithmetic patch or any remote source. This is a source review; no native build, Rust test, actual provider execution, or physical effect was run here.

The pending-write issue has two distinct layers:

1. The default Agentd canonical Intelligence path does not currently compose its Decision/Outcome writes through the authenticated `LedgerWriter`. It stops at owner preparation and transient run/context admission. There is no durable canonical handoff from that path to the actual App Server execution identity.
2. The old optional qualification path exposes an in-memory `PendingIntelligenceLedgerAppendV1`. Its reappend API needs that object and still-live authority state; losing the process loses the object. This cannot be fixed by persisting an Agentd-owned outbox and cannot be presented as completion of the default product path.

No self-contained production recovery fix was identified that can safely close those gaps by editing only the existing pending type. No new writer, outbox, executor, historical-authority fallback, or automatic redispatch was added.

## Source evidence

All paths below are relative to the repository, at the reviewed commit. `product-recovery-source-manifest.json` records the fetched blob identities for this review.

| Concern | Exact source | Observed behavior |
| --- | --- | --- |
| Default feature boundary | `codex-rs/hepta-agentd/Cargo.toml`, lines 13–22; `codex-rs/hepta-learning-ledger/Cargo.toml`, lines 16–18 | Agentd defaults to `production-cognitive-write`. Legacy learning writes require the separately named `qualification-legacy-learning-write`, forwarding the ledger's nondefault `qualification-legacy-write`. |
| Pending carrier | `hepta-agentd/src/intelligence_product.rs`, lines 715–727 | Pending stores predecessor, private canonical snapshot, and raw legacy event in an ordinary Clone/Debug struct. No durable publication or decoder is present. The public export alone is not an active production write path. |
| Optional legacy writes | `hepta-agentd/src/intelligence_product_runner.rs`, lines 273–385 | Decision, Outcome, append helper, and reconcile are feature-gated. Events are `LedgerEvent::Decision` / `Outcome`; append uses `DurableLedger::append_qualification`. The retry consumes the pending object. |
| Existing legacy test | `hepta-agentd/src/intelligence_product_tests.rs`, lines 660–795 | The gated test manually changes the coordinator to dispatched and terminal, appends legacy events, drops/reopens a ledger, then retries using the still-live prepared value. It does not call App Server or prove process-loss recovery of an original request. |
| Compiled canonical entry | `hepta-agentd/src/state.rs`, lines 620–718 | `start_canonical_intelligence` calls host invocation provider, checks the durable run identity, prepares seven owners, rechecks the current objective twice, then starts a transient run and attaches context. No authenticated Decision or Outcome append is performed there. |
| Ready result | `hepta-agentd/src/objective_submission.rs`, lines 21–47 | `FullObjectiveExecution` matches `Ready { .. }` and returns `canonical_ready`. This entry does not retain the prepared value or execute its proposed action through App Server. |
| Startup barrier | `hepta-agentd/src/objective_runtime.rs`, lines 111–145 | Reconciliation explicitly skips canonical Intelligence records until the exact seven-owner handoff is durably recovered. It waits for an authenticated ObjectiveStart retry instead of entering compatibility execution. |
| Current authority already exists | `hepta-agentd/src/state.rs`, lines 757–809 | `require_current_run_start` authenticates the stored original ingress signature against the current trust, expiry, generation, and exact fence. Reuse this; a journal fact is not current permission. |
| Existing run-start carrier | `hepta-learning-ledger/src/run_start.rs`, lines 43–125, 319–419, 506–537 | The owner durably stores original objective authentication/signature, objective bytes/digests, profile/source/deadline, and generation/fence. Its typed API appends immutable RunStart or hard conflict records, with exact idempotent replay. It has no post-preparation canonical handoff or execution/terminal update API. |
| Authenticated causal writer | `hepta-learning-ledger/src/production.rs`, lines 162–215, 260–282, 319–417, 654–709 | `LedgerWriter` owns its backend and independent witness. Typed Decision verifies Generator and completeness; typed Outcome verifies Observer, decision binding, independence, and time. Commit accepts only exact canonical replay when the witness is one record behind. |
| Durable recovery substrate | `hepta-learning-ledger/src/durable.rs`, lines 133–206 | Recovery validates the external acknowledged anchor before repairing a partial tail. I/O uncertainty poisons the old handle. Equal canonical retry never appends a new event. |
| Existing process-loss regression | `hepta-learning-ledger/src/production_tests.rs`, lines 707–813 | A child exits after ledger sync before witness. The parent reopens and exact-retries to advance the witness. The parent reconstructs a constant signed request from fixture keys; the test does not persist an original Agentd request across the process boundary. |
| Current lifecycle methods | `hepta-agentd/src/state_control.rs`, lines 499–547 | Mark-dispatched / observe-terminal update the transient coordinator and return a receipt. They are not durable authenticated learning Outcome writes and do not themselves establish an App Server terminal observation. |

Source links:

- [Agentd default features](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-agentd/Cargo.toml)
- [Canonical preparation and current run authentication](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-agentd/src/state.rs)
- [Objective submission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-agentd/src/objective_submission.rs)
- [Canonical restart barrier](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-agentd/src/objective_runtime.rs)
- [Legacy pending write path](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-agentd/src/intelligence_product_runner.rs)
- [Run-start owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-learning-ledger/src/run_start.rs)
- [Authenticated ledger owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-learning-ledger/src/production.rs)
- [Existing owner process-loss regression](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d87082c0d5afd2b474a2c453ea98005fd540dea/codex-rs/hepta-learning-ledger/src/production_tests.rs)

## What is sufficient today

- `DurableRunStartJournal` already owns immutable input identity and stores the exact original objective claims and signature. The Agentd host authenticates those bytes and revalidates them at the current use boundary; the journal itself is not an issuer or cryptographic verifier.
- `LedgerWriter::append_decision` and `append_outcome` are the existing authenticated fact writers. There is no need for an Agentd raw-event bypass.
- `LedgerWriter::verify_active_decision_binding` can reject an outcome linked to a different or revoked run/episode.
- Durable ledger/witness recovery, canonical idempotency, immutable predecessor checking, and poisoned-handle refusal already supply the append/reopen mechanics.
- Agentd already hosts the single App Server and maintains a transient coordinator. That coordinator can project recovered state, but its memory must not become the durable authority.
- Existing signed text recovery is lookup-only (`text_session_worker_recovery.rs::restore`), a useful behavior to preserve when correlating existing operations. It is not an Intelligence handoff implementation.

## Missing dependencies and smallest coherent closure

The smallest coherent implementation is a single canonical product composition using those owners. It requires an explicit durable handoff/replay contract, not an extra retry loop.

1. **Owner-owned handoff.** After preparation and before any effect admission, persist the exact canonical run/context identity, selected candidate and completeness, policy/support digests, the original typed Decision request, and its signed evidence under the learning-ledger owner. Bind it to the immutable RunStart digest, operation identity, and trust/fence references. The existing immutable RunStart cannot be rewritten to add this later: a changed record with the same run id is deliberately a conflict. A new typed owner record or another already-declared owner artifact with a verified reader is required. No such suitable write/read API was found in the inspected path.
2. **Default authenticated Decision composition.** Require the host to supply an authenticated `LedgerWriter` and the original Generator evidence; convert the prepared result into `ProductionDecisionV2` and use the typed append before proceeding. An advisory selected candidate, public principal id, or qualification receipt cannot manufacture the Generator signature or current authorization.
3. **Same App Server operation.** Pass the exact admitted context/action through the existing App Server and persist its owner-issued thread/turn/operation identity before treating dispatch as recoverable. Recovery must query that identity. An unrecorded/unknown acknowledgement must not create a new turn. The inspected canonical entry does not expose this handoff yet.
4. **Independent terminal evidence.** Obtain the terminal observation from the actual execution/effect owner, bind it to the active Decision and exact operation, obtain the appropriate Observer evidence, and append through `LedgerWriter::append_outcome`. Only then project the confirmed terminal state. Coordinator `terminal_observed: true` or a dispatch proposal digest alone does not supply this observation.
5. **Read/reconcile on restart.** Recover existing journals using their independent witnesses; load the original persisted signed handoff, revalidate current source/owner/trust and operation identity, then exact-retry only a pending fact append. If the execution owner reports unknown, retain indeterminate status and capacity. If current evidence has expired or been revoked, refuse new admission while retaining historical identity and evidence for reconciliation; do not re-sign a different request or silently advance an unwitnessed tail.

This requires producer, durable carrier, execution correlation, and observer integration. Adding only a serializable Agentd Pending struct would leave all four missing and would create a second fact store. Changing `LedgerWriter` to automatically bless an unwitnessed last record or accepting raw historic evidence under stale trust would bypass current protections. Neither was implemented.

The existing owner tests establish the substrate's intended behavior; they are not proof of real end-to-end execution. Before changing owner recovery semantics, the expiry/revocation policy for a historical exact retry must be made explicit. Current typed append revalidates signatures before commit, so expired/revoked evidence cannot simply be replayed as a new admission.

## Required regression and real qualification

A future narrow owner-carrier change should include a separate child process which persists the original request/signature, exits, and forces its parent to recover those bytes through the owner reader. Reconstructing a new request from fixture constants or retaining the prepared object in memory is insufficient.

The product composition must then demonstrate these concrete boundaries on the same actual implementation:

| Kill/failure point | Required restart behavior |
| --- | --- |
| RunStart synced; canonical handoff absent | No auto-dispatch or compatibility fallback. An authenticated retry may complete preparation only under current authority. |
| Handoff and Decision synced; dispatch not acknowledged | Reconcile the original operation identity; never issue a replacement turn based on uncertainty. |
| App Server/effect terminal exists; Outcome not appended | Read the original terminal evidence, verify its current binding, append the same typed Outcome once. |
| Learning event synced; witness lagging | Recover the original signed append request from the durable carrier; exact replay advances the witness without another event or effect. |
| Recovered evidence expired/revoked, generation changed, or payload differs | Fail closed with original identity retained; no fallback writer, new signature masquerading as replay, or automatic rerun. |
| Incomplete/corrupt/missing acknowledged history | Use existing owner rejection/partial-tail rules; never replace it with an empty journal. |

Native gates should use repository `just test` for the ledger/Agentd packages, and include the existing owner crash test plus new carrier/process tests. Actual provider/effect acceptance remains separate from deterministic source regressions.

## Qualification wording correction

The earlier qualification README mentioned only “Persistent recovery of the Intelligence pending Decision/Outcome append …”. That was accurate but incomplete: it could imply the default host already had a typed append path. The qualification README now records two explicit requirements: default canonical handoff and authenticated Decision/Outcome composition, then process-loss recovery of original signed append/operation identities. It identifies the old Pending object as optional qualification-only memory state.

No claim of completed execution, restoration, authority issuance, or deployment is added.
