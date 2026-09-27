//! Daemon entrypoint with atomic canonical product composition.
//!
//! The legacy implementation remains in `runtime_base.rs`. This owner wrapper
//! starts the installed runtime.codex supervisor as a required sibling: either
//! service exiting first stops the other, and a partial runner/provider profile
//! is rejected before daemon services open.

#[path = "runtime_base.rs"]
mod base;

use codex_arg0::Arg0DispatchPaths;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::ProcessRuntimeCodexExecutorV1;
use crate::canonical_runtime_bootstrap::take_pending_canonical_runtime_bootstrap;

pub async fn run(
    config: AgentdConfig,
    arg0_paths: Arg0DispatchPaths,
) -> Result<(), AgentdError> {
    let legacy_runner = config.intelligence_product_runner().is_some();
    let legacy_provider = config.intelligence_invocation_provider().is_some();
    let bootstrap = take_pending_canonical_runtime_bootstrap()?;

    match bootstrap {
        None if legacy_runner || legacy_provider => {
            return Err(AgentdError::Invalid(
                "canonical intelligence must be installed through AgentdCanonicalRuntimeBootstrapV1; partial runner/provider attachment is forbidden"
                    .to_string(),
            ));
        }
        None => return base::run(config, arg0_paths).await,
        Some(_) if legacy_runner || legacy_provider => {
            return Err(AgentdError::Invalid(
                "canonical runtime bootstrap conflicts with separately attached runner/provider"
                    .to_string(),
            ));
        }
        Some(bootstrap) => {
            let identity = config.identity().clone();
            let installed = bootstrap.install_executor(&identity)?;
            let startup_timeout = installed.startup_timeout;
            let shutdown_timeout = installed.shutdown_timeout;
            let lifetime = CancellationToken::new();
            let supervisor_lifetime = lifetime.clone();
            let supervisor_identity = identity.clone();
            let mut supervisor = tokio::spawn(async move {
                ProcessRuntimeCodexExecutorV1::run_installed_agentd_supervisor(
                    supervisor_identity,
                    supervisor_lifetime,
                )
                .await
            });

            let startup = tokio::select! {
                status = ProcessRuntimeCodexExecutorV1::wait_agentd_supervisor_started(startup_timeout) => status,
                joined = &mut supervisor => {
                    let result = joined.map_err(|error| {
                        AgentdError::Protocol(format!(
                            "runtime.codex supervisor startup task failed: {error}"
                        ))
                    })?;
                    return match result {
                        Ok(()) => Err(AgentdError::Protocol(
                            "runtime.codex supervisor exited before startup completed".to_string(),
                        )),
                        Err(error) => Err(error),
                    };
                }
            }?;
            if !startup.started {
                lifetime.cancel();
                return Err(AgentdError::Protocol(
                    "runtime.codex supervisor did not publish startup reconciliation"
                        .to_string(),
                ));
            }
            let config = installed.attach(config)?;

            let daemon = base::run(config, arg0_paths);
            tokio::pin!(daemon);
            let daemon_result = tokio::select! {
                result = &mut daemon => result,
                joined = &mut supervisor => {
                    lifetime.cancel();
                    let supervisor_result = joined.map_err(|error| {
                        AgentdError::Protocol(format!("runtime.codex supervisor task failed: {error}"))
                    })?;
                    return match supervisor_result {
                        Ok(()) => Err(AgentdError::Protocol(
                            "runtime.codex supervisor exited before Agentd shutdown".to_string(),
                        )),
                        Err(error) => Err(error),
                    };
                }
            };

            lifetime.cancel();
            let supervisor_result = match timeout(shutdown_timeout, &mut supervisor).await {
                Ok(joined) => joined.map_err(|error| {
                    AgentdError::Protocol(format!(
                        "runtime.codex supervisor shutdown task failed: {error}"
                    ))
                })?,
                Err(_) => {
                    supervisor.abort();
                    let _ = supervisor.await;
                    return Err(AgentdError::Protocol(
                        "runtime.codex supervisor exceeded the canonical shutdown deadline"
                            .to_string(),
                    ));
                }
            };

            match (daemon_result, supervisor_result) {
                (Err(error), _) => Err(error),
                (Ok(()), Err(error)) => Err(error),
                (Ok(()), Ok(())) => Ok(()),
            }
        }
    }
}
