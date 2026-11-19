//! Notes as the actual primary operation target, without a fabricated device.
//! Reuses the same inherited offer/parser and original recovered owner checks.

use super::*;
use codex_hepta_memory::ProductionAuthorityVerifier;

pub(crate) struct PrimaryNotesAuthority {
    pub(crate) final_use: FinalUseAuthority,
    pub(crate) grants: Arc<dyn AgentdFinalUseGrantProvider>,
    pub(crate) verifier: Arc<dyn ProductionAuthorityVerifier>,
}

pub(crate) async fn primary_notes_runtime(
    config: &AgentdConfig,
    recovered_host: &AgentdProductionWriterHost,
    bootstrap: UnixDatagram,
    authority: PrimaryNotesAuthority,
    reconcile_interval: Duration,
    expected: Option<&NotesTargetIdentity>,
) -> Result<
    (
        AgentdProductionOperationRuntimeConfig,
        AgentdNotesDocumentObserver,
    ),
    AgentdError,
> {
    primary_notes_runtime_bounded(
        config,
        recovered_host,
        bootstrap,
        authority,
        reconcile_interval,
        expected,
        None,
    )
    .await
}

pub(crate) async fn primary_notes_runtime_before(
    config: &AgentdConfig,
    recovered_host: &AgentdProductionWriterHost,
    bootstrap: UnixDatagram,
    authority: PrimaryNotesAuthority,
    reconcile_interval: Duration,
    expected: Option<&NotesTargetIdentity>,
    end: crate::calculator_deadline::Deadline,
) -> Result<
    (
        AgentdProductionOperationRuntimeConfig,
        AgentdNotesDocumentObserver,
    ),
    AgentdError,
> {
    primary_notes_runtime_bounded(
        config,
        recovered_host,
        bootstrap,
        authority,
        reconcile_interval,
        expected,
        Some(end.capped(Duration::from_secs(2))?),
    )
    .await
}

async fn primary_notes_runtime_bounded(
    config: &AgentdConfig,
    recovered_host: &AgentdProductionWriterHost,
    bootstrap: UnixDatagram,
    authority: PrimaryNotesAuthority,
    reconcile_interval: Duration,
    expected: Option<&NotesTargetIdentity>,
    total: Option<crate::calculator_deadline::Deadline>,
) -> Result<
    (
        AgentdProductionOperationRuntimeConfig,
        AgentdNotesDocumentObserver,
    ),
    AgentdError,
> {
    let deadline = Instant::now() + Duration::from_secs(2);
    let PrimaryNotesAuthority {
        final_use,
        grants,
        verifier,
    } = authority;
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
    tokio::time::timeout(
        remaining_before(deadline, total)?,
        writer.verify_current_authority(),
    )
    .await
    .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "primary Notes owner deadline"))??;
    let (offer, endpoint, recovery) =
        receive_session(&bootstrap, bounded_instant(deadline, total)?, expected)?;
    if total.is_some() {
        remaining_before(deadline, total)?;
    }
    let configured = tokio::time::timeout(remaining_before(deadline, total)?, async {
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
            let _ = acknowledge(
                &bootstrap,
                &offer,
                RegistrationStatus::Rejected,
                bounded_instant(deadline, total)?,
            );
            return Err(error);
        }
        Err(_) => {
            return Err(
                io::Error::new(io::ErrorKind::TimedOut, "primary Notes handoff deadline").into(),
            );
        }
    };
    acknowledge(
        &bootstrap,
        &offer,
        RegistrationStatus::Attached,
        bounded_instant(deadline, total)?,
    )?;
    if total.is_some() {
        remaining_before(deadline, total)?;
    }
    Ok(configured)
}

fn remaining_before(
    deadline: Instant,
    total: Option<crate::calculator_deadline::Deadline>,
) -> io::Result<Duration> {
    let local = remaining(deadline)?;
    match total {
        Some(total) => Ok(local.min(total.remaining()?)),
        None => Ok(local),
    }
}

fn bounded_instant(
    deadline: Instant,
    total: Option<crate::calculator_deadline::Deadline>,
) -> io::Result<Instant> {
    match total {
        None => Ok(deadline),
        Some(total) => Ok(Instant::now() + remaining_before(deadline, Some(total))?),
    }
}
