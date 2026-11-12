//! Hold the two original anonymous datagrams through historical preparation.
//! Only the actual Root late-install acknowledgement permits their consumption.

use super::*;

pub(in crate::production_launcher) struct PendingHandoffs {
    pub(super) learning: UnixDatagram,
    pub(super) model: UnixDatagram,
}

impl PendingHandoffs {
    pub(in crate::production_launcher) fn defer_for_original_profile(
        primary: &PrimaryInputs,
        learning: &mut Option<UnixDatagram>,
        model: &mut Option<UnixDatagram>,
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
        Ok(Some(Self { learning, model }))
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
        ),
        AgentdError,
    > {
        ack.require_prepared_scope(prepared.scope())?;
        let learning: crate::RootLearningHandoffV1 = crate::receive_root_learning_handoff(
            self.learning,
            post_a_remaining(end)?.min(Duration::from_millis(500)),
        )?;
        post_a_remaining(end)?;
        let learning = crate::RootLearningHandoffV1::connect_until(
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
        ack.require_prepared_scope(prepared.scope())?;
        post_a_remaining(end)?;
        Ok((learning, model))
    }
}
