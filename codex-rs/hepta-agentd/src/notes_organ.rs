//! A finite Notes process profile over the original Agentd owners.
//!
//! The trusted embedding supplies the already composed original protected
//! writer, Root session and Notes target. This entry starts no model, generic
//! App Server, automation plane or federation reader. It does not install
//! authority, initialize an owner, or retry an unknown application effect.

use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdError;
use crate::AgentdRootAuthoritySession;
use crate::AgentdState;
use crate::RuntimeTasks;

const INTERVAL: Duration = Duration::from_millis(50);

/// Run the registered finite Notes Organ using its same protected original
/// writer and sole run coordinator. Unsupported control methods are refused.
/// App Server readiness remains false; Health describes this explicit profile.
/// This API alone is not native-kernel, ELF-size or full-daemon qualification.
pub async fn run_notes_organ(
    config: AgentdConfig,
    root: Arc<AgentdRootAuthoritySession>,
) -> Result<(), AgentdError> {
    let runtime_handle = tokio::runtime::Handle::current();
    if runtime_handle.runtime_flavor() != tokio::runtime::RuntimeFlavor::MultiThread
        || runtime_handle.metrics().num_workers() < 2
    {
        return Err(AgentdError::Invalid(
            "Notes Organ requires at least two original runtime workers".into(),
        ));
    }
    config.require_finite_notes_profile()?;
    let host = config.production_writer_host().ok_or_else(|| {
        AgentdError::Invalid("Notes Organ requires its recovered original writer".into())
    })?;
    let notes = config.notes_objective().ok_or_else(|| {
        AgentdError::Invalid("Notes Organ requires a fixed Notes Objective profile".into())
    })?;
    notes.validate_host(&host)?;
    let trust = config
        .authbus_trust_file()
        .ok_or_else(|| AgentdError::Invalid("Notes Organ requires original AuthBus trust".into()))?
        .to_owned();
    let checkpoint = config
        .authbus_checkpoint_file()
        .ok_or_else(|| {
            AgentdError::Invalid("Notes Organ requires the external replay checkpoint".into())
        })?
        .to_owned();
    let profile = config
        .objective_profile_file()
        .ok_or_else(|| {
            AgentdError::Invalid("Notes Organ requires its original admission profile".into())
        })?
        .to_owned();
    // This profile never accepts a second owner/adapter composition input.
    // The same host was independently recovered before this entry was called.
    let (identity, registry, writer_lock) = config.into_parts();
    let _writer_lock = writer_lock;
    let state = Arc::new(AgentdState::new(
        identity.clone(),
        registry,
        /*event_capacity*/ 128,
    )?);
    state.notes_organ_root.set(root).map_err(|_| {
        AgentdError::Invalid("Notes Organ Root session was already attached".into())
    })?;
    state
        .notes_objective
        .set(notes)
        .map_err(|_| AgentdError::Invalid("Notes Objective was already attached".into()))?;
    state.attach_production_operations(Arc::clone(&host))?;
    state.check_notes_organ_authority()?;
    state.refresh_generation()?;
    let authbus = crate::authbus_ingress::TextIngress::open(&identity, trust, checkpoint).await?;
    state.refresh_generation()?;
    state.check_notes_organ_authority()?;
    state.authbus.set(Arc::new(authbus)).map_err(|_| {
        AgentdError::Protocol("original AuthBus ingress was already attached".into())
    })?;
    let objective = crate::objective_runtime::ObjectiveRuntimeHost::open(&identity, &profile)?;
    state
        .objective_runtime
        .set(Arc::new(objective))
        .map_err(|_| {
            AgentdError::Protocol("original Objective owner was already attached".into())
        })?;
    let runtime = host.cognitive_runtime();
    let store = runtime.available_store().ok_or_else(|| {
        AgentdError::Invalid("Notes Organ cannot start with unavailable original storage".into())
    })?;
    state.attach_cognitive_store(Arc::clone(store))?;
    state.mark_runtime_prerequisites_ready()?;
    let cancellation = CancellationToken::new();
    let control = AgentdControlServer::bind(
        identity.control_socket,
        Arc::clone(&state),
        cancellation.clone(),
    )
    .await?;
    // Binding and every fallible owner open precede readiness/task startup.
    state.mark_notes_organ_ready()?;
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(3))?;
    let startup = (|| {
        tasks.spawn_required("notes-control", control.run_notes())?;
        tasks.spawn_required(
            "production-operation-reconciler",
            crate::runtime::run_production_operation_reconciler(
                host,
                INTERVAL,
                cancellation.clone(),
            ),
        )?;
        tasks.spawn_required(
            "notes-generation-monitor",
            monitor(Arc::clone(&state), cancellation),
        )?;
        Ok::<_, AgentdError>(())
    })();
    if let Err(error) = startup {
        tasks.shutdown().await;
        return Err(error);
    }
    tasks
        .run_until(async move {
            crate::runtime::shutdown_signal().await?;
            crate::runtime::drain_runtime(state).await
        })
        .await
}

async fn monitor(
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    loop {
        if cancellation.is_cancelled() {
            return Ok(());
        }
        let observed = async {
            state.check_notes_organ_authority()?;
            state.refresh_generation()?;
            if state.is_fenced()? {
                return Err(AgentdError::GenerationFenced(
                    "Notes Organ is fenced".into(),
                ));
            }
            state.expire_run_deadlines()?;
            let objective = state.objective_runtime.get().ok_or_else(|| {
                AgentdError::Protocol("original Objective owner disappeared".into())
            })?;
            objective.reconcile(
                &state,
                state.current_generation()?,
                crate::authbus_ingress::now_ms()?,
            )?;
            state.check_notes_organ_authority()?;
            objective.reconcile_notes(&state).await?;
            state.check_notes_organ_authority()
        }
        .await;
        if let Err(error) = observed {
            state.mark_fenced();
            return Err(error);
        }
        tokio::select! {
            () = cancellation.cancelled() => return Ok(()),
            () = tokio::time::sleep(INTERVAL) => {}
        }
    }
}
