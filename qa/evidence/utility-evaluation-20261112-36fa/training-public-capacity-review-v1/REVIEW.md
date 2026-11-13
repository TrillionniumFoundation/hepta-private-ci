# Bootstrap public connection capacity — exact cc57 source review

**The existing public service contracts cannot close the described complete evaluated route within four simultaneous Trainer sessions merely by releasing each completed stage.** Two B members can already share one local read-only `Arc` through an existing production type. Version, Selector and NextUse currently retain separate by-value Trainer clients and continue using them. No limit or production source was changed for this review.

This is a static, source-bound liveness/resource finding, not an observed public `Busy` failure. No new H request, Cargo, test or gate ran. The fixed canonical source is `cc57c7198db6293ccca562253c42fffbe2a04633` / `b7b357c07b5539769a068c6b9b009629f5612d1e`. `SOURCE_REFERENCES.json` binds every local reference to that inventory. Unformatted provider/fixture proposals are not treated as executed products.

## Where the four permits are held

`cell_q24_training_bootstrap.rs::bind_original_custody` creates `connections: Arc<Semaphore>` with four permits. All three public surfaces use that same field:

| Public surface | Purpose | Permit lifetime |
| --- | --- | --- |
| `serve_commands` in `cell_q24_training_bootstrap_service.rs` | Original T Execute/Readback | Acquired before dispatch and moved into the entire blocking serve loop |
| `serve_candidate_material_readback` in `cell_q24_training_bootstrap_candidate.rs` | Separate Candidate page purpose | Acquired before dispatch and held through the complete session |
| `serve_original_training_readback` in `cell_q24_training_bootstrap_readback.rs` | Separate evidence-only T purpose | Acquired before dispatch and held through the complete session |

A successful response does not return a permit. The client puts the same channel back into its private slot. A permit is released only when its actual server loop exits and the captured permit drops, including EOF/error/request exhaustion. Dropping a waiting async task is not proof that already-running `spawn_blocking` I/O and its permit stopped. The private `*_channel` fixture helpers bypass this public admission boundary and cannot prove its capacity.

## Retained consumers and the overlap

| Consumer | Actual retained capability | Why it remains needed |
| --- | --- | --- |
| Root common Training | `Continuation.trainer: Option<OriginalCellQ24TrainingCommandClientV1>` | `read_prefix` calls `read_stage(Training)` and rereads the actual owner. The fresh T response is not a permanent currentness token. |
| Root Candidate | `CandidateLane.client: Option<OriginalCellQ24CandidateReadbackClientV1>` | Successful reads retain the channel. `EvaluatedContinuation::refresh` calls `read_original_evaluation`, which calls `read_original_candidate`; the 4/5/6-cut retained route continues using it. |
| Primary B | `PanelMemberOwners.trainer: Arc<LearningIterationEvidenceClientV1>` | Every panel `read_original` rebuilds Qualification sources and rereads the actual T signature. |
| Retention B | Same type | Its later CURRENT checks are also real owner reads; completing E does not free this dependency. |
| Version | `initial_trainer` then `trainer`, or the same client inside Prepared | `require_cut_current` reads actual D/T/E. Prepare consumes it into Prepared; successful publish returns the same T/E and stores them back. Later readback continues using them. |
| Selector | `OriginalPredecessors::Evaluated { trainer, evaluator }` by value | Every `observe_original`, including evidence readback, uses the original T/E sources. |
| NextUse | Same by-value T/E plus Selector evidence client | Every observation rereads T/E/S. Reading S also invokes S's own currentness checks. |

If each retained consumer is supplied its own live public Trainer session, the described topology needs **seven**, not four. Sharing the two B references through the already-existing local Arc lowers that requirement to **six**. With Root T, Candidate and one B session retained, Version uses the fourth permit; adding the current S/C owner sessions cannot be made legal by calling their factories later while discarding earlier required live predecessors.

This is a count of the described retained public-session topology, not a claim that seven sessions actually ran, and not a global count of every possible deployment. The selected Source/Cell, E and Model services have other connections; they are not added to this Trainer pool merely because they participate in the same route.

## What is already legal for B

`neuron_cell_evaluation_panel_member.rs` already stores `Arc<LearningIterationEvidenceClientV1>`. Its `read_original` uses `self.trainer.as_ref()` for the unchanged Qualification source. `neuron_cell_evaluation_panel.rs::read_members` awaits primary and retention reads in sequence. `neuron_cell_evaluation_qualification_sources.rs::read_trainer` still checks the actual complete signature equals the preregistered one.

Consequently, two member objects in the same actual Evaluation host can retain Arc clones of **one already authenticated, purpose-bound read-only T client**. This creates no new channel, writer, signature, pidfd, request counter or time window. It does not merge their task data, independent execution owners, cohorts or qualification results. The eight-file test facade happened to wrap two separate by-value clients; that is a fixture API choice, not an existing production requirement for two Trainer connections.

The original evidence backend takes its single channel before awaiting and restores it only after successful authentication. Arc is not a queue or permission to perform conflicting concurrent requests: an overlapping read may fail because the slot is occupied. The existing panel's sequential read order must remain. A shared physical session also has **one aggregate 128-request budget** and the original nonrenewed lifetime, not 128 requests per Arc. This review did not execute or prove the complete route fits that aggregate request/time budget.

## Why Version/S/C need a distinct proposal

Their existing constructors consume `OriginalCellQ24TrainingCommandConnectionV1` or `OriginalCellQ24TrainingCommandClientV1`; they do not accept an Arc or expose a legal client-return interface for arbitrary sequential reuse. The current command client also exposes Execute, so adding unrestricted Clone or returning its inner Arc would be the wrong attenuation boundary.

Ordinary's narrower proposal is source-feasible **only as a separately reviewed change**: after actual successful evaluated publication, Version consumes its retained T/E into sealed, read-only shared capabilities and retains the same capabilities for its own subsequent checks. S/C in the same already-authorized actual receiver process could then receive read-only handles to those same physical channels. Existing by-value/fresh interfaces should remain independent. There must be no Deref, FD getter, new stream, reset nonce, replacement pidfd, new deadline, cached-evidence substitution or inherited Execute capability.

Source transition checks for that possible proposal:

- `prepare_original` is Fresh-only and guarded by `preparation_requested.swap(true)` plus Awaiting-to-Prepared consumption. Successful publication does not later need another Prepare or another T Execute.
- `publish_original_final_use` has a one-shot publication guard; it moves the Prepared object, receives the same T/E back, installs state, performs final actual reads and only then sets Published. An Installed phase and a reader may already exist before a late failure: they are not sufficient export conditions.
- Recovered construction starts with a Published enum, so that enum alone is also insufficient. Existing `read_original_recovery` requires actual D/T/E, Artifact and held C owner reads before installing a reader; a later export must repeat the complete original currentness/lifetime checks and retain the same recovered restrictions.
- Any Owned-to-Shared conversion must happen once under the same state lock, preserve the actual complete signatures/context and leave failures fail-closed. Sharing must not resurrect a consumed Prepared or permit fresh recovery.
- A shared exchange lock must protect the one request counter/channel/error state. It must not be held across outer S/C callbacks that can recursively read their own predecessors. Preserve the original globally consumed/uncertain behavior on cancellation and authentication failure.

## Actual process identity is a prerequisite, not metadata

`learning_owner_command_channel.rs::original_owner_command_channel_v1` refuses same UID and same process, checks boot ID and start ticks, binds the supplied original pidfd and HostAuthorityPeerChannel credentials, then rechecks liveness. It keeps at most 30 seconds per command exchange and 300 seconds per original session. The readonly T and Candidate purposes are distinct wire values and cannot be interchanged to save a permit.

B's Arc sharing is local to the actual panel host that owns both members. Version/S/C sharing is only a valid design candidate when their original capabilities can already reside in the **same real consumer process under the trusted placement contract**. Arc does not cross a process boundary. Forwarding/duplicating a socket to a different peer, fabricating a pidfd/identity, or inserting a new proxy cannot establish that placement. Root's own T/Candidate streams remain separately authenticated original sessions.

## Required validation and remaining limits

The new completion observer and staged test fixture do not resolve public capacity. A full real-owner test must use the public serve entrypoints, keep actual UID/process/pidfd checks, assert no fifth permit is admitted, retain every required live predecessor, and complete or reject using original request counts/deadlines. It must include withdrawal, repeated currentness, cancellation, EOF and shared-channel error propagation without cloning fresh Execute or raising four/128/300-second limits. No such test has run in this review. Real task/authority evidence and real independent B utility remain separate from mechanism tests.
