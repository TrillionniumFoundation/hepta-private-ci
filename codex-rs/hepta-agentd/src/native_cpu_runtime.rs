//! Native CPU process profile using the original Agentd owners and lifecycle.
//! The trusted kernel entry supplies the already recovered, bound writer and
//! same Root session. Public ordinary configuration never enables this profile.

use crate::AgentdConfig;
use crate::AgentdControlServer;
use crate::AgentdError;
use crate::AgentdRootAuthoritySession;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::state::NativeCpuRuntimeOwners;
use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

pub(crate) async fn run_native_cpu_owner_until<S>(
    config: AgentdConfig,
    root: Arc<AgentdRootAuthoritySession>,
    ingress: Arc<crate::native_cpu_ingress::NativeCpuIngress>,
    owner_control: S,
) -> Result<(), AgentdError>
where
    S: Future<Output = Result<(), AgentdError>> + Send,
{
    let runtime_handle = tokio::runtime::Handle::current();
    if runtime_handle.runtime_flavor() != tokio::runtime::RuntimeFlavor::MultiThread
        || runtime_handle.metrics().num_workers() < 2
    {
        return Err(AgentdError::Invalid(
            "native CPU owner requires two original runtime workers".into(),
        ));
    }
    config.require_finite_native_cpu_profile()?;
    let host = config.production_writer_host().ok_or_else(|| {
        AgentdError::Invalid("native CPU owner requires its recovered original writer".into())
    })?;
    let (identity, registry, writer_lock) = config.into_parts();
    let _writer_lock = writer_lock;
    let state = Arc::new(AgentdState::<NativeCpuRuntimeOwners>::new_native_cpu(
        identity.clone(),
        registry,
        /*event_capacity*/ 128,
    )?);
    ingress.attach_state(&state)?;
    state
        .native_cpu_ingress
        .set(ingress.clone())
        .map_err(|_| AgentdError::Invalid("native ingress already attached".into()))?;
    state
        .native_cpu_root
        .set(root)
        .map_err(|_| AgentdError::Invalid("native Root already attached".into()))?;
    state.attach_production_operations(Arc::clone(&host))?;
    state.check_native_cpu_authority()?;
    state.refresh_generation()?;
    let runtime = host.cognitive_runtime();
    let store = runtime
        .available_store()
        .ok_or_else(|| AgentdError::Invalid("native CPU original storage is unavailable".into()))?;
    state.attach_cognitive_store(Arc::clone(store))?;
    state.mark_runtime_prerequisites_ready()?;
    let cancellation = CancellationToken::new();
    let control =
        AgentdControlServer::bind(identity.control_socket, state.clone(), cancellation.clone())
            .await?;
    state.mark_native_cpu_ready()?;
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(3))?;
    let startup = (|| {
        tasks.spawn_required("native-cpu-lifecycle", control.run_native_cpu())?;
        tasks.spawn_required(
            "native-cpu-owner-monitor",
            monitor(state.clone(), host.clone(), ingress.clone(), cancellation),
        )?;
        Ok::<_, AgentdError>(())
    })();
    if let Err(error) = startup {
        tasks.shutdown().await;
        return Err(error);
    }
    let stopping = ingress.clone();
    let stopping_host = host.clone();
    tasks
        .run_until(async move {
            tokio::pin!(owner_control);
            let completed = tokio::select! {
                result = crate::runtime::shutdown_signal() => { result?; None },
                result = &mut owner_control => Some(result),
            };
            // Close new admission first. An already entered command is retained
            // through completion; its original future is never dropped at signal.
            stopping.stop();
            match completed {
                Some(result) => result?,
                None => tokio::time::timeout(Duration::from_secs(10), &mut owner_control)
                    .await
                    .map_err(|_| {
                        AgentdError::Protocol(
                            "native original command did not finish within shutdown bound".into(),
                        )
                    })??,
            }
            let end = tokio::time::Instant::now() + Duration::from_secs(10);
            while stopping.blockers(&stopping_host).await? != 0 {
                if tokio::time::Instant::now() >= end {
                    return Err(AgentdError::Protocol(
                        "native original owner retains queued or indeterminate work".into(),
                    ));
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            state.mark_draining()
        })
        .await?;
    // All runtime workers are joined before the one original owner publishes
    // its terminal Current and permanently retires the same SQLite pool.
    host.writer()
        .release()
        .await
        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
    // This clones only the existing store handle. Its original close barrier
    // shuts the same shared SQLite pools; it opens no new owner or database.
    // Remaining handles are dropped before this Host exits and Root may reap it.
    store.as_ref().clone().close().await;
    Ok(())
}

async fn monitor(
    state: Arc<AgentdState<NativeCpuRuntimeOwners>>,
    host: Arc<crate::AgentdProductionWriterHost>,
    ingress: Arc<crate::native_cpu_ingress::NativeCpuIngress>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    loop {
        if cancellation.is_cancelled() {
            return Ok(());
        }
        let observed = async {
            if ingress.stopping() {
                return Ok(());
            }
            let _command = ingress.maintenance_guard().await;
            if ingress.stopping() {
                return Ok(());
            }
            state.check_native_cpu_authority()?;
            state.refresh_generation()?;
            if state.is_fenced()? {
                return Err(AgentdError::GenerationFenced(
                    "native CPU owner is fenced".into(),
                ));
            }
            if !ingress.closed() && state.native_cpu_admission_open()? {
                host.reauthorize_pending_for_destination(
                    codex_hepta_memory::HOS2_DESTINATION_V1,
                    /*limit*/ 256,
                )
                .await?;
            }
            host.reconcile_for_destination(
                codex_hepta_memory::HOS2_DESTINATION_V1,
                /*limit*/ 256,
            )
            .await?;
            state.check_native_cpu_authority()
        }
        .await;
        if let Err(error) = observed {
            state.mark_fenced();
            return Err(error);
        }
        tokio::select! {
            () = cancellation.cancelled() => return Ok(()),
            () = tokio::time::sleep(Duration::from_millis(50)) => {}
        }
    }
}
