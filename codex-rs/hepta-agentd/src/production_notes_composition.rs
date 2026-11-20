//! Notes-first assembly using only the original owners and Session target.
use super::*;

/// Complete external authority inputs for a Notes-only production host. There
/// is no placeholder primary destination and no local issuer or cut discovery.
pub struct AgentdProductionNotesHostInputs<'a> {
    pub current_cut: CognitiveRecoveryRequirement<'a>,
    pub authority: ProductionAuthorityLease,
    pub verifier: Arc<dyn ProductionAuthorityVerifier>,
    pub lease_id: String,
    pub lease_generation: u64,
    pub final_use: AgentdFinalUseHostInputs,
    pub issuer_stream: UnixStream,
    pub issuer_peer: AgentdFinalUseIssuerPeer,
    pub issuer_timeout: Duration,
    pub reconcile_interval: Duration,
    pub bootstrap: UnixDatagram,
}

/// Assemble the actual Session-provided Notes as the sole primary target.
/// Publication is atomic and no grant request or effect occurs at bootstrap.
pub async fn attach_production_notes_host(
    config: &mut AgentdConfig,
    inputs: AgentdProductionNotesHostInputs<'_>,
) -> Result<NotesTargetIdentity, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    match &inputs.current_cut {
        CognitiveRecoveryRequirement::Revoked => {
            return Err(AgentdError::GenerationFenced(
                "production current-cut authorization is revoked".into(),
            ));
        }
        CognitiveRecoveryRequirement::ExactCurrentCut(anchor)
            if anchor.owner_agent_id != config.identity().agent_id =>
        {
            return Err(AgentdError::GenerationFenced(
                "production current cut belongs to another Agent".into(),
            ));
        }
        CognitiveRecoveryRequirement::ExactCurrentCut(_) => {}
    }
    if inputs.lease_generation != config.identity().spawn_generation
        || inputs.lease_generation == 0
        || inputs.lease_id.trim().is_empty()
        || inputs.reconcile_interval.is_zero()
    {
        return Err(AgentdError::Invalid(
            "Notes production composition requires exact generation, lease and interval".into(),
        ));
    }
    if inputs.authority.agent_id != config.identity().agent_id
        || inputs.authority.fencing_token_digest().is_err()
    {
        return Err(AgentdError::GenerationFenced(
            "Notes production authority lacks its exact owner or original token".into(),
        ));
    }
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(ProtectedClockVerifier {
        inner: inputs.verifier,
        clock: Arc::clone(&inputs.final_use.clock),
    });
    verifier
        .verify(&inputs.authority, &config.identity().agent_id)
        .map_err(AgentdError::GenerationFenced)?;
    let grants = Arc::new(
        AgentdUnixFinalUseGrantProvider::from_stream(
            inputs.issuer_stream,
            inputs.issuer_peer,
            inputs.issuer_timeout,
        )
        .map_err(|error| AgentdError::Protocol(format!("final-use issuer transport: {error}")))?,
    );
    let final_use = inputs.final_use.open().map_err(|error| {
        AgentdError::Protocol(format!("protected Notes final-use authority: {error}"))
    })?;
    let recovered = Arc::new(
        AgentdProductionWriterHost::open_with_recovery(
            config,
            inputs.current_cut,
            inputs.authority.clone(),
            Arc::clone(&verifier),
            inputs.lease_id.clone(),
            inputs.lease_generation,
        )
        .await?,
    );
    let result = async {
        let (target, identity) = recovered
            .notes_target_from_session(inputs.bootstrap)
            .await?;
        let operations = AgentdProductionOperationRuntimeConfig::new(
            inputs.authority,
            verifier,
            inputs.lease_id,
            inputs.lease_generation,
            final_use,
            Arc::new(target),
            grants,
            inputs.reconcile_interval,
        );
        operations.validate_for(config)?;
        operations.validate_recovered_host(&recovered).await?;
        config.install_production_hosts(Arc::clone(&recovered), operations)?;
        Ok(identity)
    }
    .await;
    if result.is_err() {
        let recovered = Arc::try_unwrap(recovered).map_err(|_| {
            AgentdError::Invalid("failed Notes composition retained a shared owner".into())
        })?;
        recovered.close().await?;
    }
    result
}
