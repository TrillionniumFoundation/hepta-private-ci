//! Actual published Version -> original read-only T/E alias mechanisms.
//! PublicationFixture performs its original T/B/NoUpdate publication. Its
//! same-process transport and enrolled fixture credentials are explicit;
//! these tests do not prove Fresh Root execution or public four-slot admission.

use super::*;
use crate::OriginalCellQ24TrainingCommandErrorV1 as TrainingError;
use crate::OriginalCircuitPublishedEvidenceReadbackV1 as Shared;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use crate::learning_iteration_evidence_client::command_test_support::shared_readback::ReadbackControl;
use crate::learning_iteration_evidence_client::command_test_support::shared_readback::{
    self as controlled_training,
};
use anyhow::Context as _;
use std::error::Error as StdError;
use std::time::Instant;

#[derive(Clone, Copy)]
enum TrainerServing {
    ControlledResponse,
    OriginalService,
}

struct Case {
    fixture: Option<PublicationFixture>,
    task: Option<support::Session>,
    held: Option<HeldPredecessors>,
    version: Option<Arc<Version>>,
    shared: Option<Shared>,
    dataset_peer: Option<material_ports::Peer>,
    trainer_peer: Option<TrainerPeer>,
    evaluator_peer: Option<std::thread::JoinHandle<anyhow::Result<u64>>>,
    control: Option<ReadbackControl>,
    trainer_deadline_upper_bound: Option<Instant>,
}

impl Case {
    async fn ready(trainer_lifetime: Duration, serving: TrainerServing) -> anyhow::Result<Self> {
        let fixture = Box::pin(PublicationFixture::ready()).await?;
        let mut case = Self {
            fixture: Some(fixture),
            task: None,
            held: None,
            version: None,
            shared: None,
            dataset_peer: None,
            trainer_peer: None,
            evaluator_peer: None,
            control: None,
            trainer_deadline_upper_bound: None,
        };
        if let Err(error) = Box::pin(case.initialize(trainer_lifetime, serving)).await {
            let cleanup = case.cleanup().await;
            return Err(error.context(format!("actual setup cleanup: {cleanup:?}")));
        }
        Ok(case)
    }

    async fn initialize(
        &mut self,
        trainer_lifetime: Duration,
        serving: TrainerServing,
    ) -> anyhow::Result<()> {
        let fixture = self
            .fixture
            .as_ref()
            .context("same actual publication fixture")?;
        let (held, peers) = Box::pin(held_predecessors(fixture)).await?;
        let original_dataset = held.dataset_receipt.clone();
        self.held = Some(held);
        self.dataset_peer = Some(peers.dataset);
        self.trainer_peer = Some(peers.trainer);
        self.evaluator_peer = Some(peers.evaluator);
        let (task, recovery) = Box::pin(publish_for_recovery(
            self.fixture
                .as_mut()
                .context("same actual publication fixture")?,
            &original_dataset,
        ))
        .await?;
        self.task = Some(task);

        // The parent helper's unbound T channel has performed no request.
        // Close and join it before constructing this cold test's one channel.
        // The completed publication, D/E connections and original T owner stay.
        let HeldPredecessors {
            dataset,
            dataset_receipt,
            trainer,
            evaluator,
        } = self
            .held
            .take()
            .context("same original cold predecessors")?;
        drop(trainer);
        let old = self
            .trainer_peer
            .take()
            .context("one unused original T peer")?
            .join()
            .map_err(|_| anyhow::anyhow!("unused original T peer panicked"))??;
        anyhow::ensure!(old == 0, "no request on the replaced unbound test channel");
        let fixture = self
            .fixture
            .as_ref()
            .context("same actual publication fixture")?;
        let (trainer, channel) = training_ports::recovered_peer(
            fixture.host.original.command_config.clone(),
            Some((
                fixture.training.receipt().clone(),
                fixture.training.attestation().clone(),
            )),
            trainer_lifetime,
        )?;
        // Both original channel endpoints already exist. Their actual ends
        // are no later than this bound; no client deadline is written here.
        self.trainer_deadline_upper_bound = Some(
            Instant::now()
                .checked_add(trainer_lifetime)
                .context("bounded original T lifetime")?,
        );
        self.trainer_peer = Some(match serving {
            TrainerServing::ControlledResponse => {
                let (control, peer) =
                    controlled_training::serve(Arc::clone(&fixture.trainer), channel);
                self.control = Some(control);
                peer
            }
            // Budget and deadline tests use the unchanged production service
            // loop through the existing same-process transport adapter.
            TrainerServing::OriginalService => {
                commands::serve(Arc::clone(&fixture.trainer), channel)
            }
        });
        self.held = Some(HeldPredecessors {
            dataset,
            dataset_receipt,
            trainer,
            evaluator,
        });
        let version = cold_version(
            fixture,
            self.held
                .take()
                .context("same original cold predecessors")?,
            recovery,
        )?;
        self.version = Some(Arc::clone(&version));
        // This is the production Published/current admission, not a test
        // constructor for a bundle or a supplied receipt used as a reply.
        self.shared = Some(Version::share_original_evaluated_readbacks(version).await?);
        Ok(())
    }

    fn shared(&self) -> anyhow::Result<&Shared> {
        self.shared
            .as_ref()
            .context("actual admitted shared original T/E")
    }

    fn control(&self) -> anyhow::Result<&ReadbackControl> {
        self.control
            .as_ref()
            .context("actual original T transport observer")
    }

    fn training(&self) -> anyhow::Result<&crate::OriginalCellQ24TrainingCommandReceiptV1> {
        Ok(&self
            .fixture
            .as_ref()
            .context("actual original T fixture")?
            .training)
    }

    fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let fixture = self
            .fixture
            .as_ref()
            .context("actual original publication")?;
        let mut bytes = fixture.publication_bytes()?;
        bytes.extend(fixture.host.original.predecessor_bytes()?);
        bytes.extend(fixture.host.upstream_files()?);
        bytes.extend(fixture.host.original_files()?);
        Ok(bytes)
    }

    fn c_has_no_new_work(&self) -> anyhow::Result<bool> {
        let fixture = self
            .fixture
            .as_ref()
            .context("actual original publication")?;
        let c = self.task.as_ref().context("same original C")?;
        Ok(c.cell.snapshot(&fixture.source_c.scope)?.revision == 0)
    }

    async fn require_original_training_still_current(&self) -> anyhow::Result<()> {
        let fixture = self.fixture.as_ref().context("actual original T fixture")?;
        let (client, channel) = commands::client(
            fixture.trainer_context.clone(),
            true,
            Some(fixture.training.clone()),
        )?;
        let peer = commands::serve(Arc::clone(&fixture.trainer), channel);
        let observed = client.readback().await;
        drop(client);
        let joined = peer
            .join()
            .map_err(|_| anyhow::anyhow!("actual control T peer panicked"));
        anyhow::ensure!(
            observed? == fixture.training,
            "the actual original T still returns the full same signature"
        );
        anyhow::ensure!(joined?? == 1, "one actual independent control read");
        // This independent control is never assigned back into the failed
        // bundle, and cannot restore its consumed channel or any alias.
        Ok(())
    }

    async fn cleanup(&mut self) -> anyhow::Result<Option<Result<u64, TrainingError>>> {
        if let Some(control) = &self.control {
            control.release_all();
        }
        drop(self.shared.take());
        drop(self.version.take());
        drop(self.held.take());
        // Join every held peer even when an earlier one has the expected
        // exhaustion/transport error. Parent HeldPeers::finish short-circuits.
        let dataset = self.dataset_peer.take().map(material_ports::finish);
        let trainer = self.trainer_peer.take().map(std::thread::JoinHandle::join);
        let evaluator = self
            .evaluator_peer
            .take()
            .map(std::thread::JoinHandle::join);
        let mut failures = Vec::new();
        if let Some(Err(error)) = dataset {
            failures.push(format!("original D peer: {error:?}"));
        }
        let trainer = match trainer {
            Some(Ok(terminal)) => Some(terminal),
            Some(Err(_)) => {
                failures.push("original T peer panicked".to_owned());
                None
            }
            None => None,
        };
        match evaluator {
            Some(Ok(Ok(_))) | None => {}
            Some(Ok(Err(error))) => failures.push(format!("original E peer: {error:?}")),
            Some(Err(_)) => failures.push("original E peer panicked".to_owned()),
        }
        if let Some(mut c) = self.task.take() {
            if let Err(error) = c.stop().await {
                failures.push(format!("original C stop: {error:?}"));
            }
            drop(c);
        }
        if let Some(fixture) = self.fixture.take()
            && let Err(error) = fixture.finish().await
        {
            failures.push(format!("actual publication fixture finish: {error:?}"));
        }
        if self
            .control
            .as_ref()
            .is_some_and(ReadbackControl::scheduling_failed)
        {
            failures.push("test scheduling observer failed or timed out".to_owned());
        }
        anyhow::ensure!(failures.is_empty(), "actual cleanup failures: {failures:?}");
        Ok(trainer)
    }

    async fn finish(mut self) -> anyhow::Result<Result<u64, TrainingError>> {
        self.cleanup()
            .await?
            .context("one actual original T terminal")
    }
}

impl Drop for Case {
    fn drop(&mut self) {
        // Normal and Result-error paths use cleanup above. During unwinding,
        // release the scheduling latch, close clients, and reap these peers.
        if let Some(control) = &self.control {
            control.release_all();
        }
        drop(self.shared.take());
        drop(self.version.take());
        drop(self.held.take());
        if let Some(peer) = self.dataset_peer.take() {
            let _ = material_ports::finish(peer);
        }
        if let Some(peer) = self.trainer_peer.take() {
            let _ = peer.join();
        }
        if let Some(peer) = self.evaluator_peer.take() {
            let _ = peer.join();
        }
    }
}

struct ReadTask {
    task: Option<tokio::task::JoinHandle<Result<(), VersionError>>>,
    abort: tokio::task::AbortHandle,
}

impl ReadTask {
    fn start(shared: Shared) -> Self {
        let task = tokio::spawn(async move { shared.read_original_predecessors().await });
        let abort = task.abort_handle();
        Self {
            task: Some(task),
            abort,
        }
    }

    fn cancel(&self) {
        self.abort.abort();
    }

    async fn finish(mut self) -> Result<Result<(), VersionError>, tokio::task::JoinError> {
        self.task.take().expect("one owned read task").await
    }
}

impl Drop for ReadTask {
    fn drop(&mut self) {
        self.abort.abort();
    }
}

fn unavailable_trainer(error: &VersionError) -> bool {
    // Preserve the original nested error type; do not match formatted text.
    let mut current: Option<&(dyn StdError + 'static)> = Some(error);
    while let Some(error) = current {
        if let Some(original) = error.downcast_ref::<TrainingError>() {
            return matches!(original, TrainingError::Unavailable);
        }
        current = error.source();
    }
    false
}

fn require_original_frames(control: &ReadbackControl, count: usize) -> anyhow::Result<()> {
    let frames = control.frames()?;
    anyhow::ensure!(frames.len() == count, "actual original request count");
    anyhow::ensure!(
        frames
            .iter()
            .enumerate()
            .all(|(offset, frame)| frame.completed && frame.request_id == (offset as u64) + 1),
        "contiguous original authenticated requests and actual Completed responses",
    );
    anyhow::ensure!(!control.scheduling_failed(), "the test gate did not fail");
    Ok(())
}

fn require_closed_terminal(
    terminal: Result<u64, TrainingError>,
    count: usize,
) -> anyhow::Result<()> {
    match terminal {
        Ok(actual) => anyhow::ensure!(actual == count as u64, "actual original EOF count"),
        // After an abandoned reply or expiry the original stream can either
        // observe EOF or its own transport error. The test separately proves
        // the slot and exact frame count; it never turns this error into PASS
        // for a command that was supposed to return a completed receipt.
        Err(TrainingError::Transport(_)) => {}
        Err(error) => anyhow::bail!("unexpected original T terminal: {error:?}"),
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_published_readback_alias_competition_uses_same_slot() -> anyhow::Result<()> {
    let case = Box::pin(Case::ready(
        Duration::from_secs(300),
        TrainerServing::ControlledResponse,
    ))
    .await?;
    let result = async {
        let before = case.bytes()?;
        let first = case.shared()?.clone();
        let second = first.clone();
        anyhow::ensure!(
            first.fixture_same_original_clients(&second),
            "both aliases hold the same actual T and E clients"
        );
        let start = case.control()?.frames()?.len();
        let mut pause = case.control()?.pause_after_next_original_response()?;
        let active = ReadTask::start(first);
        let observed = pause.entered().await?;
        anyhow::ensure!(
            observed == start as u64 + 1,
            "pause the next actual T response"
        );
        let refused = second.read_original_predecessors().await;
        anyhow::ensure!(
            matches!(&refused, Err(error) if unavailable_trainer(error)),
            "the competing alias must observe the original absent T slot"
        );
        require_original_frames(case.control()?, start + 1)?;
        pause.release();
        active
            .finish()
            .await
            .context("original winning read task")??;
        second.read_original_predecessors().await?;
        require_original_frames(case.control()?, start + 2)?;
        anyhow::ensure!(
            case.bytes()? == before,
            "readback changed no original journals"
        );
        anyhow::ensure!(case.c_has_no_new_work()?, "readback did not execute C");
        Ok::<_, anyhow::Error>(start + 2)
    }
    .await;
    let terminal = case.finish().await;
    let expected = result?;
    anyhow::ensure!(
        terminal?? == expected as u64,
        "same original peer EOF count"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_published_readback_cancelled_alias_cannot_restore_any_alias()
-> anyhow::Result<()> {
    let case = Box::pin(Case::ready(
        Duration::from_secs(300),
        TrainerServing::ControlledResponse,
    ))
    .await?;
    let result = async {
        let before = case.bytes()?;
        let shared = case.shared()?.clone();
        let alias = shared.clone();
        let start = case.control()?.frames()?.len();
        let mut pause = case.control()?.pause_after_next_original_response()?;
        let active = ReadTask::start(shared.clone());
        anyhow::ensure!(
            pause.entered().await? == start as u64 + 1,
            "the original owner produced its actual response before cancellation"
        );
        active.cancel();
        let cancelled = active.finish().await;
        anyhow::ensure!(
            matches!(cancelled, Err(error) if error.is_cancelled()),
            "the owning await was actually cancelled"
        );
        let refused_before_release = alias.read_original_predecessors().await;
        anyhow::ensure!(
            matches!(&refused_before_release, Err(error) if unavailable_trainer(error)),
            "all aliases observe None while the original reply is still held"
        );
        pause.release();
        let late_alias = shared.clone();
        for read in [&shared, &alias, &late_alias] {
            let refused = read.read_original_predecessors().await;
            anyhow::ensure!(
                matches!(&refused, Err(error) if unavailable_trainer(error)),
                "no alias reconnects or restores the abandoned T channel"
            );
        }
        require_original_frames(case.control()?, start + 1)?;
        case.require_original_training_still_current().await?;
        anyhow::ensure!(
            case.bytes()? == before,
            "cancellation did not rewrite original evidence"
        );
        anyhow::ensure!(case.c_has_no_new_work()?, "cancellation did not execute C");
        Ok::<_, anyhow::Error>(start + 1)
    }
    .await;
    let terminal = case.finish().await;
    require_closed_terminal(terminal?, result?)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_published_readback_aliases_share_original_128_frame_budget() -> anyhow::Result<()>
{
    let case = Box::pin(Case::ready(
        Duration::from_secs(300),
        TrainerServing::OriginalService,
    ))
    .await?;
    let result = async {
        let before = case.bytes()?;
        let shared = case.shared()?.clone();
        let alias = shared.clone();
        anyhow::ensure!(
            shared.fixture_same_original_clients(&alias),
            "same original clients"
        );
        let expected = case.training()?.clone();
        let next = shared
            .fixture_original_trainer_next_request_id()?
            .context("the original service's actual channel is present")?;
        let consumed = usize::try_from(
            next.checked_sub(1)
                .context("original request ids start at one")?,
        )?;
        anyhow::ensure!(
            consumed > 0 && consumed < 128,
            "actual Version admission spent original frames"
        );
        // Exercise only T through a cfg(test) read-only method. Calling the
        // full bundle 128 times would first exhaust the older B fixture's own
        // 64-frame evidence peers and would not isolate this T transport limit.
        for offset in consumed..128 {
            let reader = if offset % 2 == 0 { &shared } else { &alias };
            let original = reader.fixture_read_original_trainer().await?;
            anyhow::ensure!(
                original == expected,
                "every frame reads the same full original T"
            );
        }
        anyhow::ensure!(
            shared.fixture_original_trainer_next_request_id()? == Some(129)
                && alias.fixture_original_trainer_next_request_id()? == Some(129),
            "all aliases spent the same original 128 requests",
        );
        let new_alias = shared.clone();
        anyhow::ensure!(
            matches!(
                new_alias.fixture_read_original_trainer().await,
                Err(TrainingError::CommitUncertain)
            ),
            "a new alias cannot obtain frame 129 from the exhausted original peer"
        );
        for reader in [&shared, &alias, &new_alias] {
            anyhow::ensure!(
                matches!(
                    reader.fixture_read_original_trainer().await,
                    Err(TrainingError::Unavailable)
                ),
                "exhaustion leaves the one original slot consumed for every alias"
            );
        }
        for reader in [&shared, &alias, &new_alias] {
            anyhow::ensure!(
                reader.fixture_original_trainer_next_request_id()?.is_none(),
                "no exhausted alias retains an original channel"
            );
        }
        anyhow::ensure!(
            case.bytes()? == before,
            "bounded reads changed no original journals"
        );
        anyhow::ensure!(case.c_has_no_new_work()?, "bounded reads did not execute C");
        Ok::<_, anyhow::Error>(())
    }
    .await;
    let terminal = case.finish().await;
    result?;
    anyhow::ensure!(
        matches!(terminal?, Err(TrainingError::Unavailable)),
        "the actual original server exhausted its unchanged 128-frame loop"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_published_readback_clone_cannot_renew_original_absolute_deadline()
-> anyhow::Result<()> {
    // A legal shorter lifetime is supplied to the existing connection factory
    // before binding or sharing. No frozen receipt or live deadline is edited.
    let case = Box::pin(Case::ready(
        Duration::from_secs(10),
        TrainerServing::OriginalService,
    ))
    .await?;
    let result = async {
        let before = case.bytes()?;
        let shared = case.shared()?.clone();
        let original = shared.fixture_read_original_trainer().await?;
        anyhow::ensure!(
            &original == case.training()?,
            "original T read before its actual deadline"
        );
        let next = shared
            .fixture_original_trainer_next_request_id()?
            .context("the original deadline has not yet consumed the channel")?;
        let count = usize::try_from(
            next.checked_sub(1)
                .context("original request ids start at one")?,
        )?;
        let expired_at = case
            .trainer_deadline_upper_bound
            .context("original channel's fixed upper end")?;
        tokio::time::sleep_until(tokio::time::Instant::from_std(expired_at)).await;
        let late_alias = shared.clone();
        anyhow::ensure!(
            shared.fixture_same_original_clients(&late_alias),
            "late cloning still holds the same original clients"
        );
        anyhow::ensure!(
            shared.fixture_original_trainer_next_request_id()? == Some(next)
                && late_alias.fixture_original_trainer_next_request_id()? == Some(next),
            "time and cloning did not construct another channel or reset its request id",
        );
        anyhow::ensure!(
            matches!(
                late_alias.fixture_read_original_trainer().await,
                Err(TrainingError::CommitUncertain)
            ),
            "the late alias cannot extend the original transport deadline"
        );
        anyhow::ensure!(
            matches!(
                shared.fixture_read_original_trainer().await,
                Err(TrainingError::Unavailable)
            ),
            "expiry consumes the same original slot"
        );
        anyhow::ensure!(
            shared.fixture_original_trainer_next_request_id()?.is_none()
                && late_alias
                    .fixture_original_trainer_next_request_id()?
                    .is_none(),
            "all aliases lose the same expired channel",
        );
        case.require_original_training_still_current().await?;
        anyhow::ensure!(
            case.bytes()? == before,
            "expiry did not rewrite original evidence"
        );
        anyhow::ensure!(case.c_has_no_new_work()?, "expiry did not execute C");
        Ok::<_, anyhow::Error>(count)
    }
    .await;
    let terminal = case.finish().await;
    require_closed_terminal(terminal?, result?)?;
    Ok(())
}
