//! One verified distribution obtained from the actual original Initial client.
//! There is no constructor from caller JSON, a bare root key or signer list.

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::*;
use crate::AgentdIdentity;
use crate::AgentdRootAuthoritySession;
use crate::authority_host_service::generation_initial::LEARNING_TRUST_PURPOSE;
use crate::authority_host_service::generation_initial::LearningTrustResponseV1;

pub(crate) struct OriginalRootInitialLearningTrustV1 {
    activated: ActivatedLearningTrustV1,
    generator: TrustedLearningSignerV1,
    observer: TrustedLearningSignerV1,
}

impl OriginalRootInitialLearningTrustV1 {
    pub(crate) fn into_ledger_authorities(
        self,
    ) -> (
        ActivatedLearningTrustV1,
        TrustedLearningSignerV1,
        TrustedLearningSignerV1,
    ) {
        (self.activated, self.generator, self.observer)
    }
}

impl RootGenerationInitialClient {
    pub(crate) fn read_original_learning_trust(
        &self,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<OriginalRootInitialLearningTrustV1, AgentdError> {
        let result = (|| {
            self.require_learning_trust_session(session, identity)?;
            let pin = self.profile.learning_trust.as_ref().ok_or_else(uncertain)?;
            pin.require_target(&self.profile.deployment.target)?;
            let before = self.observe_initial_current()?;
            crate::neuron_generation_current::initial_root::original_initial_record(
                &self.profile.prepared,
                &before,
            )?
            .ok_or_else(uncertain)?;
            let response = {
                let mut held = self.lane.try_lock().map_err(|_| uncertain())?;
                let mut lane = held.take().ok_or_else(uncertain)?;
                let request_id = lane.sequence;
                lane.sequence = request_id.checked_add(1).ok_or_else(uncertain)?;
                let request = Request {
                    schema: 1,
                    purpose: LEARNING_TRUST_PURPOSE.into(),
                    request_id,
                    profile: self.profile.binding.clone(),
                    command: Command::ReadLearningTrust {},
                };
                let raw = lane.stream.exchange(&serde_json::to_vec(&request)?)?;
                let response: LearningTrustResponseV1 = serde_json::from_slice(&raw)?;
                if response.schema != 1
                    || response.purpose != LEARNING_TRUST_PURPOSE
                    || response.request_id != request_id
                    || response.profile != self.profile.binding
                    || &response.pin != pin
                    || self.fenced.load(Ordering::Acquire)
                {
                    return Err(uncertain());
                }
                self.require_learning_trust_session(session, identity)?;
                *held = Some(lane);
                response
            };
            let (activated, generator, observer) = response.payload.activate_pinned_genesis(
                session.clock().now_unix_ms().map_err(|_| uncertain())? / 1_000,
            )?;
            response.payload.require_activation_pin(&activated, pin)?;
            if self.observe_initial_current()? != before {
                return Err(uncertain());
            }
            self.require_learning_trust_session(session, identity)?;
            Ok(OriginalRootInitialLearningTrustV1 {
                activated,
                generator,
                observer,
            })
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }

    fn require_learning_trust_session(
        &self,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        self.connection.require_same_original_session(session)?;
        if self.connection.original_launch_binding().1 != identity
            || self.fenced.load(Ordering::Acquire)
        {
            return Err(uncertain());
        }
        self.connection.require_same_original_session(session)
    }
}
