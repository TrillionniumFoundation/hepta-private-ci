//! One bounded kernel-peer service loop for the live secrets role owners.

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::timeout;

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
        || config.request_timeout_ms > 5_000
        || config.shutdown_drain_ms < config.request_timeout_ms
        || config.shutdown_drain_ms > 10_000
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
                tasks.spawn(async move {
                    let _permit = permit;
                    if timeout(Duration::from_millis(config.request_timeout_ms), exchange(
                        stream, &config, &*owner,
                    )).await.is_err() { owner.fence_unknown(); }
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
        return Err(ConsumerPortError::Unavailable);
    }
    drop(endpoint);
    failure.map_or(Ok(()), Err)
}

async fn exchange<O: LocalServiceOwner>(
    mut stream: UnixStream,
    config: &LocalServiceConfig,
    owner: &O,
) -> Result<(), ConsumerPortError> {
    let peer_uid = stream.peer_cred().map_err(unavailable)?.uid();
    if !config.allowed_peer_uids.contains(&peer_uid) {
        return Err(ConsumerPortError::Rejected);
    }
    let length = stream.read_u32().await.map_err(unavailable)? as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Invalid);
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await.map_err(unavailable)?;
    if stream.peer_cred().map_err(unavailable)?.uid() != peer_uid {
        return Err(ConsumerPortError::Rejected);
    }
    let response = owner.handle(peer_uid, &body).await?;
    if response.is_empty() || response.len() > MAX_FRAME_BYTES {
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
