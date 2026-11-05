//! Fresh offline authorization to retry one unchanged retained publication.
use super::*;

impl H7PqProductionRecoverySigner {
    #[expect(
        clippy::too_many_arguments,
        reason = "the fresh decision explicitly binds both retained attempts and actual owner state"
    )]
    pub fn sign_retry_retained_publication(
        &self,
        intent: &SignedSupervisorIntent,
        observed: &ReleaseBinding,
        observation: &RetainedPublicationObservationV1,
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
        let release = match (intent.transition, intent.status) {
            (H7H89ProductionTransition::Upgrade, crate::SignedIntentStatus::Committed)
            | (H7H89ProductionTransition::Rollback, crate::SignedIntentStatus::RolledBack)
                if intent.pq_authority.is_some() =>
            {
                &intent.target_release
            }
            (H7H89ProductionTransition::Upgrade, crate::SignedIntentStatus::RolledBack)
                if intent.pq_authority.is_some() =>
            {
                &intent.source_release
            }
            (_, crate::SignedIntentStatus::Aborted)
                if !intent.requires_recovery()
                    && intent.unknown_effects.last().is_some_and(|unknown| {
                        unknown.decision.schema_version == 3
                            && unknown.decision.pq_authority.is_some()
                            && unknown.decision.grant_sha256 == intent.grant_sha256
                    }) =>
            {
                &intent.source_release
            }
            _ => return Err(ProductionAuthorityError::RecoveryBinding),
        };
        if observed.release_id.as_str() != release
            || !observation.valid_for(&agent)
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
            ProductionRecoveryOutcome::RetryRetainedPublication,
            lifecycle_generation,
            authority_epoch,
            issued,
            expires,
        )?;
        decision.retained_publication_observation = Some(observation.clone());
        self.finish(decision)
    }
}
