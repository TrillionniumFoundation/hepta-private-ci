//! One bounded kernel-peer service loop for the live secrets role owners.

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio::time::timeout_at;

use crate::ConsumerPortError;
use crate::local_endpoint::BoundSocket;

const MAX_FRAME_BYTES: usize = 32 * 1024;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LocalServiceConfig {
    pub socket_path: std::path::PathBuf,
    pub ipc_group_gid: u32,
    pub service_uid: u32,
    pub allowed_peer_uids: Vec<u32>,
    pub request_timeout_ms: u64,
    pub shutdown_drain_ms: u64,
}

/// Concrete role owners decode their own bounded request and complete their
/// durable effect before returning a response. Cancellation must fence writes;
/// reads of original operations remain available. This loop never retries work.
pub(crate) trait LocalServiceOwner: Send + Sync + 'static {
    fn handle(
        &self,
        peer_uid: u32,
        request: &[u8],
        original_deadline: Instant,
    ) -> impl Future<Output = Result<Vec<u8>, ConsumerPortError>> + Send;
    fn fence_unknown(&self);
    fn close(&self) -> impl Future<Output = ()> + Send;
}

pub(crate) async fn serve<O: LocalServiceOwner>(
    config: LocalServiceConfig,
    owner: Arc<O>,
    mut endpoint: BoundSocket,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    if config.service_uid != rustix::process::geteuid().as_raw()
        || config.allowed_peer_uids.is_empty()
        || config.allowed_peer_uids.len() > 8
        || config.request_timeout_ms == 0
        || config.request_timeout_ms > 30_000
        || config.shutdown_drain_ms < config.request_timeout_ms
        || config.shutdown_drain_ms > 60_000
    {
        return Err(ConsumerPortError::Invalid);
    }
    let listener = endpoint.listener()?;
    let config = Arc::new(config);
    let permits = Arc::new(Semaphore::new(4));
    let mut tasks = JoinSet::new();
    let mut failure = None;
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            biased;
            _ = &mut shutdown => break,
            result = tasks.join_next(), if !tasks.is_empty() => {
                if result.is_some_and(|result| result.is_err()) { owner.fence_unknown(); }
            }
            accepted = listener.accept() => {
                let (stream, _) = match accepted {
                    Ok(connection) => connection,
                    Err(_) => { failure = Some(ConsumerPortError::Unavailable); break; }
                };
                let Ok(permit) = Arc::clone(&permits).try_acquire_owned() else { drop(stream); continue; };
                let owner = Arc::clone(&owner);
                let config = Arc::clone(&config);
                let original_deadline = Instant::now() + Duration::from_millis(config.request_timeout_ms);
                tasks.spawn(async move {
                    let _permit = permit;
                    serve_connection(stream, &config, &*owner, original_deadline,
                        |stream: &UnixStream| Ok(stream.peer_cred().map_err(unavailable)?.uid()),
                    ).await;
                });
            }
        }
    }
    drop(listener); // No new admission during the drain.
    let drain = async {
        while let Some(result) = tasks.join_next().await {
            if result.is_err() {
                owner.fence_unknown();
            }
        }
        owner.close().await;
    };
    if timeout(Duration::from_millis(config.shutdown_drain_ms), drain)
        .await
        .is_err()
    {
        owner.fence_unknown();
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
        // JoinSet completion proves request futures have stopped before this
        // endpoint is released. A cancelled durable owner remains fenced.
        return Err(ConsumerPortError::Unavailable);
    }
    drop(endpoint);
    failure.map_or(Ok(()), Err)
}

async fn serve_connection<O, S, P>(
    stream: S,
    config: &LocalServiceConfig,
    owner: &O,
    original_deadline: Instant,
    peer: P,
) where
    O: LocalServiceOwner,
    S: AsyncRead + AsyncWrite + Unpin + Send,
    P: Fn(&S) -> Result<u32, ConsumerPortError> + Send,
{
    if Instant::now() >= original_deadline {
        return;
    }
    let _result = timeout_at(
        tokio::time::Instant::from_std(original_deadline),
        exchange(stream, config, owner, original_deadline, peer),
    )
    .await;
}

/// Cancellation is uncertain only while the owner is executing. An incomplete
/// frame has not entered the owner; a lost response cannot undo a finished call.
struct RequestExecutionFence<'a, O: LocalServiceOwner> {
    owner: &'a O,
    armed: bool,
}

impl<O: LocalServiceOwner> Drop for RequestExecutionFence<'_, O> {
    fn drop(&mut self) {
        if self.armed {
            self.owner.fence_unknown();
        }
    }
}

async fn exchange<O, S, P>(
    mut stream: S,
    config: &LocalServiceConfig,
    owner: &O,
    original_deadline: Instant,
    peer: P,
) -> Result<(), ConsumerPortError>
where
    O: LocalServiceOwner,
    S: AsyncRead + AsyncWrite + Unpin + Send,
    P: Fn(&S) -> Result<u32, ConsumerPortError> + Send,
{
    let peer_uid = peer(&stream)?;
    if !config.allowed_peer_uids.contains(&peer_uid) {
        return Err(ConsumerPortError::Rejected);
    }
    let length = stream.read_u32().await.map_err(unavailable)? as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Invalid);
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await.map_err(unavailable)?;
    if peer(&stream)? != peer_uid {
        return Err(ConsumerPortError::Rejected);
    }
    // A ready framing/peer future can finish in the same poll as expiry.
    // Recheck the accept-time budget immediately before owner entry.
    if Instant::now() >= original_deadline {
        return Err(ConsumerPortError::Unavailable);
    }
    let mut execution = RequestExecutionFence { owner, armed: true };
    let result = owner.handle(peer_uid, &body, original_deadline).await;
    execution.armed = false;
    let response = result?;
    if Instant::now() >= original_deadline
        || response.is_empty()
        || response.len() > MAX_FRAME_BYTES
    {
        return Err(ConsumerPortError::Unavailable);
    }
    stream
        .write_u32(response.len() as u32)
        .await
        .map_err(unavailable)?;
    stream.write_all(&response).await.map_err(unavailable)?;
    stream.shutdown().await.map_err(unavailable)
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}

#[cfg(test)]
#[path = "local_service_tests.rs"]
mod tests;
