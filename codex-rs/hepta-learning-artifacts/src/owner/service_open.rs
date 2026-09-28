impl LearningArtifactOwnerService {
    pub fn open(
        config: LearningArtifactOwnerServiceConfigV1,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        let started = Instant::now();
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        if config.storage_binding.is_zero()
            || config.withdrawal_registry.scope_digest()
                != Some(config.trust.withdrawal_scope_digest)
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let request_trust = config.trust.clone();
        let registry_id = config.trust.registry_id.clone();
        let scope = config.trust.withdrawal_scope_digest;
        let host = match config.required_current_head {
            Some(current) => LearningArtifactOwnerHost::open_with_required_current_head(
                &config.root,
                config.trust,
                config.writer_lease,
                current,
                config.now,
            )?,
            None => LearningArtifactOwnerHost::open(
                &config.root,
                config.trust,
                config.writer_lease,
                config.now,
            )?,
        };
        let root = std::fs::canonicalize(&config.root)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let request_identity = RequestIdentityStore::new(
            &root,
            &request_trust,
            host.trust_digest(),
            config.storage_binding,
        )?;
        let durable_drain = DurableDrain::new(&root, &registry_id, scope, config.storage_binding);
        let draining = durable_drain
            .requested()
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        if draining {
            durable_drain
                .persist()
                .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        }
        if let Some(current) = host.discover_current_head(config.now)?
            && current.signed.binding != config.storage_binding
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let registry = host.recover_current_registry(config.now)?;
        let recovery = host.recovery_required_operations()?;
        if recovery.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RecoveryConflict);
        }
        let recovery_required = recovery
            .first()
            .map(|checkpoint| checkpoint.operation_id.clone());
        let durable_withdrawals =
            DurableWithdrawalFloor::new(&root, &registry_id, scope, config.storage_binding);
        durable_withdrawals
            .persist(&config.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let operational_state =
            OwnerOperationalState::new(draining, recovery_required, config.now);
        metrics.observe(ArtifactOwnerStageV1::StartupRecovery, started.elapsed());
        Ok(Self {
            host,
            root,
            durable_drain,
            durable_withdrawals,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            request_identity,
            operational_state,
            metrics,
        })
    }

}
