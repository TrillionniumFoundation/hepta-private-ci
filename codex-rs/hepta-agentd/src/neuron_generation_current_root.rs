//! Closed Root-only operations called after the original publication broker
//! validates live source/selection/consumer capabilities. No arbitrary head CAS.

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;

use super::*;

impl NeuronGenerationCurrentOwnerV1 {
    pub(crate) fn read_original_root_recovery_intent(
        &self,
        original: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<codex_hepta_types::Digest32, AgentdError> {
        store::CurrentStore::read_original_root_recovery_intent(&self.store, original)
    }

    pub(crate) fn read_original_completed_successor(
        &self,
        original_a: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
        capture_retired: bool,
    ) -> Result<
        crate::authority_host_service::generation_publication::RootCompletedSuccessorDataV1,
        AgentdError,
    > {
        store::CurrentStore::read_original_completed_successor(
            &self.store,
            original_a,
            capture_retired,
        )
    }

    pub(crate) fn require_original_root_historical_receipt(
        &self,
        original: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
    ) -> Result<(), AgentdError> {
        store::CurrentStore::require_original_root_historical_receipt(&self.store, original)
    }

    pub(crate) fn original_broker_head(&self) -> Result<CurrentHead, AgentdError> {
        if !self.store.is_original_host() {
            return Err(invalid(
                "Root publication requires its actual original protected store",
            ));
        }
        self.store.load()
    }

    pub(crate) fn original_broker_prepare(
        &self,
        intent: &types::UpdateIntent,
    ) -> Result<(), AgentdError> {
        let expected = self.original_broker_head()?;
        if expected.current != intent.previous
            || expected
                .prepared
                .as_ref()
                .is_some_and(|value| value != intent)
            || intent.supersedes.is_some()
        {
            return Err(invalid("original exact predecessor preparation required"));
        }
        let mut next = expected.clone();
        next.prepared = Some(intent.clone());
        if next != expected {
            self.store.replace(&expected, &next)?;
        }
        if self.original_broker_head()? != next {
            return Err(crate::root_generation_current_client::uncertain());
        }
        Ok(())
    }

    pub(crate) fn original_broker_publish(
        &self,
        intent: &types::UpdateIntent,
        signed: &SignedFinalUseGrant,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> Result<(), AgentdError> {
        let expected = self.original_broker_head()?;
        if expected.current != intent.previous
            || expected.prepared.as_ref() != Some(intent)
            || signed.grant.binding != intent.binding()?
        {
            return Err(invalid("original exact prepared CURRENT required"));
        }
        let next = CurrentHead {
            schema_version: 1,
            current: intent.target.clone(),
            prepared: None,
            initial: None,
            published: Some(Published {
                intent: intent.clone(),
                signed: signed.clone(),
                witness: witness.clone(),
                signed_grant_digest: signed_grant_digest(signed)?.into_array(),
            }),
        };
        self.store.replace(&expected, &next)?;
        if self.original_broker_head()? != next {
            return Err(crate::root_generation_current_client::uncertain());
        }
        Ok(())
    }

    pub(crate) fn require_original_root_selection(
        &self,
        decision: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        operation: &codex_hepta_types::StableId,
        selection: codex_hepta_types::Digest32,
    ) -> Result<(), AgentdError> {
        self.store
            .require_original_root_selection(decision, operation, selection)
    }

    pub(crate) fn require_original_root_successor(
        &self,
        session: &crate::root_production_inputs::OriginalQ24SuccessorSession,
        initial: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
    ) -> Result<(), AgentdError> {
        self.store
            .require_original_root_successor(session, initial, scope)
    }

    pub(crate) fn from_original_root_publication(
        original: crate::root_generation_current_client::RootGenerationCurrentClient,
    ) -> Result<Self, AgentdError> {
        let store = store::CurrentStore::from_original_root(original)?;
        store.load()?;
        Ok(Self { store })
    }
}
