//! Original production composition from the authenticated Root descriptor handoff.
//! The ordinary environment path never constructs these inputs.

use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::AgentdNotesDocumentObserver;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootProductionInputs;
use crate::AgentdUnixCognitiveCheckpointTransport;
use crate::AgentdUnixFinalUseGrantProvider;

/// Retain the actual Root feed for the whole daemon lifetime. The checkpoint
/// is the one bound to the recovered writer, suitable for its original sender.
/// The optional Notes observer is read-only and shares the exact private
/// application channel registered below; it cannot install or issue grants.
pub struct AgentdRootProductionAttachment {
    pub root_session: Arc<AgentdRootAuthoritySession>,
    pub checkpoint: Arc<ProtectedCognitiveCheckpoint<AgentdUnixCognitiveCheckpointTransport>>,
    pub grants: Arc<AgentdUnixFinalUseGrantProvider>,
    pub notes: Option<AgentdNotesDocumentObserver>,
}

/// Assemble one protected writer using the already verified live Root session,
/// original Current checkpoint and already opened Device/Notes consumers.
/// No consumer, issuer socket or writer is opened a second time by this path.
///
/// The trusted launcher must retain the returned Root feed until `run` exits.
/// It must register the actual Session Reserved target with the same Root
/// issuer before effects are requested. A Notes handoff ACK alone proves no
/// grant route, model execution, application effect or durable Root terminal.
pub async fn attach_root_production_operation_host(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    primary_target: Arc<dyn FinalUseProductionOutboxTarget>,
    notes_bootstrap: Option<UnixDatagram>,
    reconcile_interval: Duration,
) -> Result<AgentdRootProductionAttachment, AgentdError> {
    attach_root_production_operation_host_with_startup(
        config,
        inputs,
        primary_target,
        notes_bootstrap,
        reconcile_interval,
        /*release*/ None,
    )
    .await
}

/// The explicit staged counterpart activates the exact Root-sealed Session
/// reservation only after the original writer/primary inputs are ready.
pub async fn attach_root_production_operation_host_with_startup(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    primary_target: Arc<dyn FinalUseProductionOutboxTarget>,
    notes_bootstrap: Option<UnixDatagram>,
    reconcile_interval: Duration,
    release: Option<crate::AgentdNotesStartupRelease>,
) -> Result<AgentdRootProductionAttachment, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    if let Some(release) = &release {
        release.validate()?;
        if notes_bootstrap.is_none() {
            return Err(AgentdError::Invalid(
                "Notes startup release requires its actual inherited channel".into(),
            ));
        }
    }
    if reconcile_interval.is_zero() || primary_target.destination_id().is_empty() {
        return Err(AgentdError::Invalid(
            "original Root composition requires an actual primary target and nonzero interval"
                .into(),
        ));
    }
    let AgentdRootProductionInputs {
        session,
        checkpoint,
        device,
        notes,
        grants,
        bootstrap,
    } = inputs;
    bootstrap.writer.validate()?;
    if bootstrap.writer.registered_agent_id != config.identity().agent_id
        || bootstrap.writer.spawn_generation != config.identity().spawn_generation
    {
        return Err(AgentdError::GenerationFenced(
            "Root writer handoff differs from this actual Agentd process".into(),
        ));
    }
    let root_session = Arc::new(session);
    let authority = root_session.authority();
    let verifier = root_session.verifier();
    verifier
        .verify(&authority, &config.identity().agent_id)
        .map_err(AgentdError::GenerationFenced)?;
    let lease_id = bootstrap.writer.local_lease_id;
    let lease_generation = bootstrap.writer.local_lease_generation;
    let operation_grants: Arc<dyn AgentdFinalUseGrantProvider> = grants.clone();
    let operations = AgentdProductionOperationRuntimeConfig::new(
        authority.clone(),
        Arc::clone(&verifier),
        lease_id.clone(),
        lease_generation,
        device,
        primary_target,
        operation_grants,
        reconcile_interval,
    );
    operations.validate_for(config)?;
    let (host, checkpoint) = AgentdProductionWriterHost::open_with_protected_recovery(
        config,
        authority,
        verifier,
        lease_id,
        lease_generation,
        checkpoint,
    )
    .await?;
    let host = Arc::new(host);
    operations.validate_recovered_host(&host).await?;
    let (operations, observer) = match notes_bootstrap {
        Some(channel) => {
            if let Some(release) = &release {
                crate::notes_bootstrap::activate_startup(&channel, release)?;
            }
            let (operations, _identity, observer) = operations
                .with_notes_from_session_expected(
                    config,
                    &host,
                    channel,
                    notes,
                    release.as_ref().map(|release| &release.target),
                )
                .await?;
            let operations = operations.with_notes_receipt_recovery(observer.clone())?;
            (operations, Some(observer))
        }
        None => (operations, None),
    };
    // This existing atomic installer performs the final live verifier check
    // after every earlier await and metadata callback, then publishes both
    // handles without another fallible operation. Failure preserves the real
    // protected store state and never falls back to an unprotected open.
    config.install_production_hosts(host, operations)?;
    Ok(AgentdRootProductionAttachment {
        root_session,
        checkpoint,
        grants,
        notes: observer,
    })
}

/// Explicit Notes-only profile. It still consumes the same authenticated Root
/// session and both already activated frontier owners, but only the actual
/// inherited Notes application is an effect destination. No Android payload,
/// device signer, mock primary or second recovered writer is constructed.
pub async fn attach_root_notes_operation_host(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    notes_bootstrap: UnixDatagram,
    reconcile_interval: Duration,
) -> Result<AgentdRootProductionAttachment, AgentdError> {
    attach_root_notes_operation_host_with_startup(
        config,
        inputs,
        notes_bootstrap,
        reconcile_interval,
        /*release*/ None,
    )
    .await
}

/// Notes-only staged profile; the ordinary direct profile delegates with no
/// activation. Existing effect deadlines and two-FD Offer/ACK remain unchanged.
pub async fn attach_root_notes_operation_host_with_startup(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    notes_bootstrap: UnixDatagram,
    reconcile_interval: Duration,
    release: Option<crate::AgentdNotesStartupRelease>,
) -> Result<AgentdRootProductionAttachment, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    if let Some(release) = &release {
        release.validate()?;
    }
    if reconcile_interval.is_zero() {
        return Err(AgentdError::Invalid(
            "Notes reconciliation interval must be nonzero".into(),
        ));
    }
    let AgentdRootProductionInputs {
        session,
        checkpoint,
        device: _device,
        notes,
        grants,
        bootstrap,
    } = inputs;
    // The retained live Root session already holds clones of both original
    // FinalUse owners. The unused Device owner acquires no target or effect.
    bootstrap.writer.validate()?;
    if bootstrap.writer.registered_agent_id != config.identity().agent_id
        || bootstrap.writer.spawn_generation != config.identity().spawn_generation
    {
        return Err(AgentdError::GenerationFenced(
            "Root Notes handoff differs from actual Agentd identity".into(),
        ));
    }
    let root_session = Arc::new(session);
    let authority = root_session.authority();
    let verifier = root_session.verifier();
    verifier
        .verify(&authority, &config.identity().agent_id)
        .map_err(AgentdError::GenerationFenced)?;
    let (host, checkpoint) = AgentdProductionWriterHost::open_with_protected_recovery(
        config,
        authority,
        Arc::clone(&verifier),
        bootstrap.writer.local_lease_id,
        bootstrap.writer.local_lease_generation,
        checkpoint,
    )
    .await?;
    if let Some(release) = &release {
        host.writer().verify_current_authority().await?;
        crate::notes_bootstrap::activate_startup(&notes_bootstrap, release)?;
    }
    let operation_grants: Arc<dyn AgentdFinalUseGrantProvider> = grants.clone();
    let (operations, observer) = crate::notes_bootstrap::primary_notes_runtime(
        config,
        &host,
        notes_bootstrap,
        notes,
        operation_grants,
        verifier,
        reconcile_interval,
        release.as_ref().map(|release| &release.target),
    )
    .await?;
    let operations = operations.with_notes_receipt_recovery(observer.clone())?;
    // The same final live verifier and atomic installer as the joint profile.
    config.install_production_hosts(Arc::new(host), operations)?;
    Ok(AgentdRootProductionAttachment {
        root_session,
        checkpoint,
        grants,
        notes: Some(observer),
    })
}
