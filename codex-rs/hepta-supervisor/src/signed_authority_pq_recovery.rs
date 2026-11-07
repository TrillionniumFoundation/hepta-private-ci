//! Explicit recovery-role signatures for current production recovery.
use super::*;

impl H7PqProductionRecoverySigner {
    pub fn new(
        policy_bytes: &[u8],
        key: PqNativeSigningKey,
    ) -> Result<Self, ProductionAuthorityError> {
        let (policy, digest) = policy::decode_policy(policy_bytes)?;
        Ok(Self {
            role: PqRoleSigner::new(policy.recovery, digest, key)?,
        })
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "all original observed recovery bindings remain explicit"
    )]
    pub fn sign_recovery(
        &self,
        agent_id: &AgentId,
        grant_sha256: Sha256Digest,
        intent_sha256: Sha256Digest,
        release_transaction_sha256: Sha256Digest,
        observed_release: impl Into<String>,
        observed_manifest_sha256: Sha256Digest,
        observed_agentd_sha256: Sha256Digest,
        observed_matrixd_sha256: Option<Sha256Digest>,
        outcome: ProductionRecoveryOutcome,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        let decision = unsigned::recovery(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            agent_id,
            grant_sha256,
            intent_sha256,
            release_transaction_sha256,
            observed_release,
            observed_manifest_sha256,
            observed_agentd_sha256,
            observed_matrixd_sha256,
            outcome,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        self.finish(decision)
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "all original Unknown owner fences remain explicit"
    )]
    pub fn sign_abandon_unknown(
        &self,
        intent: &SignedSupervisorIntent,
        source: &ReleaseBinding,
        release_state_generation: u64,
        lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        let decision = unsigned::abandon_unknown(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            intent,
            source,
            release_state_generation,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        self.finish(decision)
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "Unknown recovery signs the actual anchored predecessor and retained transaction"
    )]
    pub fn sign_abandon_unknown_after_predecessor(
        &self,
        intent: &SignedSupervisorIntent,
        source: &ReleaseBinding,
        predecessor: &UnknownRecoveryPredecessorV1,
        observed_transaction_sha256: Sha256Digest,
        release_state_generation: u64,
        lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        if !AgentId::parse(intent.agent_id.clone()).is_ok_and(|agent| predecessor.valid_for(&agent))
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        intent
            .validate()
            .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
        if intent.pq_authority.is_none()
            || source.release_id.as_str() != intent.source_release
            || !matches!(
                intent.status,
                crate::SignedIntentStatus::Prepared
                    | crate::SignedIntentStatus::Queued
                    | crate::SignedIntentStatus::RecoveryRequired
            ) && !intent.requires_recovery()
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        let agent = AgentId::parse(intent.agent_id.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?;
        let mut decision = unsigned::recovery(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            &agent,
            intent.grant_sha256.clone(),
            intent.intent_sha256.clone(),
            observed_transaction_sha256,
            source.release_id.as_str(),
            Sha256Digest::parse(source.manifest_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            Sha256Digest::parse(source.agentd_program_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            source
                .matrixd_program_sha256
                .as_ref()
                .map(|value| Sha256Digest::parse(value.clone()))
                .transpose()
                .map_err(ProductionAuthorityError::Invalid)?,
            ProductionRecoveryOutcome::AbandonUnknown,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        decision.unknown_observation = Some(UnknownRecoveryObservation {
            release_state_generation,
            admission_frontier_sha256: Sha256Digest::parse(
                source.admission_frontier_sha256.clone(),
            )
            .map_err(ProductionAuthorityError::Invalid)?,
            predecessor: Some(predecessor.clone()),
        });
        self.finish(decision)
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "confirmation binds the full retained Unknown snapshot and actual predecessor"
    )]
    pub fn sign_confirm_unknown_publication(
        &self,
        intent: &SignedSupervisorIntent,
        source: &ReleaseBinding,
        predecessor: &UnknownRecoveryPredecessorV1,
        observed_transaction_sha256: Sha256Digest,
        release_state_generation: u64,
        lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        intent
            .validate()
            .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
        if intent.status != crate::SignedIntentStatus::Aborted
            || intent.requires_recovery()
            || !intent.unknown_effects.last().is_some_and(|unknown| {
                unknown.decision.schema_version == 3
                    && unknown.decision.pq_authority.is_some()
                    && unknown.decision.grant_sha256 == intent.grant_sha256
            })
            || source.release_id.as_str() != intent.source_release
            || !AgentId::parse(intent.agent_id.clone())
                .is_ok_and(|agent| predecessor.valid_for(&agent))
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        let agent = AgentId::parse(intent.agent_id.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?;
        let mut decision = unsigned::recovery(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            &agent,
            intent.grant_sha256.clone(),
            intent.intent_sha256.clone(),
            observed_transaction_sha256,
            source.release_id.as_str(),
            Sha256Digest::parse(source.manifest_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            Sha256Digest::parse(source.agentd_program_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            source
                .matrixd_program_sha256
                .as_ref()
                .map(|value| Sha256Digest::parse(value.clone()))
                .transpose()
                .map_err(ProductionAuthorityError::Invalid)?,
            ProductionRecoveryOutcome::ConfirmUnknownPublication,
            lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        decision.unknown_observation = Some(UnknownRecoveryObservation {
            release_state_generation,
            admission_frontier_sha256: Sha256Digest::parse(
                source.admission_frontier_sha256.clone(),
            )
            .map_err(ProductionAuthorityError::Invalid)?,
            predecessor: Some(predecessor.clone()),
        });
        self.finish(decision)
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "fresh confirmation binds the exact retained completion proposal and owner observations"
    )]
    pub fn sign_confirm_completion_publication(
        &self,
        intent: &SignedSupervisorIntent,
        observed: &ReleaseBinding,
        observation: &CompletionPublicationObservationV1,
        observed_transaction_sha256: Sha256Digest,
        lifecycle_generation: u64,
        authority_epoch: u64,
        issued: u64,
        expires: u64,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        intent
            .validate()
            .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
        let agent = AgentId::parse(intent.agent_id.clone())
            .map_err(|_| ProductionAuthorityError::RecoveryBinding)?;
        let (outcome, expected_release) = match (intent.transition, intent.status) {
            (H7H89ProductionTransition::Upgrade, crate::SignedIntentStatus::Committed) => (
                ProductionRecoveryOutcome::ConfirmCommittedPublication,
                &intent.target_release,
            ),
            (H7H89ProductionTransition::Upgrade, crate::SignedIntentStatus::RolledBack) => (
                ProductionRecoveryOutcome::ConfirmRolledBackPublication,
                &intent.source_release,
            ),
            (H7H89ProductionTransition::Rollback, crate::SignedIntentStatus::RolledBack) => (
                ProductionRecoveryOutcome::ConfirmRolledBackPublication,
                &intent.target_release,
            ),
            _ => return Err(ProductionAuthorityError::RecoveryBinding),
        };
        if intent.pq_authority.is_none()
            || !observation.valid_for(&agent)
            || observed.release_id.as_str() != expected_release
            || observation.admission_frontier_sha256.as_str() != observed.admission_frontier_sha256
        {
            return Err(ProductionAuthorityError::RecoveryBinding);
        }
        let mut decision = unsigned::recovery(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            &agent,
            intent.grant_sha256.clone(),
            intent.intent_sha256.clone(),
            observed_transaction_sha256,
            observed.release_id.as_str(),
            Sha256Digest::parse(observed.manifest_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            Sha256Digest::parse(observed.agentd_program_sha256.clone())
                .map_err(ProductionAuthorityError::Invalid)?,
            observed
                .matrixd_program_sha256
                .as_ref()
                .map(|value| Sha256Digest::parse(value.clone()))
                .transpose()
                .map_err(ProductionAuthorityError::Invalid)?,
            outcome,
            lifecycle_generation,
            authority_epoch,
            issued,
            expires,
        )?;
        decision.completion_observation = Some(observation.clone());
        self.finish(decision)
    }

    pub(super) fn finish(
        &self,
        mut decision: ProductionRecoveryDecision,
    ) -> Result<ProductionRecoveryDecision, ProductionAuthorityError> {
        decision.schema_version = 3;
        decision.namespace = pq_wire::RECOVERY_NAMESPACE.to_string();
        decision.pq_authority = Some(self.role.binding.clone());
        decision.decision_sha256 = decision.payload_digest();
        decision.signature_base64 = self.role.sign(&decision.signing_bytes())?;
        decision.validate_shape()?;
        Ok(decision)
    }
}
