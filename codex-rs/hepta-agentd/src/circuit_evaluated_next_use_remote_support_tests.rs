//! Test-only transport with the same original task, Selector, and T/B peers.
//! All replies come from actual owners; enrollment/process separation is a fixture.

use super::*;

use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as reads;

pub(super) type TaskHost =
    OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;
pub(super) type TaskPeer = std::thread::JoinHandle<Result<u64, ReadError>>;

pub(super) fn task_peer(
    c: &support::Session,
    context: ReadContext,
) -> anyhow::Result<(Arc<TaskHost>, OriginalCircuitLearningReadClientV1, TaskPeer)> {
    let host = Arc::new(TaskHost::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context.clone(),
    )?);
    let (client, channel) = reads::evaluated_client(context)?;
    let peer = reads::serve(Arc::clone(&host), channel);
    Ok((host, client, peer))
}

pub(super) struct RemoteSelector {
    pub(super) files: SelectorFiles,
    pub(super) selected: OriginalCircuitEvaluatedSelectionReceiptV1,
    pub(super) live: Arc<OriginalCircuitLearningReadClientV1>,
    pub(super) task_host: Arc<TaskHost>,
    pub(super) task_thread: TaskPeer,
    pub(super) host:
        Arc<OriginalCircuitEvaluatedSelectionRemoteReadbackOwnerV1<FileAnchorWitnessStore>>,
    pub(super) client: crate::LearningIterationEvidenceClientV1,
    pub(super) thread:
        std::thread::JoinHandle<Result<u64, OriginalCircuitEvaluatedSelectionReadbackErrorV1>>,
}

impl RemoteSelector {
    pub(super) async fn from_original(
        f: &PublicationFixture,
        c: &support::Session,
        trainer: &Arc<OriginalCellQ24TrainingCommandClientV1>,
        evaluator: &Arc<OriginalCellEvaluationCommandClientV1>,
        invalidate_source_after_read: Option<(u64, File)>,
    ) -> anyhow::Result<Self> {
        let (task_host, live, task_thread) =
            task_peer(c, ReadContext::for_original_selection(f.context()?)?)?;
        let live = Arc::new(live);
        let files = SelectorFiles::new()?;
        let mut owner = files.owner(f, OpenReceipt::Fresh)?;
        let selected = owner
            .attest_original_evaluated_remote_selection(
                OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                    snapshot: f.evaluation.snapshot(),
                    live: &live,
                    trainer,
                    evaluator,
                },
            )
            .await?;
        // This consumes the same original S custody. The original 4cut task
        // read client and both T/B clients are retained without reconnecting.
        let host = Arc::new(owner.into_evaluated_remote_readback_owner(
            selected.clone(),
            Arc::clone(&live),
            Arc::clone(trainer),
            Arc::clone(evaluator),
        )?);
        host.fixture_reject_wrong_requests()?;
        let (client, thread) = host.fixture_original_client(invalidate_source_after_read)?;
        Ok(Self {
            files,
            selected,
            live,
            task_host,
            task_thread,
            host,
            client,
            thread,
        })
    }
}

pub(super) fn remote_sources<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    live: &'a OriginalCircuitLearningReadClientV1,
    trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    evaluator: &'a OriginalCellEvaluationCommandClientV1,
    selector: &'a crate::LearningIterationEvidenceClientV1,
) -> crate::OriginalCircuitEvaluatedNextUseRemoteSourcesV1<'a> {
    crate::OriginalCircuitEvaluatedNextUseRemoteSourcesV1 {
        snapshot,
        live,
        trainer,
        evaluator,
        selector,
    }
}
