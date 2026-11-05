//! Two original FinalUse consumers, one original Root session and one writer.
use crate::AgentdCalculatorStateObserver;
use crate::AgentdConfig;
use crate::AgentdDesktopStartupRelease;
use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;
use crate::AgentdProductionWriterHost;
use crate::AgentdRootProductionAttachment;
use crate::AgentdRootProductionInputs;
use crate::calculator_deadline::Deadline;
use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::time::Duration;

/// Retain the same original Root feed/checkpoint/grants and both read-only views.
pub struct AgentdDesktopProductionAttachment {
    pub root: AgentdRootProductionAttachment,
    pub calculator: AgentdCalculatorStateObserver,
}

/// Activate the exact sealed reservation after protected recovery, then consume
/// Notes and Calculator offers in Session order. The old Notes-only entry and
/// catalog remain unchanged. This entry alone creates no original Core thread.
pub async fn attach_root_desktop_operation_host_with_startup(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    bootstrap_channel: UnixDatagram,
    reconcile_interval: Duration,
    release: AgentdDesktopStartupRelease,
) -> Result<AgentdDesktopProductionAttachment, AgentdError> {
    attach_root_desktop_operation_host_with_startup_before(
        config,
        inputs,
        bootstrap_channel,
        reconcile_interval,
        release,
        Deadline::after(Duration::from_secs(30))?,
    )
    .await
}

/// The launcher passes its original parse-time budget through protected
/// recovery, activation and both ordered handoffs. No phase resets this clock.
pub(crate) async fn attach_root_desktop_operation_host_with_startup_before(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    bootstrap_channel: UnixDatagram,
    reconcile_interval: Duration,
    release: AgentdDesktopStartupRelease,
    end: Deadline,
) -> Result<AgentdDesktopProductionAttachment, AgentdError> {
    end.remaining()?;
    config.require_unconfigured_production_hosts()?;
    release.validate()?;
    if reconcile_interval.is_zero() {
        return Err(AgentdError::Invalid(
            "Desktop reconciliation interval must be nonzero".into(),
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
            "Desktop Root handoff differs from actual Agentd identity".into(),
        ));
    }
    let root_session = Arc::new(session);
    let authority = root_session.authority();
    let verifier = root_session.verifier();
    verifier
        .verify(&authority, &config.identity().agent_id)
        .map_err(AgentdError::GenerationFenced)?;
    config.retain_root_session(&root_session)?;
    let (host, checkpoint) = tokio::time::timeout(
        end.remaining()?,
        AgentdProductionWriterHost::open_with_protected_recovery(
            config,
            authority,
            Arc::clone(&verifier),
            bootstrap.writer.local_lease_id,
            bootstrap.writer.local_lease_generation,
            checkpoint,
        ),
    )
    .await
    .map_err(|_| AgentdError::Invalid("Desktop protected recovery deadline elapsed".into()))??;
    end.remaining()?;
    tokio::time::timeout(end.remaining()?, host.writer().verify_current_authority())
        .await
        .map_err(|_| AgentdError::Invalid("Desktop authority deadline elapsed".into()))??;
    end.remaining()?;
    crate::desktop_startup::activate_before(&bootstrap_channel, &release, end)?;
    let operation_grants: Arc<dyn AgentdFinalUseGrantProvider> = grants.clone();
    let (operations, notes_observer) = crate::notes_bootstrap::primary_notes_runtime_before(
        config,
        &host,
        bootstrap_channel.try_clone()?,
        notes,
        operation_grants,
        verifier,
        reconcile_interval,
        Some(&release.notes),
        end,
    )
    .await?;
    let (operations, calculator) = operations
        .with_calculator_from_session_expected_before(
            config,
            &host,
            bootstrap_channel,
            device,
            &release.calculator,
            end,
        )
        .await?;
    let operations = operations.with_notes_receipt_recovery(notes_observer.clone())?;
    end.remaining()?;
    // Opening the new local lease can leave the original owner Dirty. Publish
    // its actual cut only here, after both authenticated handoffs and before
    // installing the sole owner. Recovery selectors remain strictly read-only.
    tokio::time::timeout(end.remaining()?, host.writer().acknowledge_current())
        .await
        .map_err(|_| {
            AgentdError::Invalid("Desktop Current acknowledgement deadline elapsed".into())
        })?
        .map_err(|error| {
            AgentdError::Invalid(format!("Desktop original Current acknowledgement: {error}"))
        })?;
    end.remaining()?;
    // The original atomic installer checks live authority after all handoffs
    // and awaits, then publishes the sole writer/runtime without another await.
    config.install_production_hosts(Arc::new(host), operations)?;
    end.remaining()?;
    Ok(AgentdDesktopProductionAttachment {
        root: AgentdRootProductionAttachment {
            root_session,
            checkpoint,
            grants,
            notes: Some(notes_observer),
        },
        calculator,
    })
}
