//! Bounded connection tasks for the existing read-only loopback listener.
//!
//! The set owns accepted connection futures, including completed tasks awaiting
//! reaping. Capacity exhaustion stops accepting sockets; it does not allocate
//! a second userspace queue. Kernel backlog and runtime snapshot memory remain
//! separate resources. This is not peer authentication or an effect executor.

use std::future::Future;
use std::io;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_runtime::HeptaRuntime;
use tokio::net::TcpListener;
use tokio::task::JoinSet;

use crate::RESPONSE_TIMEOUT;
use crate::serve_connection;

pub(super) const MAX_CONNECTIONS: usize = 64;

/// Run the one normal listener with a bounded task set and consuming shutdown.
/// The private limit can narrow, but cannot enlarge, the gateway's hard ceiling.
pub(super) async fn serve(
    listener: TcpListener,
    runtime: Arc<HeptaRuntime>,
    max_connections: usize,
    shutdown: impl Future<Output = io::Result<()>>,
) -> Result<()> {
    if !(1..=MAX_CONNECTIONS).contains(&max_connections) {
        anyhow::bail!("invalid loopback connection limit");
    }
    if !listener.local_addr()?.ip().is_loopback() {
        anyhow::bail!("bounded gateway listener must be loopback-only");
    }
    let mut connections = JoinSet::new();
    tokio::pin!(shutdown);
    let outcome = loop {
        tokio::select! {
            biased;
            signal = &mut shutdown => {
                break signal.context("wait for gateway shutdown signal");
            }
            accepted = listener.accept(), if connections.len() < max_connections => {
                let (stream, peer) = match accepted {
                    Ok(accepted) => accepted,
                    Err(error) => break Err(error).context("accept loopback gateway connection"),
                };
                if !peer.ip().is_loopback() {
                    continue;
                }
                let runtime = Arc::clone(&runtime);
                connections.spawn(async move {
                    if let Err(error) = serve_connection(stream, runtime).await {
                        eprintln!("hepta loopback request failed: {error:#}");
                    }
                });
            }
            joined = connections.join_next(), if !connections.is_empty() => {
                if let Some(Err(error)) = joined {
                    eprintln!("hepta loopback connection task failed: {error}");
                }
            }
        }
    };
    // This gateway is read-only: cancellation closes pending responses, not
    // uncertain domain operations. No accepted task is detached on shutdown.
    drop(listener);
    tokio::time::timeout(RESPONSE_TIMEOUT, connections.shutdown())
        .await
        .context("loopback connection shutdown timed out")?;
    outcome
}
