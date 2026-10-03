//! Finite transport for the original Generator composition. Only admission and
//! input reading time out; an admitted effect is drained even after shutdown.
use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::frozen_generator_wire::*;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixListener;
use tokio::net::UnixStream;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use crate::root_frozen_generator::GeneratorPublication;
use crate::root_frozen_generator::RootFrozenGeneratorServiceV1;

#[path = "root_unix_socket.rs"]
mod socket;

pub(crate) async fn serve(host: Arc<RootFrozenGeneratorServiceV1>) -> Result<()> {
    let (listener, _guard) = socket::bind_socket(host.socket(), host.socket_group()).await?;
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    let shutdown = async move {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {},
            _ = terminate.recv() => {},
        }
    };
    accept_connections(
        listener,
        move |stream| connection(stream, host.clone()),
        shutdown,
    )
    .await
}

async fn accept_connections<F, C, S>(
    listener: UnixListener,
    connection: F,
    shutdown: S,
) -> Result<()>
where
    F: Fn(UnixStream) -> C,
    C: Future<Output = Result<()>> + Send + 'static,
    S: Future<Output = ()>,
{
    let capacity = Arc::new(Semaphore::new(16));
    let mut tasks = JoinSet::new();
    tokio::pin!(shutdown);
    let result = loop {
        tokio::select! {
            biased;
            _ = &mut shutdown => break Ok(()),
            _ = tasks.join_next(), if !tasks.is_empty() => {},
            accepted = listener.accept() => {
                let stream = match accepted {
                    Ok((stream, _)) => stream,
                    Err(error) => break Err(error.into()),
                };
                let Ok(permit) = capacity.clone().try_acquire_owned() else { continue; };
                let connection = connection(stream);
                tasks.spawn(async move {
                    let _permit = permit;
                    // Retain this task until dispatch settles. No caller timeout or
                    // shutdown path aborts an original Generator producer.
                    let _ = connection.await;
                });
            }
        }
    };
    drop(listener);
    while tasks.join_next().await.is_some() {}
    result
}

async fn connection(mut stream: UnixStream, host: Arc<RootFrozenGeneratorServiceV1>) -> Result<()> {
    let (peer, request) = tokio::time::timeout(Duration::from_secs(15), async {
        let peer = host.admit(&stream).await?;
        let request = read_request(&mut stream).await?;
        Ok::<_, anyhow::Error>((peer, request))
    })
    .await??;
    let response = match request {
        FrozenGeneratorOperationV1::PrepareRound(request) => encode_round_preparation_response_v1(
            &host.prepare_round(&stream, &peer, request).await,
        ),
        FrozenGeneratorOperationV1::Issue(request) => encode_frozen_generator_response_v1(
            &host
                .dispatch(&stream, &peer, GeneratorPublication::Issue(request))
                .await,
        ),
        FrozenGeneratorOperationV1::Observe(request) => encode_frozen_generator_response_v1(
            &host
                .dispatch(&stream, &peer, GeneratorPublication::Observe(request))
                .await,
        ),
        FrozenGeneratorOperationV1::ObserveModelFailure(request) => {
            encode_self_iteration_model_failure_observation_response_v1(
                &host.observe_model_failure(&stream, &peer, request).await,
            )
        }
        FrozenGeneratorOperationV1::IndependentOwner(request) => {
            let purpose = request.purpose;
            encode_self_iteration_owner_response_v1(
                purpose,
                &host
                    .dispatch_independent_owner(&stream, &peer, request)
                    .await,
            )
        }
    };
    let mut bytes = response.map_err(|error| anyhow::anyhow!("{error}"))?;
    bytes.push(b'\n');
    // Dispatch has already settled; only a stalled response consumer times out.
    // The actual admitted producer is never cancelled by this transport limit.
    write_response(&mut stream, &bytes, Duration::from_secs(15)).await?;
    Ok(())
}

async fn write_response(
    stream: &mut UnixStream,
    bytes: &[u8],
    maximum_wait: Duration,
) -> Result<()> {
    tokio::time::timeout(maximum_wait, async {
        stream.write_all(bytes).await?;
        stream.shutdown().await
    })
    .await
    .context("Root response consumer exceeded its bounded wait")??;
    Ok(())
}

async fn read_request(stream: &mut UnixStream) -> Result<FrozenGeneratorOperationV1> {
    let mut bytes = Vec::new();
    // EOF must use the same reader so a buffered second request cannot disappear.
    let mut reader = BufReader::new(stream).take(MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1 as u64 + 1);
    let count = reader.read_until(b'\n', &mut bytes).await?;
    ensure!(
        count > 0 && count <= MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1 && bytes.last() == Some(&b'\n'),
        "invalid Generator request frame"
    );
    let mut trailing = [0; 1];
    ensure!(
        reader.read(&mut trailing).await? == 0,
        "one Generator request per connection"
    );
    decode_frozen_generator_operation_v1(&bytes).map_err(|error| anyhow::anyhow!("{error}"))
}

#[cfg(test)]
#[path = "root_frozen_generator_server_tests.rs"]
mod tests;
