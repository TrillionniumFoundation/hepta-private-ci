//! Custody for one actual configured local Legacy MCP startup.
//! Admission is closed before cleanup. Actual startup and driver handles
//! remain owned through waiter cancellation; no count substitutes for join.

use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use codex_config::McpServerTransportConfig;
use codex_rmcp_client::OriginalMcpClientShutdown;
use codex_rmcp_client::OriginalMcpClientShutdownObservation;
use tokio::sync::Mutex;
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

use crate::McpProtocolMode;
use crate::McpRuntimeInput;
use crate::McpStartupPolicy;
use crate::mcp::CODEX_APPS_MCP_SERVER_NAME;
use crate::rmcp_client::ManagedClient;
use crate::rmcp_client::StartupOutcomeError;

type StartupOutput = (String, Result<ManagedClient, StartupOutcomeError>);

/// Externally retained before the actual configured initializer is polled.
/// This empty object cannot choose a server, command, credential or policy.
pub struct OriginalMcpRuntimeShutdown {
    stopped: AtomicBool,
    state: StdMutex<OriginalRuntimeState>,
    changed: Notify,
    cleanup: StdMutex<Option<Arc<OriginalCleanupJob>>>,
}

struct OriginalRuntimeState {
    constructor_used: bool,
    constructing: bool,
    startup: Option<CancellationToken>,
    client: Option<Arc<OriginalMcpClientShutdown>>,
    startup_jobs: Vec<Arc<OriginalStartupJob>>,
    custody_failure: Option<String>,
}

pub(crate) struct OriginalMcpConstructionGuard {
    owner: Arc<OriginalMcpRuntimeShutdown>,
}

struct OriginalStartupJob {
    state: Mutex<OriginalStartupJobState>,
}

struct OriginalStartupJobState {
    handle: Option<JoinHandle<OriginalStartupJoined>>,
    joined: Option<OriginalStartupJoined>,
}

#[derive(Clone)]
struct OriginalStartupJoined {
    ready: usize,
    errors: Vec<String>,
}

struct OriginalCleanupJob {
    state: Mutex<OriginalCleanupJobState>,
}

struct OriginalCleanupJobState {
    handle: Option<JoinHandle<Result<Arc<OriginalMcpRuntimeShutdownObservation>, String>>>,
    result: Option<Result<Arc<OriginalMcpRuntimeShutdownObservation>, String>>,
}

/// Actual cleanup facts, not business completion or authority permission.
pub struct OriginalMcpRuntimeShutdownObservation {
    startups: Vec<OriginalStartupJoined>,
    client: Option<OriginalMcpClientShutdownObservation>,
}

impl OriginalMcpRuntimeShutdownObservation {
    pub fn require_original_ready_runtime_joined(&self) -> Result<()> {
        ensure!(
            self.startups.len() == 1,
            "original MCP startup custody is incomplete"
        );
        let startup = &self.startups[0];
        ensure!(
            startup.ready == 1 && startup.errors.is_empty(),
            "original MCP startup did not join with one successful configured client"
        );
        OriginalMcpClientShutdownObservation::require_original_ready_client_joined(
            self.client
                .as_ref()
                .ok_or_else(|| anyhow!("original MCP client was never constructed"))?,
        )
    }
}

impl OriginalMcpRuntimeShutdown {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            stopped: AtomicBool::new(false),
            state: StdMutex::new(OriginalRuntimeState {
                constructor_used: false,
                constructing: false,
                startup: None,
                client: None,
                startup_jobs: Vec::new(),
                custody_failure: None,
            }),
            changed: Notify::new(),
            cleanup: StdMutex::new(None),
        })
    }

    pub(crate) fn reserve_original_input(
        self: &Arc<Self>,
        input: &McpRuntimeInput,
    ) -> Result<OriginalMcpConstructionGuard> {
        ensure!(
            cfg!(target_os = "linux"),
            "owned MCP cleanup requires Linux"
        );
        ensure!(
            input.startup_policy == McpStartupPolicy::Eager,
            "owned MCP startup cannot be deferred"
        );
        ensure!(
            input.config.protocol_mode == McpProtocolMode::Legacy,
            "owned MCP startup requires the actual retained Legacy profile"
        );
        ensure!(
            input.tx_event.is_none()
                && input.elicitation_reviewer.is_none()
                && input.elicitation_lifecycle.is_none(),
            "owned MCP profile requires its original threadless handler policy"
        );
        ensure!(
            input.mcp_servers.len() == 1,
            "owned MCP startup requires one explicitly configured server"
        );
        let (name, server) = input
            .mcp_servers
            .iter()
            .next()
            .ok_or_else(|| anyhow!("original MCP server is absent"))?;
        ensure!(
            name != CODEX_APPS_MCP_SERVER_NAME && server.enabled(),
            "owned MCP startup cannot reconnect hosted Apps or a disabled server"
        );
        ensure!(
            server.config().is_local_environment()
                && matches!(
                    &server.config().transport,
                    McpServerTransportConfig::Stdio { .. }
                ),
            "owned MCP shutdown supports the configured local stdio transport only"
        );
        let mut state = self
            .state
            .lock()
            .map_err(|_| anyhow!("original MCP startup custody is poisoned"))?;
        ensure!(
            !self.stopped.load(Ordering::Acquire) && !state.constructor_used,
            "original MCP startup cannot be reopened"
        );
        state.constructor_used = true;
        state.constructing = true;
        state.startup = Some(input.startup_cancellation_token.clone());
        state.client = Some(OriginalMcpClientShutdown::new(
            input.runtime_context.local_process_cwd(),
        ));
        Ok(OriginalMcpConstructionGuard {
            owner: Arc::clone(self),
        })
    }

    pub(crate) fn original_client_custody(&self) -> Result<Arc<OriginalMcpClientShutdown>> {
        let state = self
            .state
            .lock()
            .map_err(|_| anyhow!("original MCP startup custody is poisoned"))?;
        ensure!(
            !self.stopped.load(Ordering::Acquire)
                && state.constructor_used
                && state.custody_failure.is_none(),
            "original MCP construction is no longer admitted"
        );
        state
            .client
            .as_ref()
            .map(Arc::clone)
            .ok_or_else(|| anyhow!("actual MCP construction custody is absent"))
    }

    pub(crate) fn require_original_construction(&self) -> Result<()> {
        let state = self
            .state
            .lock()
            .map_err(|_| anyhow!("original MCP startup custody is poisoned"))?;
        ensure!(
            !self.stopped.load(Ordering::Acquire)
                && state.constructing
                && state.custody_failure.is_none(),
            "actual original MCP construction was cancelled or refused"
        );
        Ok(())
    }

    pub(crate) fn retain_original_startup(&self, mut actual: JoinSet<StartupOutput>) {
        let poisoned = self.state.is_poisoned();
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if poisoned || !state.constructing || !state.startup_jobs.is_empty() {
            state.custody_failure = Some("original startup handle registration was refused".into());
        }
        // No await separates creation of this actual task from registration
        // of its handle. Unlike JoinSet::join_all, one failed child does not
        // discard the remaining original child handles.
        let handle = tokio::spawn(async move {
            let mut joined = OriginalStartupJoined {
                ready: 0,
                errors: Vec::new(),
            };
            while let Some(result) = actual.join_next().await {
                match result {
                    Ok((_name, Ok(client))) => {
                        joined.ready += 1;
                        drop(client);
                    }
                    Ok((name, Err(error))) => joined.errors.push(format!("{name}: {error}")),
                    Err(error) => joined
                        .errors
                        .push(format!("actual MCP startup task: {error}")),
                }
            }
            joined
        });
        state.startup_jobs.push(Arc::new(OriginalStartupJob {
            state: Mutex::new(OriginalStartupJobState {
                handle: Some(handle),
                joined: None,
            }),
        }));
    }

    pub fn request_stop(&self) {
        self.stopped.store(true, Ordering::Release);
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(startup) = &state.startup {
            startup.cancel();
        }
        if let Some(client) = &state.client {
            OriginalMcpClientShutdown::request_stop(client);
        }
        drop(state);
        self.changed.notify_waiters();
    }

    /// Starts and retains the real cleanup task before returning its waiter.
    /// Dropping the waiter cannot take the handle or the original result.
    pub fn stop_and_join_original_runtime(
        self: &Arc<Self>,
    ) -> impl std::future::Future<Output = Result<Arc<OriginalMcpRuntimeShutdownObservation>>>
    + Send
    + 'static {
        self.request_stop();
        let job = {
            let mut slot = self
                .cleanup
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if let Some(job) = slot.as_ref() {
                Arc::clone(job)
            } else {
                let owner = Arc::clone(self);
                let handle = tokio::spawn(async move { owner.join_original_resources().await });
                let job = Arc::new(OriginalCleanupJob {
                    state: Mutex::new(OriginalCleanupJobState {
                        handle: Some(handle),
                        result: None,
                    }),
                });
                *slot = Some(Arc::clone(&job));
                job
            }
        };
        async move {
            job.receive_original_cleanup()
                .await
                .map_err(|error| anyhow!(error))
        }
    }

    async fn join_original_resources(
        self: Arc<Self>,
    ) -> Result<Arc<OriginalMcpRuntimeShutdownObservation>, String> {
        // A cancelled constructor drops its guard before cleanup can snapshot
        // the registered real handles. A stop before reservation rejects start.
        loop {
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            let constructing = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .constructing;
            if !constructing {
                break;
            }
            changed.await;
        }
        let (jobs, client, mut first_error) = {
            let state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let failure = if self.state.is_poisoned() || self.cleanup.is_poisoned() {
                Some("original MCP cleanup custody is poisoned".to_string())
            } else {
                state.custody_failure.clone()
            };
            (state.startup_jobs.clone(), state.client.clone(), failure)
        };
        let mut startups = Vec::new();
        for job in jobs {
            let joined = job.join_original_startup().await;
            if first_error.is_none() && !joined.errors.is_empty() {
                first_error = Some(joined.errors.join("; "));
            }
            startups.push(joined);
        }
        // The real startup jobs have ended; no client/service can appear after
        // this cut. Always drive driver/Child cleanup even after startup errors.
        let client = if let Some(client) = client {
            match OriginalMcpClientShutdown::join_original_client(&client).await {
                Ok(observed) => Some(observed),
                Err(error) => {
                    if first_error.is_none() {
                        first_error = Some(error.to_string());
                    } else {
                        tracing::error!(error = %error, "additional original MCP cleanup failure");
                    }
                    None
                }
            }
        } else {
            None
        };
        if let Some(error) = first_error {
            return Err(error);
        }
        Ok(Arc::new(OriginalMcpRuntimeShutdownObservation {
            startups,
            client,
        }))
    }
}

impl Drop for OriginalMcpConstructionGuard {
    fn drop(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.constructing = false;
        drop(state);
        self.owner.changed.notify_waiters();
    }
}

impl OriginalStartupJob {
    async fn join_original_startup(&self) -> OriginalStartupJoined {
        let mut state = self.state.lock().await;
        if let Some(joined) = &state.joined {
            return joined.clone();
        }
        let joined = match state.handle.as_mut() {
            Some(handle) => match handle.await {
                Ok(joined) => joined,
                Err(error) => OriginalStartupJoined {
                    ready: 0,
                    errors: vec![format!("actual MCP startup join owner: {error}")],
                },
            },
            None => OriginalStartupJoined {
                ready: 0,
                errors: vec!["actual MCP startup handle is missing".into()],
            },
        };
        state.handle.take();
        state.joined = Some(joined.clone());
        joined
    }
}

impl OriginalCleanupJob {
    async fn receive_original_cleanup(
        &self,
    ) -> Result<Arc<OriginalMcpRuntimeShutdownObservation>, String> {
        let mut state = self.state.lock().await;
        if let Some(result) = &state.result {
            return result.clone();
        }
        let result = match state.handle.as_mut() {
            Some(handle) => match handle.await {
                Ok(result) => result,
                Err(error) => Err(format!("actual MCP cleanup owner failed: {error}")),
            },
            None => Err("actual MCP cleanup handle is missing".into()),
        };
        state.handle.take();
        state.result = Some(result.clone());
        result
    }
}

impl Drop for OriginalMcpRuntimeShutdown {
    fn drop(&mut self) {
        self.request_stop();
    }
}
