//! Notes as the actual primary operation target, without a fabricated device.
//! Reuses the same inherited offer/parser and original recovered owner checks.

use super::*;
use codex_hepta_memory::ProductionAuthorityVerifier;

pub(crate) async fn primary_notes_runtime(
    config: &AgentdConfig,
    recovered_host: &AgentdProductionWriterHost,
    bootstrap: UnixDatagram,
    final_use: FinalUseAuthority,
    grants: Arc<dyn AgentdFinalUseGrantProvider>,
    verifier: Arc<dyn ProductionAuthorityVerifier>,
    reconcile_interval: Duration,
    expected: Option<&NotesTargetIdentity>,
) -> Result<
    (
        AgentdProductionOperationRuntimeConfig,
        AgentdNotesDocumentObserver,
    ),
    AgentdError,
> {
    let deadline = Instant::now() + Duration::from_secs(2);
    let writer = recovered_host.writer();
    if recovered_host.destination_count() != 0
        || writer.owner_agent_id() != &config.identity().agent_id
        || recovered_host.spawn_generation() != config.identity().spawn_generation
        || recovered_host.production_mutation().is_none()
        || reconcile_interval.is_zero()
    {
        return Err(AgentdError::Invalid(
            "primary Notes requires this unregistered recovered original owner".into(),
        ));
    }
    verifier
        .verify(writer.authority(), writer.owner_agent_id())
        .map_err(AgentdError::GenerationFenced)?;
    tokio::time::timeout(remaining(deadline)?, writer.verify_current_authority())
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "primary Notes owner deadline"))??;
    let (offer, endpoint, recovery) = receive_session(&bootstrap, deadline, expected)?;
    let configured = tokio::time::timeout(remaining(deadline)?, async {
        let channel = Arc::new(AgentdNotesChannel::from_private_channels(
            endpoint, recovery,
        )?);
        let target = ProductionNotesTarget::new(offer.target.clone(), channel)
            .map_err(AgentdError::Invalid)?;
        let observer = AgentdNotesDocumentObserver::new(target.document_observer());
        let operations = AgentdProductionOperationRuntimeConfig::new(
            writer.authority().clone(),
            verifier,
            writer.lease_id().to_owned(),
            writer.generation(),
            final_use,
            Arc::new(target),
            grants,
            reconcile_interval,
        );
        operations.validate_for(config)?;
        operations.validate_recovered_host(recovered_host).await?;
        Ok::<_, AgentdError>((operations, observer))
    })
    .await;
    let configured = match configured {
        Ok(Ok(configured)) => configured,
        Ok(Err(error)) => {
            let _ = acknowledge(&bootstrap, &offer, RegistrationStatus::Rejected, deadline);
            return Err(error);
        }
        Err(_) => {
            return Err(
                io::Error::new(io::ErrorKind::TimedOut, "primary Notes handoff deadline").into(),
            );
        }
    };
    acknowledge(&bootstrap, &offer, RegistrationStatus::Attached, deadline)?;
    Ok(configured)
}
