//! One finite UDS endpoint. Authentication precedes any request read.
use std::sync::Arc;
use std::time::Duration;

use anyhow::ensure;
use codex_hepta_matrixd::chat::native_wire::*;
use codex_hepta_matrixd::chat::wire::MAX_CHAT_FRAME_BYTES;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use super::Result;
use super::RootChatHost;

#[path = "root_unix_socket.rs"]
mod socket;

pub(super) async fn serve(host: Arc<RootChatHost>) -> Result<()> {
    let (listener, _guard) =
        socket::bind_socket(&host.configuration.socket, host.gateway.socket_group()).await?;
    let capacity = Arc::new(Semaphore::new(16));
    let mut tasks = JoinSet::new();
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => break,
            _ = terminate.recv() => break,
            _ = tasks.join_next(), if !tasks.is_empty() => {},
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                if host.peer(&stream).is_err() { continue; }
                let Ok(permit) = capacity.clone().try_acquire_owned() else { continue; };
                let host = host.clone();
                tasks.spawn(async move {
                    let _permit = permit;
                    let _ = tokio::time::timeout(Duration::from_secs(15), connection(stream, host)).await;
                });
            }
        }
    }
    tasks.abort_all();
    while tasks.join_next().await.is_some() {}
    Ok(())
}

async fn connection(mut stream: UnixStream, host: Arc<RootChatHost>) -> Result<()> {
    host.peer(&stream)?;
    let request = read_request(&mut stream).await?;
    let response = host.dispatch(&stream, request).await;
    let mut response = serde_json::to_vec(&response)?;
    ensure!(
        response.len() < MAX_CHAT_FRAME_BYTES,
        "chat response exceeded bound"
    );
    response.push(b'\n');
    stream.write_all(&response).await?;
    stream.shutdown().await?;
    Ok(())
}

async fn read_request(stream: &mut UnixStream) -> Result<NativeChatRootRequest> {
    let mut bytes = Vec::new();
    // Keep the same buffered reader for EOF: bytes after the newline may
    // already be buffered and must not disappear when the reader is dropped.
    let mut reader = BufReader::new(stream).take(MAX_NATIVE_CHAT_REQUEST_BYTES as u64 + 1);
    let count = reader.read_until(b'\n', &mut bytes).await?;
    ensure!(
        count > 0 && count <= MAX_NATIVE_CHAT_REQUEST_BYTES && bytes.last() == Some(&b'\n'),
        "invalid chat request frame"
    );
    let mut trailing = [0; 1];
    ensure!(
        reader.read(&mut trailing).await? == 0,
        "one chat request per connection"
    );
    Ok(serde_json::from_slice(&bytes)?)
}

#[cfg(test)]
#[path = "chat_root_server_tests.rs"]
mod tests;
