use super::*;

impl AgentdClient {
    /// Resume exact PoN bytes from the signed host's optional packet directory.
    /// No local file read is required: durable attempts survive material loss.
    pub async fn automation_resume_pon_packet(
        &self,
        intent: AuthorizedEffectIntent,
        packet: crate::AutomationPonPacketFile,
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<AutomationEffectReconcileSnapshot, AgentdError> {
        if !self.capabilities().await?.capabilities.iter().any(|capability| {
            capability.id == crate::AUTOMATION_PON_PACKET_FILE_CAPABILITY && capability.major == 1
        }) {
            return Err(AgentdError::Protocol(
                "Agentd has no host-owned PoN packet file capability".to_owned(),
            ));
        }
        match self.send(AgentdRequest::automation_resume_pon_packet(
            self.request_id(), self.spawn_generation, intent, packet, signed_grant, command_id,
        )).await?.payload {
            AgentdPayload::AutomationEffectReconcile(observation) => Ok(observation),
            payload => unexpected(payload),
        }
    }

    /// Resume one original-owner effect. This prepares a new single-step run
    /// only when no durable dispatch exists; uncertain attempts are reconciled.
    pub async fn automation_resume_effect(
        &self,
        intent: AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<AutomationEffectReconcileSnapshot, AgentdError> {
        if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
            return Err(AgentdError::Invalid(
                "automation effect wire payload is empty or too large".to_owned(),
            ));
        }
        if !self
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|capability| {
                capability.id == crate::AUTOMATION_EFFECT_RESUME_CAPABILITY && capability.major == 1
            })
        {
            return Err(AgentdError::Protocol(
                "Agentd has no original-owner effect resume capability".to_owned(),
            ));
        }
        let request = AgentdRequest::automation_resume_effect(
            self.request_id(),
            self.spawn_generation,
            intent,
            encode_hex(wire_payload),
            signed_grant,
            command_id,
        );
        match self.send(request).await?.payload {
            AgentdPayload::AutomationEffectReconcile(observation) => Ok(observation),
            payload => unexpected(payload),
        }
    }

    /// Observe a completed exact effect through the original durable owner.
    /// This never renews a lease, consumes a nonce, settles or sends an effect.
    pub async fn automation_observe_effect(
        &self,
        intent: AuthorizedEffectIntent,
        command_id: String,
    ) -> Result<AutomationEffectReconcileSnapshot, AgentdError> {
        if !self
            .capabilities()
            .await?
            .capabilities
            .iter()
            .any(|capability| {
                capability.id == crate::AUTOMATION_TERMINAL_OBSERVATION_CAPABILITY
                    && capability.major == 1
            })
        {
            return Err(AgentdError::Protocol(
                "Agentd has no terminal effect observation capability".to_owned(),
            ));
        }
        match self
            .send(AgentdRequest::automation_observe_effect(
                self.request_id(),
                self.spawn_generation,
                intent,
                command_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationEffectReconcile(observation) => Ok(observation),
            payload => unexpected(payload),
        }
    }
}
