use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::sync::mpsc;
use tokio::sync::oneshot;

async fn parse_frame(bytes: Vec<u8>) -> Result<FrozenGeneratorOperationV1> {
    let (mut writer, mut reader) = UnixStream::pair()?;
    let write = tokio::spawn(async move {
        writer.write_all(&bytes).await?;
        writer.shutdown().await
    });
    let result = read_request(&mut reader).await;
    drop(reader);
    // Oversized frames close without consuming the remainder of the writer.
    let _ = write.await?;
    result
}

fn frame() -> Result<Vec<u8>> {
    let request = FrozenGeneratorRequestV1::from_payload(b"original frozen candidate")
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let mut bytes =
        encode_frozen_generator_request_v1(&request).map_err(|error| anyhow::anyhow!("{error}"))?;
    bytes.push(b'\n');
    Ok(bytes)
}

#[tokio::test]
async fn settled_response_cannot_pin_a_drained_connection_when_consumer_stops_reading() -> Result<()>
{
    let (mut writer, _nonreading_peer) = UnixStream::pair()?;
    // Transport backpressure fixture, not a model observation or signed fact.
    let bytes = vec![b'x'; MAX_SELF_ITERATION_FAILURE_OBSERVATION_RESPONSE_BYTES_V1];
    let error = write_response(&mut writer, &bytes, Duration::from_millis(50))
        .await
        .expect_err("a nonreading peer must relinquish the bounded connection");
    assert!(error.to_string().contains("bounded wait"));
    Ok(())
}

#[tokio::test]
async fn exact_shared_frame_requires_eof_even_for_buffered_whitespace() -> Result<()> {
    let bytes = frame()?;
    let FrozenGeneratorOperationV1::Issue(request) = parse_frame(bytes.clone()).await? else {
        anyhow::bail!("legacy issuance was reclassified");
    };
    assert_eq!(
        request
            .payload()
            .map_err(|error| anyhow::anyhow!("{error}"))?,
        b"original frozen candidate"
    );
    let observation =
        FrozenGeneratorObservationRequestV2::from_payload(b"original frozen candidate")
            .map_err(|error| anyhow::anyhow!("{error}"))?;
    let mut observation = encode_frozen_generator_observation_request_v2(&observation)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    observation.push(b'\n');
    let FrozenGeneratorOperationV1::Observe(request) = parse_frame(observation).await? else {
        anyhow::bail!("read-only observation was reclassified as issuance");
    };
    assert_eq!(
        request
            .payload()
            .map_err(|error| anyhow::anyhow!("{error}"))?,
        b"original frozen candidate"
    );
    let preparation = RoundPreparationRequestV1::from_round_bytes(b"whole original reserved round")
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let mut preparation = encode_round_preparation_request_v1(&preparation)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    preparation.push(b'\n');
    let FrozenGeneratorOperationV1::PrepareRound(request) = parse_frame(preparation.clone()).await? else {
        anyhow::bail!("preparation was reclassified as another effect purpose");
    };
    assert_eq!(request.round_bytes().map_err(|error| anyhow::anyhow!("{error}"))?, b"whole original reserved round");
    preparation.extend_from_slice(&bytes);
    assert!(parse_frame(preparation).await.is_err());
    let mut second_request = bytes.clone();
    second_request.extend_from_slice(&bytes);
    assert!(parse_frame(second_request).await.is_err());
    let mut whitespace = bytes;
    whitespace.push(b' ');
    assert!(parse_frame(whitespace).await.is_err());
    Ok(())
}

#[tokio::test]
async fn finite_frame_rejects_unterminated_oversized_and_invalid_shared_payload() -> Result<()> {
    let mut bytes = frame()?;
    bytes.pop();
    assert!(parse_frame(bytes).await.is_err());
    let mut oversized = vec![b' '; MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1];
    oversized.push(b'\n');
    assert!(parse_frame(oversized).await.is_err());
    for invalid in [
        b"{\"schema_version\":1,\"frozen_payload_hex\":\"AF\"}\n".as_slice(),
        b"{\"schema_version\":3,\"frozen_payload_hex\":\"aa\"}\n".as_slice(),
        b"{\"schema_version\":1,\"frozen_payload_hex\":\"aa\",\"command\":\"x\"}\n".as_slice(),
    ] {
        assert!(parse_frame(invalid.to_vec()).await.is_err());
    }
    Ok(())
}

#[tokio::test]
async fn shutdown_and_caller_disconnect_drain_started_dispatch_without_replay() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("generator.sock");
    let listener = UnixListener::bind(&path)?;
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let (entered_tx, mut entered_rx) = mpsc::channel(1);
    let release = Arc::new(Semaphore::new(0));
    let dispatches = Arc::new(AtomicUsize::new(0));
    let completions = Arc::new(AtomicUsize::new(0));
    let mut server = tokio::spawn(accept_connections(
        listener,
        {
            let release = release.clone();
            let dispatches = dispatches.clone();
            let completions = completions.clone();
            move |mut stream| {
                let release = release.clone();
                let dispatches = dispatches.clone();
                let completions = completions.clone();
                let entered_tx = entered_tx.clone();
                async move {
                    read_request(&mut stream).await?;
                    dispatches.fetch_add(1, Ordering::SeqCst);
                    entered_tx.send(()).await?;
                    let permit = release.acquire().await?;
                    permit.forget();
                    completions.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                }
            }
        },
        async {
            let _ = shutdown_rx.await;
        },
    ));
    let mut client = UnixStream::connect(&path).await?;
    client.write_all(&frame()?).await?;
    client.shutdown().await?;
    tokio::time::timeout(Duration::from_secs(2), entered_rx.recv())
        .await?
        .ok_or_else(|| anyhow::anyhow!("dispatch never entered"))?;
    drop(client);
    shutdown_tx
        .send(())
        .map_err(|_| anyhow::anyhow!("server stopped before shutdown"))?;
    assert!(
        tokio::time::timeout(Duration::from_millis(50), &mut server)
            .await
            .is_err()
    );
    assert_eq!(dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(completions.load(Ordering::SeqCst), 0);
    release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), server).await???;
    assert_eq!(dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(completions.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn sixteen_active_connections_close_overflow_and_are_all_drained() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("generator.sock");
    let listener = UnixListener::bind(&path)?;
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let (entered_tx, mut entered_rx) = mpsc::channel(16);
    let release = Arc::new(Semaphore::new(0));
    let calls = Arc::new(AtomicUsize::new(0));
    let completions = Arc::new(AtomicUsize::new(0));
    let server = tokio::spawn(accept_connections(
        listener,
        {
            let release = release.clone();
            let calls = calls.clone();
            let completions = completions.clone();
            move |stream| {
                let release = release.clone();
                let calls = calls.clone();
                let completions = completions.clone();
                let entered_tx = entered_tx.clone();
                async move {
                    let _stream = stream;
                    calls.fetch_add(1, Ordering::SeqCst);
                    entered_tx.send(()).await?;
                    let permit = release.acquire().await?;
                    permit.forget();
                    completions.fetch_add(1, Ordering::SeqCst);
                    Ok(())
                }
            }
        },
        async {
            let _ = shutdown_rx.await;
        },
    ));
    let mut clients = Vec::new();
    for _ in 0..16 {
        clients.push(UnixStream::connect(&path).await?);
        tokio::time::timeout(Duration::from_secs(2), entered_rx.recv())
            .await?
            .ok_or_else(|| anyhow::anyhow!("connection not accepted"))?;
    }
    let mut overflow = UnixStream::connect(&path).await?;
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), overflow.read(&mut byte)).await??,
        0
    );
    assert_eq!(calls.load(Ordering::SeqCst), 16);
    shutdown_tx
        .send(())
        .map_err(|_| anyhow::anyhow!("server stopped before shutdown"))?;
    release.add_permits(16);
    tokio::time::timeout(Duration::from_secs(2), server).await???;
    assert_eq!(calls.load(Ordering::SeqCst), 16);
    assert_eq!(completions.load(Ordering::SeqCst), 16);
    drop(clients);
    Ok(())
}
