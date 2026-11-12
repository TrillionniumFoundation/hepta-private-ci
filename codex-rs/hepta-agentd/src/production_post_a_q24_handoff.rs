//! Hold the four original anonymous datagrams through historical preparation.
//! Only the actual Root late-install acknowledgement permits their consumption.

use super::*;

pub(in crate::production_launcher) struct PendingHandoffs {
    pub(super) learning: UnixDatagram,
    pub(super) model: UnixDatagram,
    pub(super) independent_b: UnixDatagram,
    pub(super) publication: UnixDatagram,
}

impl PendingHandoffs {
    pub(in crate::production_launcher) fn defer_for_original_profile(
        primary: &PrimaryInputs,
        learning: &mut Option<UnixDatagram>,
        model: &mut Option<UnixDatagram>,
        independent_b: &mut Option<UnixDatagram>,
        publication: &mut Option<UnixDatagram>,
    ) -> Result<Option<Self>, AgentdError> {
        if !matches!(primary, PrimaryInputs::PostAQ24 { .. }) {
            return Ok(None);
        }
        let learning = learning
            .take()
            .ok_or_else(|| refused("post-A learning handoff absent"))?;
        let model = model
            .take()
            .ok_or_else(|| refused("post-A model handoff absent"))?;
        let independent_b = independent_b
            .take()
            .ok_or_else(|| refused("post-A independent B handoff absent"))?;
        let publication = publication
            .take()
            .ok_or_else(|| refused("post-A publication handoff absent"))?;
        Ok(Some(Self {
            learning,
            model,
            independent_b,
            publication,
        }))
    }

    pub(super) async fn receive_original_after_ack(
        self,
        original: &AgentdRootProductionInputs,
        identity: &AgentdIdentity,
        ack: &crate::root_historical_task_read_client::OriginalPostAFrozenLearningAckV1,
        prepared: &crate::CellQ24PreparedLearningV1,
        end: Instant,
    ) -> Result<
        (
            crate::AgentdRootLearningInputsV1,
            crate::AgentdRootQ24ModelFactoryV1,
            crate::RootGenerationPublicationHandoffV1,
            crate::RootIndependentBEvaluationHandoffV1,
        ),
        AgentdError,
    > {
        OriginalPostAFrozenLearningAckV1::require_prepared_scope(ack, prepared.scope())?;
        let learning: crate::RootLearningHandoffV1 = crate::receive_root_learning_handoff(
            self.learning,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
        )?;
        post_a_remaining(end)?;
        let learning: crate::AgentdRootLearningInputsV1 =
            crate::RootLearningHandoffV1::connect_until(
                learning,
                original,
                identity,
                post_a_remaining(end)?.min(Duration::from_millis(500)),
                end,
            )
            .await?;
        learning.require_prepared_q24(prepared)?;
        let model: crate::RootQ24ModelFactoryHandoffV1 =
            crate::receive_root_q24_model_factory_handoff(
                self.model,
                post_a_remaining(end)?.min(Duration::from_millis(500)),
            )?;
        post_a_remaining(end)?;
        let model = crate::RootQ24ModelFactoryHandoffV1::connect_until(
            model,
            original,
            &learning,
            identity,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
            end,
        )
        .await?;
        OriginalPostAFrozenLearningAckV1::require_prepared_scope(ack, prepared.scope())?;
        post_a_remaining(end)?;
        // CURRENT is not connected here. The actual Root server cannot admit
        // it until the later independent decision and target are available.
        let publication = crate::receive_root_generation_publication_handoff(
            self.publication,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
        )?;
        OriginalPostAFrozenLearningAckV1::require_prepared_scope(ack, prepared.scope())?;
        post_a_remaining(end)?;
        let independent_b = crate::receive_root_independent_b_evaluation_handoff(
            self.independent_b,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
        )?;
        OriginalPostAFrozenLearningAckV1::require_prepared_scope(ack, prepared.scope())?;
        post_a_remaining(end)?;
        Ok((learning, model, publication, independent_b))
    }
}
