//! The waiting C service can be selected only from this assembled original
//! Root/Q24 bootstrap and its registered historical A source.

use super::*;
use crate::circuit_q24_successor::SuccessorSlot;
use crate::root_production_inputs::OriginalQ24SuccessorSession;

pub(crate) struct OriginalQ24SuccessorContext {
    identity: AgentdIdentity,
    owners: Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
    source: OriginalSuccessorSourceV1,
    session: Arc<OriginalQ24SuccessorSession>,
}

enum OriginalSuccessorSourceV1 {
    Retained(Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1>),
    Historical(Arc<super::historical_source::RegisteredHistoricalLearningSourceV1>),
}

impl OriginalQ24SuccessorContext {
    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }
    pub(crate) fn owners(&self) -> &Arc<crate::OriginalCellQ24LearningStageOwnersV1> {
        &self.owners
    }
    pub(crate) fn session(&self) -> &OriginalQ24SuccessorSession {
        &self.session
    }
    pub(crate) fn initial(&self) -> &LearningIterationSnapshotV1 {
        let owners: &crate::OriginalCellQ24LearningStageOwnersV1 = self.owners.as_ref();
        owners.prepared().initial()
    }
    pub(crate) fn scope(&self) -> &FrozenLearningScopeV2 {
        let owners: &crate::OriginalCellQ24LearningStageOwnersV1 = self.owners.as_ref();
        owners.prepared().scope()
    }

    pub(crate) async fn require_current_successor_context(&self) -> Result<(), AgentdError> {
        self.session.require_current_successor_session()?;
        match &self.source {
            OriginalSuccessorSourceV1::Retained(retained) => {
                let retained: &Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1> =
                    retained;
                retained.observe_retained_learning(&self.identity).await?;
            }
            OriginalSuccessorSourceV1::Historical(source) => {
                source.require_current_historical_source(&self.identity)?;
            }
        }
        let owners: &crate::OriginalCellQ24LearningStageOwnersV1 = self.owners.as_ref();
        owners
            .require_current()
            .await
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        self.session.require_current_successor_session()
    }
}

impl LearningIterationRuntimeBootstrapV1 {
    pub(crate) async fn prepare_original_successor_context(
        &mut self,
        identity: &AgentdIdentity,
        session: Arc<OriginalQ24SuccessorSession>,
        slot: &Arc<SuccessorSlot>,
    ) -> Result<Arc<OriginalQ24SuccessorContext>, AgentdError> {
        self.require_identity(identity)?;
        let original: &Arc<crate::OriginalCellQ24LearningStageOwnersV1> = self
            .original_q24
            .as_ref()
            .ok_or_else(|| successor_refused("original Root Q24 owners required"))?;
        let prepared = original.prepared();
        let source = match (&self.retained_source, &self.historical_source) {
            (Some(retained), None) if retained.request() == &prepared.initial().request => {
                OriginalSuccessorSourceV1::Retained(Arc::clone(retained))
            }
            (None, Some(historical)) if historical.request() == &prepared.initial().request => {
                historical.require_prepared_historical_source(prepared)?;
                OriginalSuccessorSourceV1::Historical(Arc::clone(historical))
            }
            _ => return Err(successor_refused("one actual original A source required")),
        };
        let registry = self
            .circuit_delivery_registry
            .as_ref()
            .ok_or_else(|| successor_refused("original Root delivery registry required"))?;
        if self.successor.is_some()
            || !self.enforce_circuit_admission
            || !matches!(
                self.circuit_delivery_source,
                CircuitLearningSourceV1::OriginalQ24
            )
            || session.identity() != identity
            || self.scope.as_ref() != Some(prepared.scope())
            || self.owners != prepared.initial().owners
            || registry.requests.as_slice() != std::slice::from_ref(&prepared.initial().request)
        {
            return Err(successor_refused(
                "successor differs from assembled Root and retained source",
            ));
        }
        let context = Arc::new(OriginalQ24SuccessorContext {
            identity: identity.clone(),
            owners: Arc::clone(original),
            source,
            session,
        });
        context.require_current_successor_context().await?;
        original
            .register_original_successor(Arc::clone(&context.session), slot)
            .await
            .map_err(|error| successor_refused(&error.to_string()))?;
        self.successor = Some(Arc::clone(slot));
        Ok(context)
    }

    pub(crate) async fn wait_original_successor_stage(
        &self,
        state: &AgentdState,
        snapshot: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        let Some(slot) = &self.successor else {
            return Ok(());
        };
        let needs_publication = stage == LearningIterationStageV1::NextUse
            || (stage == LearningIterationStageV1::Selection
                && !snapshot.receipts.last().is_some_and(|receipt| {
                    receipt.observation.stage() == LearningIterationStageV1::Proposal
                }));
        if !needs_publication {
            return Ok(());
        }
        self.require_stage_admission(state)?;
        self.require_frozen_scope(&snapshot.request)?;
        // The preceding original checkpoint has completed. No aggregate lane,
        // checkpoint transport or owner mutex is held across this wait.
        slot.wait_original_generation(snapshot).await?;
        self.require_stage_admission(state)?;
        if now_unix_seconds()? >= snapshot.request.envelope.expiry_unix_seconds {
            return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
        }
        Ok(())
    }
}

fn successor_refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
