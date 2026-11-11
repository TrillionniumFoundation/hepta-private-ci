//! Installation belongs to the original required worker. Cancellation fences
//! immediately, then joins any original owner action already in progress.

use codex_hepta_automation::AutomationStore;
use tokio_util::sync::CancellationToken;
use super::*;
use crate::AgentdState;

pub(crate) struct PendingSuccessorOwner {
    context: Arc<OriginalQ24SuccessorContext>,
    slot: Arc<SuccessorSlot>,
    receiver: Option<oneshot::Receiver<Installation>>,
    capacity: usize,
    _lifetime: CloseOnDrop,
}

impl PendingSuccessorOwner {
    pub(super) fn new(
        context: Arc<OriginalQ24SuccessorContext>,
        slot: Arc<SuccessorSlot>,
        receiver: oneshot::Receiver<Installation>,
        capacity: usize,
    ) -> Self {
        Self { context, slot: Arc::clone(&slot), receiver: Some(receiver), capacity,
            _lifetime: CloseOnDrop::new(&slot) }
    }

    pub(crate) async fn run(
        mut self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let slot = Arc::clone(&self.slot);
        let work = async {
            let runtime = self.install_original_successor(Arc::clone(&state)).await.map_err(|error| AgentdError::Protocol(error.to_string()))?;
            runtime.run_in_original_successor_lane(store, state, slot.closed.clone()).await
        };
        tokio::pin!(work);
        tokio::select! {
            result = &mut work => result,
            _ = cancellation.cancelled() => {
                slot.close();
                // Never drop a future which may already have prepared CURRENT,
                // consumed FinalUse or created the original Source/Cell owner.
                work.await
            }
        }
    }

    async fn install_original_successor(&mut self, state: Arc<AgentdState>) -> Result<CircuitTaskRuntimeBootstrapV1, Error> {
        let receiver = self.receiver.take().ok_or(Error::CommitUncertain)?;
        let command = tokio::select! {
            _ = self.slot.closed.cancelled() => return Err(Error::Binding("successor is closed")),
            command = receiver => command.map_err(|_| Error::Binding("successor sender was dropped"))?,
        };
        let Installation { driver, predecessor, target, execution, quoted, grant, completed, _work } = command;
        let result = self.prepare_original_worker(driver, predecessor, target, &execution, Arc::clone(&state)).await;
        let original = match result {
            Ok(original) => original,
            Err(error) => {
                self.slot.close();
                let _ = quoted.send(Err(error));
                return Err(Error::CommitUncertain);
            }
        };
        let quote = Quote { binding: original.prepared.final_use_binding().clone(), intent: original.prepared.intent_digest() };
        if self.slot.require_open().is_err() || quoted.send(Ok(quote)).is_err() {
            self.slot.close();
            return Err(Error::CommitUncertain);
        }
        let result = self.finish_original_worker(original, execution, grant, Arc::clone(&state)).await.map_err(prepared_uncertain);
        match result {
            Ok((runtime, invocation, installed)) => {
                if self.slot.install_original_owner(runtime.handle(), invocation).is_err() {
                    self.slot.close();
                    let _ = completed.send(Err(prepared_uncertain(Error::CommitUncertain)));
                    return Err(Error::CommitUncertain);
                }
                if completed.send(Ok(installed)).is_err() {
                    self.slot.close();
                    return Err(Error::CommitUncertain);
                }
                // Queue/active count falls only after original postconditions and
                // final installation. The ordinary driver counts all later C work.
                drop(_work);
                Ok(runtime)
            }
            Err(error) => {
                self.slot.close();
                let _ = completed.send(Err(error));
                Err(Error::CommitUncertain)
            }
        }
    }

    async fn prepare_original_worker(
        &self,
        driver: OriginalCellQ24RootPublicationDriverV1,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
        execution: &OriginalQ24SuccessorExecutionInputsV1,
        state: Arc<AgentdState>,
    ) -> Result<crate::cell_q24_publication_driver::OriginalSuccessorPublication, Error> {
        self.slot.require_open().map_err(|_| Error::CommitUncertain)?;
        self.slot.require_decision(driver.original_successor_decision())?;
        state::remaining(self.context.initial().request.envelope.expiry_unix_seconds)?;
        crate::cell_q24_publication_driver::require_successor_admission(&state, self.context.identity())?;
        execution.validate_original_successor_execution(self.context.identity(), &target, self.capacity)?;
        self.context.require_current_successor_context().await?;
        self.slot.require_open().map_err(|_| Error::CommitUncertain)?;
        driver.prepare_in_original_successor_worker(Arc::clone(&self.context), predecessor, target, state, Arc::clone(&self.slot)).await
    }

    async fn finish_original_worker(
        &self,
        original: crate::cell_q24_publication_driver::OriginalSuccessorPublication,
        execution: OriginalQ24SuccessorExecutionInputsV1,
        grant: oneshot::Receiver<SignedFinalUseGrant>,
        state: Arc<AgentdState>,
    ) -> Result<(CircuitTaskRuntimeBootstrapV1, Arc<crate::DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>, OriginalQ24InstalledSuccessorV1), Error> {
        let signed = tokio::select! {
            _ = self.slot.closed.cancelled() => return Err(Error::CommitUncertain),
            result = tokio::time::timeout(state::remaining(self.context.initial().request.envelope.expiry_unix_seconds)?, grant) => {
                result.map_err(|_| Error::CommitUncertain)?.map_err(|_| Error::CommitUncertain)?
            }
        };
        original.proof.require_current_successor_publication().await?;
        self.slot.require_open().map_err(|_| Error::CommitUncertain)?;
        crate::cell_q24_publication_driver::require_successor_admission(&state, self.context.identity())?;
        let task = original.prepared.publish_successor_current(signed, Arc::clone(&state), self.context.identity().clone(), Arc::clone(&self.slot)).await?;
        original.proof.require_current_successor_publication().await?;
        self.slot.require_open().map_err(|_| Error::CommitUncertain)?;
        crate::cell_q24_publication_driver::require_successor_admission(&state, self.context.identity())?;
        let opened = execution.open_original_successor_channel(self.context.identity(), task,
            original.bundle, original.model, self.capacity)?;
        original.proof.require_current_successor_publication().await?;
        self.slot.require_open().map_err(|_| Error::CommitUncertain)?;
        crate::cell_q24_publication_driver::require_successor_admission(&state, self.context.identity())?;
        Ok(opened)
    }
}
