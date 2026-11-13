use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_exec_server_protocol::JSONRPCMessage;
use codex_exec_server_protocol::JSONRPCResponse;
use codex_exec_server_protocol::RequestId;
use futures::FutureExt;
use futures::SinkExt;
use futures::StreamExt;
use pretty_assertions::assert_eq;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_tungstenite::MaybeTlsStream;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::accept_async;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use tokio_util::task::AbortOnDropHandle;

use super::HarnessKeyValidator;
use super::MAX_FAILED_NOISE_HANDSHAKES;
use super::MAX_HARNESS_KEY_AUTHORIZATION_BYTES;
use super::RendezvousDisconnectReason;
use super::run_multiplexed_environment;
use crate::ExecServerError;
use crate::ExecServerRuntimePaths;
use crate::connection::JsonRpcConnectionEvent;
use crate::noise_channel::InitiatorHandshake;
use crate::noise_channel::NoiseChannelIdentity;
use crate::noise_channel::NoiseChannelPublicKey;
use crate::noise_channel::noise_channel_prologue;
use crate::noise_relay::NoiseHarnessConnectionArgs;
use crate::noise_relay::noise_harness_connection_from_websocket;
use crate::relay::RelayFrameBodyKind;
use crate::relay::decode_relay_message_frame;
use crate::relay::encode_relay_message_frame;
use crate::relay_proto::RelayMessageFrame;
use crate::server::ConnectionProcessor;

const ENVIRONMENT_ID: &str = "environment-1";
const EXECUTOR_REGISTRATION_ID: &str = "registration-1";

#[tokio::test]
async fn missing_pong_disconnects_physical_relay() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (_harness_websocket, _response) = harness_connection.await??;

    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        NoiseChannelIdentity::generate()?,
        BlockingValidator {
            calls: Arc::new(AtomicUsize::new(0)),
            release: Arc::new(Notify::new()),
        },
    ));

    assert_eq!(
        timeout(Duration::from_secs(1), environment_task).await??,
        RendezvousDisconnectReason::PongTimeout
    );
    Ok(())
}

#[tokio::test]
async fn pong_keeps_physical_relay_connected() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        NoiseChannelIdentity::generate()?,
        BlockingValidator {
            calls: Arc::new(AtomicUsize::new(0)),
            release: Arc::new(Notify::new()),
        },
    ));

    timeout(Duration::from_secs(1), async {
        let mut pings = 0;
        while pings < 6 {
            match harness_websocket.next().await {
                Some(Ok(Message::Ping(payload))) => {
                    harness_websocket.send(Message::Pong(payload)).await?;
                    pings += 1;
                }
                Some(Ok(Message::Pong(_) | Message::Frame(_))) => {}
                Some(Ok(message)) => anyhow::bail!("expected keepalive ping, got {message:?}"),
                Some(Err(error)) => return Err(error.into()),
                None => anyhow::bail!("environment disconnected before six keepalive pings"),
            }
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    harness_websocket.close(None).await?;
    assert_eq!(
        timeout(Duration::from_secs(1), environment_task).await??,
        RendezvousDisconnectReason::PeerClose
    );
    Ok(())
}

#[derive(Clone)]
struct BlockingValidator {
    calls: Arc<AtomicUsize>,
    release: Arc<Notify>,
}

impl HarnessKeyValidator for BlockingValidator {
    fn validate_harness_key(
        &self,
        _harness_public_key: &NoiseChannelPublicKey,
        _authorization: &str,
    ) -> impl std::future::Future<Output = Result<(), ExecServerError>> + Send {
        let calls = Arc::clone(&self.calls);
        let release = Arc::clone(&self.release);
        async move {
            calls.fetch_add(1, Ordering::SeqCst);
            release.notified().await;
            Ok(())
        }
    }
}

#[tokio::test]
async fn processor_exit_resets_noise_harness_stream() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let connecting = tokio::spawn(connect_async(format!("ws://{}", listener.local_addr()?)));
    let (socket, _) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (harness_websocket, _) = connecting.await??;
    let identity = NoiseChannelIdentity::generate()?;
    let release = Arc::new(Notify::new());
    release.notify_one();
    let environment_task = AbortOnDropHandle::new(tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        identity.clone(),
        BlockingValidator {
            calls: Arc::new(AtomicUsize::new(0)),
            release,
        },
    )));
    let mut connection = noise_harness_connection_from_websocket(
        harness_websocket,
        NoiseHarnessConnectionArgs {
            connection_label: "processor exit test".to_string(),
            environment_id: ENVIRONMENT_ID.to_string(),
            executor_registration_id: EXECUTOR_REGISTRATION_ID.to_string(),
            identity: NoiseChannelIdentity::generate()?,
            responder_public_key: identity.public_key(),
            harness_key_authorization: "authorization".to_string(),
        },
    );
    // Valid JSON reaches the processor; an unsolicited response closes it and
    // aborts its writer. The physical relay must still deliver the reset.
    connection
        .outgoing_tx
        .send(JSONRPCMessage::Response(JSONRPCResponse {
            id: RequestId::Integer(1),
            result: serde_json::Value::Null,
        }))
        .await?;
    assert!(matches!(
        timeout(Duration::from_secs(1), connection.incoming_rx.recv()).await?,
        Some(JsonRpcConnectionEvent::Disconnected { reason: Some(reason) })
            if reason == "Noise relay stream reset"
    ));
    for task in connection.task_handles {
        task.abort();
        let _ = task.await;
    }
    environment_task.abort();
    let _ = environment_task.await;
    Ok(())
}

#[tokio::test]
async fn pending_harness_key_validation_does_not_block_new_handshakes() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_identity = NoiseChannelIdentity::generate()?;
    let harness_identity = NoiseChannelIdentity::generate()?;
    let calls = Arc::new(AtomicUsize::new(0));
    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        environment_identity.clone(),
        BlockingValidator {
            calls: Arc::clone(&calls),
            release: Arc::new(Notify::new()),
        },
    ));

    for stream_id in ["stream-1", "stream-2"] {
        let prologue = noise_channel_prologue(ENVIRONMENT_ID, EXECUTOR_REGISTRATION_ID, stream_id);
        let (_handshake, request) = InitiatorHandshake::start(
            &harness_identity,
            &environment_identity.public_key(),
            &prologue,
            b"authorization",
        )?;
        let frame = RelayMessageFrame::handshake(stream_id.to_string(), request);
        harness_websocket
            .send(Message::Binary(encode_relay_message_frame(&frame).into()))
            .await?;
    }

    timeout(Duration::from_secs(1), async {
        while calls.load(Ordering::SeqCst) != 2 {
            tokio::task::yield_now().await;
        }
    })
    .await?;

    harness_websocket.close(None).await?;
    timeout(Duration::from_secs(1), environment_task).await??;
    Ok(())
}

async fn wait_for_validation_calls(
    harness_websocket: &mut WebSocketStream<MaybeTlsStream<TcpStream>>,
    calls: &AtomicUsize,
    expected: usize,
    prefetched_reset: &mut Option<Message>,
) -> Result<()> {
    timeout(Duration::from_secs(1), async {
        while calls.load(Ordering::SeqCst) != expected {
            // Keep serving the peer's unchanged Ping/Pong deadline while the
            // validator is pending. Counter polling alone never reads a Ping.
            tokio::select! {
                _ = tokio::task::yield_now() => {}
                message = harness_websocket.next() => match message {
                    Some(Ok(Message::Ping(_))) => harness_websocket.flush().await?,
                    Some(Ok(Message::Pong(_) | Message::Frame(_))) => {}
                    Some(Ok(message @ Message::Binary(_))) => {
                        if prefetched_reset.is_some() {
                            anyhow::bail!("more than one frame arrived during validation {expected}");
                        }
                        *prefetched_reset = Some(message);
                    }
                    Some(Ok(message)) => anyhow::bail!(
                        "unexpected frame while waiting for validation {expected}: {message:?}"
                    ),
                    Some(Err(error)) => return Err(error.into()),
                    None => anyhow::bail!(
                        "environment closed before validation {expected} started"
                    ),
                }
            }
        }
        Ok::<_, anyhow::Error>(())
    })
    .await
    .with_context(|| {
        format!(
            "validation {expected} did not start within 1s; observed {} calls",
            calls.load(Ordering::SeqCst)
        )
    })?
    .with_context(|| format!("serve keepalive while waiting for validation {expected}"))?;
    Ok(())
}

#[tokio::test]
async fn duplicate_handshakes_exhaust_failure_budget() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_identity = NoiseChannelIdentity::generate()?;
    let harness_identity = NoiseChannelIdentity::generate()?;
    let calls = Arc::new(AtomicUsize::new(0));
    let release = Arc::new(Notify::new());
    let mut environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        environment_identity.clone(),
        BlockingValidator {
            calls: Arc::clone(&calls),
            release: Arc::clone(&release),
        },
    ));

    let mut environment_joined = false;
    let outcome = std::panic::AssertUnwindSafe(async {
        let mut prefetched_reset = None;
        let stream_id = "stream-1";
        let prologue = noise_channel_prologue(ENVIRONMENT_ID, EXECUTOR_REGISTRATION_ID, stream_id);
        let (_handshake, request) = InitiatorHandshake::start(
            &harness_identity,
            &environment_identity.public_key(),
            &prologue,
            b"authorization",
        )?;
        let frame = RelayMessageFrame::handshake(stream_id.to_string(), request);
        let encoded = encode_relay_message_frame(&frame);
        harness_websocket
            .send(Message::Binary(encoded.clone().into()))
            .await
            .context("send initial handshake before validation starts")?;
        wait_for_validation_calls(&mut harness_websocket, &calls, 1, &mut prefetched_reset).await?;

        for attempt in 1..MAX_FAILED_NOISE_HANDSHAKES {
            if attempt > 1 {
                harness_websocket
                    .send(Message::Binary(encoded.clone().into()))
                    .await
                    .with_context(|| format!("send handshake for validation attempt {attempt}"))?;
                wait_for_validation_calls(
                    &mut harness_websocket,
                    &calls,
                    attempt,
                    &mut prefetched_reset,
                )
                .await?;
            }
            harness_websocket
                .send(Message::Binary(encoded.clone().into()))
                .await
                .with_context(|| format!("send duplicate for failure {attempt}"))?;
            let payload = timeout(Duration::from_secs(1), async {
                loop {
                    let message = match prefetched_reset.take() {
                        Some(message) => Some(Ok(message)),
                        None => harness_websocket.next().await,
                    };
                    match message {
                        Some(Ok(Message::Binary(payload))) => break Ok(payload),
                        Some(Ok(Message::Ping(_) | Message::Pong(_) | Message::Frame(_))) => {}
                        Some(Ok(message)) => anyhow::bail!("expected reset frame, got {message:?}"),
                        Some(Err(error)) => break Err(error.into()),
                        None => anyhow::bail!("environment closed before sending reset"),
                    }
                }
            })
            .await
            .with_context(|| format!("wait for reset after duplicate {attempt}"))?
            .with_context(|| format!("read reset after duplicate {attempt}"))?;
            let reset = decode_relay_message_frame(payload.as_ref())
                .with_context(|| format!("decode reset after duplicate {attempt}"))?;
            assert_eq!(reset.stream_id, stream_id);
            assert_eq!(reset.validate()?, RelayFrameBodyKind::Reset);
        }

        harness_websocket
            .send(Message::Binary(encoded.clone().into()))
            .await
            .context("send final handshake before failure-budget exhaustion")?;
        wait_for_validation_calls(
            &mut harness_websocket,
            &calls,
            MAX_FAILED_NOISE_HANDSHAKES,
            &mut prefetched_reset,
        )
        .await?;
        harness_websocket
            .send(Message::Binary(encoded.into()))
            .await
            .context("send final duplicate to exhaust the failure budget")?;
        let completion = timeout(Duration::from_secs(1), &mut environment_task)
            .await
            .context("failure-budget exhaustion should stop the environment within 1s")?;
        environment_joined = true;
        let reason = completion.context("environment task failed after budget exhaustion")?;
        eprintln!("failure-budget environment disconnect reason: {reason:?}");
        Ok::<_, anyhow::Error>(())
    })
    .catch_unwind()
    .await;

    release.notify_waiters();
    let cleanup = if environment_joined {
        Ok(())
    } else {
        environment_task.abort();
        match timeout(Duration::from_secs(1), &mut environment_task).await {
            Ok(Ok(reason)) => {
                eprintln!("failed fixture environment disconnect reason: {reason:?}");
                Ok(())
            }
            Ok(Err(error)) if error.is_cancelled() => Ok(()),
            Ok(Err(error)) => Err(anyhow::Error::from(error).context("join environment cleanup")),
            Err(error) => {
                Err(anyhow::Error::from(error).context("environment cleanup exceeded 1s"))
            }
        }
    };
    match outcome {
        Ok(Ok(())) => cleanup,
        Ok(Err(error)) => {
            if let Err(cleanup_error) = cleanup {
                return Err(error.context(format!("fixture cleanup failed: {cleanup_error:#}")));
            }
            Err(error)
        }
        Err(panic) => {
            if let Err(error) = cleanup {
                eprintln!("fixture cleanup failed after panic: {error:#}");
            }
            std::panic::resume_unwind(panic)
        }
    }
}

#[tokio::test]
async fn oversized_harness_authorization_is_rejected_before_validation() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_identity = NoiseChannelIdentity::generate()?;
    let harness_identity = NoiseChannelIdentity::generate()?;
    let calls = Arc::new(AtomicUsize::new(0));
    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        environment_identity.clone(),
        BlockingValidator {
            calls: Arc::clone(&calls),
            release: Arc::new(Notify::new()),
        },
    ));

    let stream_id = "stream-1";
    let prologue = noise_channel_prologue(ENVIRONMENT_ID, EXECUTOR_REGISTRATION_ID, stream_id);
    let oversized_authorization = vec![b'a'; MAX_HARNESS_KEY_AUTHORIZATION_BYTES + 1];
    let (_handshake, request) = InitiatorHandshake::start(
        &harness_identity,
        &environment_identity.public_key(),
        &prologue,
        &oversized_authorization,
    )?;
    let frame = RelayMessageFrame::handshake(stream_id.to_string(), request);
    harness_websocket
        .send(Message::Binary(encode_relay_message_frame(&frame).into()))
        .await?;

    let Message::Binary(payload) = timeout(Duration::from_secs(1), harness_websocket.next())
        .await?
        .ok_or_else(|| anyhow::anyhow!("environment closed before sending reset"))??
    else {
        anyhow::bail!("expected binary reset frame");
    };
    let reset = decode_relay_message_frame(payload.as_ref())?;
    assert_eq!(reset.validate()?, RelayFrameBodyKind::Reset);
    assert_eq!(calls.load(Ordering::SeqCst), 0);

    harness_websocket.close(None).await?;
    timeout(Duration::from_secs(1), environment_task).await??;
    Ok(())
}

#[tokio::test]
async fn repeated_malformed_handshakes_close_the_physical_relay() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_identity = NoiseChannelIdentity::generate()?;
    let harness_identity = NoiseChannelIdentity::generate()?;
    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        environment_identity.clone(),
        BlockingValidator {
            calls: Arc::new(AtomicUsize::new(0)),
            release: Arc::new(Notify::new()),
        },
    ));

    for attempt in 0..MAX_FAILED_NOISE_HANDSHAKES {
        let stream_id = format!("malformed-{attempt}");
        let prologue = noise_channel_prologue(ENVIRONMENT_ID, EXECUTOR_REGISTRATION_ID, &stream_id);
        let (_handshake, mut request) = InitiatorHandshake::start(
            &harness_identity,
            &environment_identity.public_key(),
            &prologue,
            b"authorization",
        )?;
        let last_byte = request.last_mut().expect("handshake request is not empty");
        *last_byte ^= 1;
        let frame = RelayMessageFrame::handshake(stream_id, request);
        harness_websocket
            .send(Message::Binary(encode_relay_message_frame(&frame).into()))
            .await?;
    }

    timeout(Duration::from_secs(1), environment_task).await??;
    Ok(())
}

#[tokio::test]
async fn repeated_early_data_during_validation_closes_the_physical_relay() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let websocket_url = format!("ws://{}", listener.local_addr()?);
    let harness_connection = tokio::spawn(connect_async(websocket_url));
    let (socket, _peer_addr) = listener.accept().await?;
    let environment_websocket = accept_async(socket).await?;
    let (mut harness_websocket, _response) = harness_connection.await??;

    let environment_identity = NoiseChannelIdentity::generate()?;
    let harness_identity = NoiseChannelIdentity::generate()?;
    let environment_task = tokio::spawn(run_multiplexed_environment(
        environment_websocket,
        ConnectionProcessor::new(ExecServerRuntimePaths::new(
            std::env::current_exe()?,
            /*codex_linux_sandbox_exe*/ None,
        )?),
        ENVIRONMENT_ID.to_string(),
        EXECUTOR_REGISTRATION_ID.to_string(),
        environment_identity.clone(),
        BlockingValidator {
            calls: Arc::new(AtomicUsize::new(0)),
            release: Arc::new(Notify::new()),
        },
    ));

    for attempt in 0..MAX_FAILED_NOISE_HANDSHAKES {
        let stream_id = format!("early-data-{attempt}");
        let prologue = noise_channel_prologue(ENVIRONMENT_ID, EXECUTOR_REGISTRATION_ID, &stream_id);
        let (_handshake, request) = InitiatorHandshake::start(
            &harness_identity,
            &environment_identity.public_key(),
            &prologue,
            b"authorization",
        )?;
        for frame in [
            RelayMessageFrame::handshake(stream_id.clone(), request),
            RelayMessageFrame::data(stream_id, /*seq*/ 0, vec![0], /*trace*/ None),
        ] {
            harness_websocket
                .send(Message::Binary(encode_relay_message_frame(&frame).into()))
                .await?;
        }
    }

    timeout(Duration::from_secs(1), environment_task).await??;
    Ok(())
}
