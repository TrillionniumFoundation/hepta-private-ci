//! A new recipient's bounded delivery of the same Root-observed historical A.
//! This retains no old writer or Automation outbox. A new explicit journal
//! witnesses dispatch; prior Pending permits only the original Root readback.

use std::fs::File;
use std::time::Instant;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::*;
use crate::CellQ24PreparedLearningV1;
use crate::OriginalCellQ24LearningOpenV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as JournalError;
use crate::learning_owner_journal::LearningOwnerJournalV1;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1;

pub(crate) struct RegisteredHistoricalLearningSourceV1 {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
    prepared: Arc<CellQ24PreparedLearningV1>,
    identity: AgentdIdentity,
    end: Instant,
}

impl RegisteredHistoricalLearningSourceV1 {
    pub(crate) fn capture_original_historical_source(
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        prepared: Arc<CellQ24PreparedLearningV1>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &crate::AgentdRootAuthoritySession,
        identity: AgentdIdentity,
        end: Instant,
    ) -> Result<Arc<Self>, AgentdError> {
        receipt.require_original_client(client, session)?;
        if receipt.initial_snapshot().request.agent_id.as_str() != identity.agent_id.as_str() {
            return Err(refused("original recipient agent differs"));
        }
        let source: Arc<RegisteredHistoricalLearningSourceV1> = Arc::new(Self {
            receipt,
            prepared,
            identity,
            end,
        });
        source.require_current_historical_source(&source.identity)?;
        source.receipt.require_original_client(client, session)?;
        Ok(source)
    }

    pub(crate) fn require_current_historical_source(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        if identity != &self.identity || Instant::now() >= self.end {
            return Err(refused("historical recipient or original end differs"));
        }
        self.prepared
            .require_original_historical_source(&self.receipt)
            .map_err(refused)?;
        if Instant::now() >= self.end {
            return Err(refused("historical source deadline"));
        }
        Ok(())
    }

    pub(crate) fn require_prepared_historical_source(
        &self,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<(), AgentdError> {
        if !std::ptr::eq(self.prepared.as_ref(), prepared) {
            return Err(refused("different actual prepared Dataset owner"));
        }
        self.require_current_historical_source(&self.identity)
    }

    pub(crate) fn request(&self) -> &LearningIterationRequestV1 {
        &self.prepared.initial().request
    }
}

pub(crate) struct OriginalHistoricalLearningDeliveryV1 {
    source: Arc<RegisteredHistoricalLearningSourceV1>,
    journal: LearningOwnerJournalV1<FileAnchorWitnessStore>,
    key: ProductEvaluationExecutionKeyV1,
    continuation: Option<crate::production_launcher::OriginalPostAContinuationV1>,
}

impl LearningIterationRuntimeBootstrapV1 {
    pub(crate) fn with_original_historical_source(
        mut self,
        source: Arc<RegisteredHistoricalLearningSourceV1>,
        identity: &AgentdIdentity,
        journal: File,
        witness: FileAnchorWitnessStore,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let original: &Arc<crate::OriginalCellQ24LearningStageOwnersV1> = self
            .original_q24
            .as_ref()
            .ok_or_else(|| refused("actual assembled Q24 owners absent"))?;
        let prepared = original.prepared();
        source.require_prepared_historical_source(prepared)?;
        let registry = self
            .circuit_delivery_registry
            .as_ref()
            .ok_or_else(|| refused("original source registry absent"))?;
        if self.retained_source.is_some()
            || self.historical_source.is_some()
            || self.historical_delivery.is_some()
            || !self.enforce_circuit_admission
            || !matches!(
                self.circuit_delivery_source,
                CircuitLearningSourceV1::OriginalQ24
            )
            || self.scope.as_ref() != Some(prepared.scope())
            || self.owners != prepared.initial().owners
            || registry.requests.as_slice() != std::slice::from_ref(source.request())
        {
            return Err(refused(
                "historical delivery differs from original Root assembly",
            ));
        }
        source.require_current_historical_source(identity)?;
        let key = ProductEvaluationExecutionKeyV1 {
            plan_id: source.request().operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-historical-learning-delivery.v1\0",
                crate::neuron_generation_process_identity_digest_v1(identity)?.as_array(),
                prepared.initial().head_digest.as_array(),
                prepared.scope().binding().as_array(),
            ]),
        };
        let journal = match mode {
            OriginalCellQ24LearningOpenV1::Create => {
                LearningOwnerJournalV1::create(journal, witness, key.binding_digest)
            }
            OriginalCellQ24LearningOpenV1::Recover => {
                LearningOwnerJournalV1::recover(journal, witness, key.binding_digest)
            }
        }
        .map_err(refused)?;
        source.require_current_historical_source(identity)?;
        self.historical_source = Some(Arc::clone(&source));
        self.historical_delivery = Some(OriginalHistoricalLearningDeliveryV1 {
            source,
            journal,
            key,
            continuation: None,
        });
        Ok(self)
    }

    pub(crate) fn with_original_post_a_continuation(
        mut self,
        continuation: crate::production_launcher::OriginalPostAContinuationV1,
        identity: &AgentdIdentity,
    ) -> Result<Self, AgentdError> {
        self.require_identity(identity)?;
        let owners = self
            .original_q24
            .as_ref()
            .ok_or_else(|| refused("original Q24 aggregate absent"))?;
        let delivery = self
            .historical_delivery
            .as_mut()
            .ok_or_else(|| refused("original historical delivery absent"))?;
        if delivery.continuation.is_some() {
            return Err(refused("original post-A continuation already installed"));
        }
        crate::production_launcher::OriginalPostAContinuationV1::require_original_delivery(
            &continuation,
            &delivery.source,
            owners,
            identity,
        )?;
        delivery.continuation = Some(continuation);
        Ok(self)
    }
}

impl OriginalHistoricalLearningDeliveryV1 {
    pub(super) fn require_original_source(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.source.require_current_historical_source(identity)
    }

    pub(super) async fn run(
        mut self,
        handle: LearningIterationHandleV1,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let Some(continuation) = self.continuation.take() else {
            return self.run_delivery(handle, state, cancellation).await;
        };
        let joined = cancellation.child_token();
        let delivery_cancelled = joined.clone();
        let continuation_cancelled = joined.clone();
        let delivery = self.run_delivery(handle, Arc::clone(&state), joined.clone());
        let continuation = crate::production_launcher::OriginalPostAContinuationV1::run(
            continuation,
            state,
            joined,
        );
        // Both owned futures remain joined after an error or shutdown. An
        // original publisher or issuer already in progress is never detached.
        let (delivery, continuation) = tokio::join!(
            async {
                let result = delivery.await;
                if result.is_err() {
                    delivery_cancelled.cancel();
                }
                result
            },
            async {
                let result = continuation.await;
                if result.is_err() {
                    continuation_cancelled.cancel();
                }
                result
            },
        );
        delivery?;
        continuation
    }

    async fn run_delivery(
        mut self,
        handle: LearningIterationHandleV1,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(Duration::from_millis(50)) => {}
            }
            if require_ready(&state).is_ok() && state.automation_admission_ready()? {
                break;
            }
            if Instant::now() >= self.source.end {
                return Err(refused("historical delivery deadline"));
            }
        }
        self.source
            .require_current_historical_source(state.identity())?;
        // This supervised future owns the journal across dispatch. Cancellation
        // or an abort drops that same owner; its witnessed Pending is retained.
        let reservation = handle.reserve().map_err(refused)?;
        let existing = self.journal.read(&self.key);
        let snapshot = match existing {
            Ok(saved) => {
                let snapshot = self.readback(reservation, &cancellation).await?;
                if saved.as_slice() != snapshot.head_digest.as_array() {
                    return Err(refused("original delivery head differs"));
                }
                snapshot
            }
            Err(JournalError::Pending) => self.readback(reservation, &cancellation).await?,
            Err(JournalError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                let source = Arc::clone(&self.source);
                let mut observed = None;
                let observed_snapshot = &mut observed;
                let state = Arc::clone(&state);
                let cancelled = &cancellation;
                self.journal.commit_original_historical_delivery(&self.key, move || async move {
                        source.require_current_historical_source(state.identity()).map_err(|_| JournalError::Binding("post-claim historical source"))?;
                        let result = tokio::select! {
                                _ = cancelled.cancelled() => Err(LearningIterationRuntimeErrorV1::CommitUncertain),
                                result = tokio::time::timeout_at(source.end.into(), reservation.submit(source.request().clone())) =>
                                    result.unwrap_or(Err(LearningIterationRuntimeErrorV1::CommitUncertain)),
                            }.map_err(|_| JournalError::Pending)?;
                        require_complete(&source, &result).map_err(|_| JournalError::Binding("original Root delivery is incomplete"))?;
                        source.require_current_historical_source(state.identity()).map_err(|_| JournalError::Binding("post-dispatch historical source"))?;
                        let bytes = result.head_digest.as_array().to_vec();
                        *observed_snapshot = Some(result);
                        Ok(bytes)
                    }).await.map_err(refused)?;
                observed
                    .ok_or_else(|| refused("new delivery did not execute its original claim"))?
            }
            Err(error) => return Err(refused(error)),
        };
        require_complete(&self.source, &snapshot)?;
        self.source
            .require_current_historical_source(state.identity())?;
        cancellation.cancelled().await;
        Ok(())
    }

    async fn readback(
        &self,
        reservation: LearningIterationReservationV1<'_>,
        cancellation: &CancellationToken,
    ) -> Result<LearningIterationSnapshotV1, AgentdError> {
        self.source
            .require_current_historical_source(&self.source.identity)?;
        let result = tokio::select! {
            _ = cancellation.cancelled() => return Err(refused("original historical readback cancelled")),
            result = tokio::time::timeout_at(self.source.end.into(), reservation.readback(self.source.request().clone())) => result,
        }.map_err(refused)?.map_err(refused)?;
        require_complete(&self.source, &result)?;
        self.source
            .require_current_historical_source(&self.source.identity)?;
        Ok(result)
    }
}

fn require_complete(
    source: &RegisteredHistoricalLearningSourceV1,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<(), AgentdError> {
    if snapshot.request != *source.request() || snapshot.owners != source.prepared.initial().owners
    {
        return Err(refused("historical Root snapshot differs"));
    }
    source
        .prepared
        .scope()
        .validate_snapshot(snapshot)
        .map_err(refused)?;
    let completed =
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(refused)?;
    if completed.next_stage().is_some() {
        return Err(refused("original historical iteration is incomplete"));
    }
    Ok(())
}

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original historical learning source: {message}"))
}
