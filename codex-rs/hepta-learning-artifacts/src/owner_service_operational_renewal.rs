//! Only the sole writer service can open this maintenance purpose. Prior
//! eligibility remains expired; fresh publication follows the normal protocol.
use super::*;

impl LearningArtifactOwnerService {
    /// Extend a fully authenticated retained history with a current signed
    /// writer lease. The caller supplies new evidence/admissions to `publish`;
    /// this constructor neither refreshes old evidence nor grants result use.
    /// An external acknowledged floor is mandatory, including after expiry.
    pub fn open_for_fresh_evidence_publication(
        config: LearningArtifactOwnerServiceConfigV1,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        let retained = config
            .required_current_head
            .ok_or(LearningArtifactOwnerServiceError::InvalidConfiguration)?;
        if config.storage_binding.is_zero()
            || retained.binding != config.storage_binding
            || config.withdrawal_registry.scope_digest()
                != Some(config.trust.withdrawal_scope_digest)
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let host = LearningArtifactOwnerHost::open_for_fresh_evidence_publication(
            &config.root,
            config.trust,
            config.writer_lease,
            retained,
            config.now,
        )?;
        let current = host
            .discover_publication_predecessor(config.now)?
            .ok_or(LearningArtifactOwnerServiceError::InvalidConfiguration)?;
        if current.signed.binding != config.storage_binding {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let registry = host.recover_publication_registry(config.now)?;
        let recovery = host.recovery_required_operations()?;
        if recovery.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RecoveryConflict);
        }
        Ok(Self {
            host,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            recovery_required: recovery.first().map(|value| value.operation_id.clone()),
        })
    }
}
