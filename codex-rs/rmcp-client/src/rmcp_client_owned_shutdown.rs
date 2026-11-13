//! Physical custody for the selected original local Legacy MCP client.
//! This joins its real service driver and stdio owners. It does not claim
//! to join SDK protocol/logging callbacks which hold no Agentd owners.

use std::collections::HashMap;
use std::ffi::OsString;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use codex_config::types::McpServerEnvVar;
use rmcp::service::QuitReason;
use rmcp::service::RoleClient;
use rmcp::service::RunningService;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use super::ClientState;
use super::PendingTransport;
use super::RmcpClient;
use crate::McpProtocolMode;
use crate::elicitation_client_service::ElicitationClientService;
use crate::stdio_server_launcher::LocalStdioServerLauncher;
use crate::stdio_server_launcher::OriginalStdioShutdownCustody;
use crate::stdio_server_launcher::OriginalStdioShutdownObservation;
use crate::stdio_server_launcher::StdioServerLauncher;

type OriginalService = RunningService<RoleClient, ElicitationClientService>;

/// Empty custody creates neither an MCP peer nor operation permission.
/// Only the concrete local Legacy constructor below installs a client.
pub struct OriginalMcpClientShutdown {
    fallback_cwd: PathBuf,
    stdio: Arc<OriginalStdioShutdownCustody>,
    stopped: AtomicBool,
    state: StdMutex<OriginalClientState>,
}

struct OriginalClientState {
    constructor_used: bool,
    client: Option<Weak<RmcpClient>>,
    service: Option<Arc<OriginalService>>,
    extra_services: Vec<Arc<OriginalService>>,
    driver: Option<Arc<OriginalDriverJob>>,
}

struct OriginalDriverJob {
    state: Mutex<OriginalDriverState>,
}

struct OriginalDriverState {
    handle: Option<JoinHandle<Result<OriginalDriverJoined, String>>>,
    result: Option<Result<OriginalDriverJoined, String>>,
}

#[derive(Clone, Debug)]
enum OriginalDriverJoined {
    Cancelled,
    Closed,
}

/// A cleanup observation, never a business or authority capability.
/// Callers cannot fill these fields or deserialize them from a peer.
pub struct OriginalMcpClientShutdownObservation {
    driver: Option<OriginalDriverJoined>,
    stdio: OriginalStdioShutdownObservation,
}

impl OriginalMcpClientShutdownObservation {
    pub fn require_original_ready_client_joined(&self) -> Result<()> {
        ensure!(
            self.driver.is_some(),
            "original MCP service never became an owned driver"
        );
        self.stdio
            .require_original_child_exited()
            .map_err(|error| anyhow!("original MCP child was not joined: {error}"))
    }
}

impl OriginalMcpClientShutdown {
    pub fn new(fallback_cwd: PathBuf) -> Arc<Self> {
        Arc::new(Self {
            fallback_cwd,
            stdio: OriginalStdioShutdownCustody::new(),
            stopped: AtomicBool::new(false),
            state: StdMutex::new(OriginalClientState {
                constructor_used: false,
                client: None,
                service: None,
                extra_services: Vec::new(),
                driver: None,
            }),
        })
    }

    pub fn request_stop(&self) {
        self.stopped.store(true, Ordering::Release);
        // Poison grants cleanup access only, never another start.
        let state = self.state.lock().unwrap_or_else(|error| error.into_inner());
        if let Some(service) = &state.service {
            service.cancellation_token().cancel();
        }
        for service in &state.extra_services {
            service.cancellation_token().cancel();
        }
        drop(state);
        self.stdio.request_stop();
    }

    fn reserve_original_constructor(&self) -> Result<()> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| anyhow!("original MCP client custody is poisoned"))?;
        ensure!(
            !self.stopped.load(Ordering::Acquire) && !state.constructor_used,
            "original MCP client custody cannot be restarted"
        );
        state.constructor_used = true;
        Ok(())
    }

    fn retain_original_client(&self, client: &Arc<RmcpClient>) -> Result<()> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| anyhow!("original MCP client custody is poisoned"))?;
        ensure!(
            state.constructor_used && state.client.is_none(),
            "original MCP client cannot be replaced"
        );
        state.client = Some(Arc::downgrade(client));
        Ok(())
    }

    pub(super) fn retain_original_service(&self, service: &Arc<OriginalService>) -> Result<()> {
        let poisoned = self.state.is_poisoned();
        let mut state = self.state.lock().unwrap_or_else(|error| error.into_inner());
        // The original handshake already created this driver. Even poison
        // must retain it for cleanup before returning the refusal.
        let duplicate = state.service.is_some() || state.driver.is_some();
        if duplicate {
            state.extra_services.push(Arc::clone(service));
        } else {
            state.service = Some(Arc::clone(service));
        }
        if poisoned || !state.constructor_used || duplicate || self.stopped.load(Ordering::Acquire)
        {
            service.cancellation_token().cancel();
            return Err(anyhow!("original MCP service publication was refused"));
        }
        Ok(())
    }

    fn start_original_driver_join(&self) -> Option<Arc<OriginalDriverJob>> {
        let mut state = self.state.lock().unwrap_or_else(|error| error.into_inner());
        if let Some(job) = &state.driver {
            return Some(Arc::clone(job));
        }
        let service = state.service.take()?;
        let extra_services = std::mem::take(&mut state.extra_services);
        // The outer registry has already joined the actual startup work.
        // This real service and the resulting handle move into one registered
        // cleanup task without an await gap. Waiter cancellation cannot
        // detach the task or take away the SDK service handle.
        let handle = tokio::spawn(async move {
            let duplicate = !extra_services.is_empty();
            let mut actual = Vec::with_capacity(1 + extra_services.len());
            actual.push(service);
            actual.extend(extra_services);
            let mut primary = None;
            let mut first_error = duplicate
                .then(|| "original MCP startup produced more than one service".to_string());
            for service in actual {
                match join_actual_original_service(service).await {
                    Ok(joined) => {
                        if primary.is_none() {
                            primary = Some(joined);
                        }
                    }
                    Err(error) => {
                        if first_error.is_none() {
                            first_error = Some(error);
                        } else {
                            tracing::error!(error = %error, "additional original service join failure");
                        }
                    }
                }
            }
            if let Some(error) = first_error {
                return Err(error);
            }
            primary.ok_or_else(|| "original service join result missing".into())
        });
        let job = Arc::new(OriginalDriverJob {
            state: Mutex::new(OriginalDriverState {
                handle: Some(handle),
                result: None,
            }),
        });
        state.driver = Some(Arc::clone(&job));
        Some(job)
    }

    /// The configured startup registry must first join its real startup jobs.
    /// It then retains the actual cleanup task which drives this method.
    pub async fn join_original_client(&self) -> Result<OriginalMcpClientShutdownObservation> {
        self.request_stop();
        let mut first_error = self
            .state
            .is_poisoned()
            .then(|| anyhow!("original MCP client custody was poisoned"));
        let client = self
            .state
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .client
            .as_ref()
            .and_then(Weak::upgrade);
        if let Some(client) = client {
            // Only the client retained synchronously by our constructor is
            // reachable; no caller-supplied replacement is accepted.
            let previous = {
                let mut state = client.state.lock().await;
                std::mem::replace(&mut *state, ClientState::Closed)
            };
            match previous {
                ClientState::Connecting {
                    transport: Some(PendingTransport::Stdio { mut transport }),
                } => {
                    use rmcp::transport::Transport;
                    if let Err(error) = transport.close().await {
                        if first_error.is_none() {
                            first_error =
                                Some(anyhow!("original pending MCP transport close: {error}"));
                        }
                    }
                }
                // Ready's Arc was retained before the first subsequent await.
                // Dropping this state cancels the original retained-call lifetime.
                other => drop(other),
            }
        }
        let driver = match self.start_original_driver_join() {
            Some(job) => match job.join_original().await {
                Ok(joined) => Some(joined),
                Err(error) => {
                    if first_error.is_none() {
                        first_error = Some(anyhow!(error));
                    }
                    None
                }
            },
            None => None,
        };
        let stdio = self
            .stdio
            .join_original_stdio()
            .await
            .map_err(|error| anyhow!("original MCP stdio owners did not join: {error}"));
        match (first_error, stdio) {
            (Some(error), Err(cleanup)) => {
                tracing::error!(error = %cleanup, "additional original MCP stdio cleanup failure");
                Err(error)
            }
            (Some(error), Ok(_)) => Err(error),
            (None, Err(error)) => Err(error),
            (None, Ok(stdio)) => Ok(OriginalMcpClientShutdownObservation { driver, stdio }),
        }
    }
}

async fn join_actual_original_service(
    service: Arc<OriginalService>,
) -> Result<OriginalDriverJoined, String> {
    let mut retained = service;
    loop {
        retained.cancellation_token().cancel();
        match Arc::try_unwrap(retained) {
            Ok(service) => {
                return match service.cancel().await {
                    Ok(QuitReason::Cancelled) => Ok(OriginalDriverJoined::Cancelled),
                    Ok(QuitReason::Closed) => Ok(OriginalDriverJoined::Closed),
                    Ok(QuitReason::JoinError(error)) => {
                        Err(format!("original MCP service subtask failed: {error}"))
                    }
                    Ok(_) => Err("original MCP service returned an unknown quit reason".into()),
                    Err(error) => Err(format!(
                        "actual original MCP service driver failed to join: {error}"
                    )),
                };
            }
            Err(service) => retained = service,
        }
        // Actual retained users must release their service references.
        // This is no request retry or join proof: the only success above
        // awaits the original SDK JoinHandle without a timeout.
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
}

impl OriginalDriverJob {
    async fn join_original(&self) -> Result<OriginalDriverJoined, String> {
        let mut state = self.state.lock().await;
        if let Some(result) = &state.result {
            return result.clone();
        }
        let result = match state.handle.as_mut() {
            Some(handle) => match handle.await {
                Ok(result) => result,
                Err(error) => Err(format!("original MCP driver cleanup task failed: {error}")),
            },
            None => Err("original MCP driver join custody is unavailable".into()),
        };
        state.handle.take();
        state.result = Some(result.clone());
        result
    }
}

impl Drop for OriginalMcpClientShutdown {
    fn drop(&mut self) {
        self.request_stop();
    }
}

impl RmcpClient {
    /// The original configured local Legacy constructor, with real custody.
    pub async fn new_stdio_client_with_owned_shutdown(
        program: OsString,
        args: Vec<OsString>,
        env: Option<HashMap<OsString, OsString>>,
        env_vars: &[McpServerEnvVar],
        cwd: Option<String>,
        owner: Arc<OriginalMcpClientShutdown>,
    ) -> std::io::Result<Arc<Self>> {
        if !cfg!(target_os = "linux") {
            return Err(std::io::Error::new(
                std::io::ErrorKind::Unsupported,
                "owned MCP shutdown requires the Linux local Legacy profile",
            ));
        }
        owner
            .reserve_original_constructor()
            .map_err(std::io::Error::other)?;
        let launcher: Arc<dyn StdioServerLauncher> =
            Arc::new(LocalStdioServerLauncher::new_with_owned_shutdown(
                owner.fallback_cwd.clone(),
                Arc::clone(&owner.stdio),
            ));
        let mut client = Self::new_stdio_client_with_protocol_mode(
            program,
            args,
            env,
            env_vars,
            cwd,
            launcher,
            McpProtocolMode::Legacy,
        )
        .await?;
        client.original_owned_shutdown = Some(Arc::clone(&owner));
        let client = Arc::new(client);
        owner
            .retain_original_client(&client)
            .map_err(std::io::Error::other)?;
        Ok(client)
    }
}
