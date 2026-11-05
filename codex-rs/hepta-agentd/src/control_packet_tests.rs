use super::*;
use std::future::Future;
use std::future::poll_fn;
use std::io::ErrorKind;
use std::task::Poll;
use std::time::Duration;
use std::time::Instant;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::io::duplex;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn coalesced_header_preserves_prefetched_complete_packet() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = vec![b'\n'; 49_508];
    let mut wire = b"{}\n".to_vec();
    wire.extend_from_slice(&body);
    let mut reader = BufReader::new(wire.as_slice());
    assert_eq!(
        crate::control::read_request_frame(&mut reader).await?,
        b"{}\n"
    );
    assert!(!reader.buffer().is_empty());
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    let packet = AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(body.len())?,
        &Sha256Digest::for_bytes(&body),
        permits,
        &execution,
    )
    .await?;
    assert_eq!(packet.wire_payload(), body.as_slice());
    assert_eq!(packet.execution().deadline(), execution.deadline());
    Ok(())
}

#[tokio::test]
async fn fragmented_header_and_body_require_exact_write_side_eof() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = b"fragmented\nraw\0packet";
    let (mut writer, reader) = duplex(/*max_buf_size*/ 7);
    let producer = tokio::spawn(async move {
        for fragment in [b"{".as_slice(), b"}".as_slice(), b"\n".as_slice()]
            .into_iter()
            .chain(body.chunks(3))
        {
            writer.write_all(fragment).await?;
            tokio::task::yield_now().await;
        }
        writer.shutdown().await
    });
    let mut reader = BufReader::new(reader);
    assert_eq!(
        crate::control::read_request_frame(&mut reader).await?,
        b"{}\n"
    );
    let packet = AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(body.len())?,
        &Sha256Digest::for_bytes(body),
        Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY)),
        &execution,
    )
    .await?;
    assert_eq!(packet.wire_payload(), body.as_slice());
    producer.await??;
    Ok(())
}

#[tokio::test]
async fn original_header_bound_and_newline_are_enforced() -> anyhow::Result<()> {
    let mut exact = vec![b' '; usize::try_from(crate::MAX_CONTROL_FRAME_BYTES)?];
    *exact.last_mut().expect("nonempty header") = b'\n';
    assert_eq!(
        crate::control::read_request_frame(&mut BufReader::new(exact.as_slice())).await?,
        exact
    );
    let mut oversized = exact;
    oversized.insert(/*index*/ 0, b' ');
    for wire in [b"".as_slice(), b"{}", oversized.as_slice()] {
        assert!(matches!(
            crate::control::read_request_frame(&mut BufReader::new(wire)).await,
            Err(AgentdError::Protocol(_))
        ));
    }
    Ok(())
}

#[tokio::test]
async fn invalid_lengths_refuse_before_permit_or_input_read() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = b"unread";
    let expected = Sha256Digest::for_bytes(body);
    for length in [
        0,
        u32::try_from(MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES)? + 1,
        u32::MAX,
    ] {
        let mut reader = body.as_slice();
        assert!(matches!(
            AdmittedEffectPacketV1::read(
                &mut reader,
                length,
                &expected,
                Arc::new(Semaphore::new(/*permits*/ 0)),
                &execution,
            )
            .await,
            Err(AgentdError::Invalid(_))
        ));
        assert_eq!(reader, body);
    }
    Ok(())
}

#[tokio::test]
async fn maximum_packet_is_complete_and_digest_bound() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = vec![0x5a; MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES];
    let packet = AdmittedEffectPacketV1::read(
        &mut body.as_slice(),
        u32::try_from(body.len())?,
        &Sha256Digest::for_bytes(&body),
        Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY)),
        &execution,
    )
    .await?;
    assert_eq!(packet.wire_payload(), body.as_slice());
    Ok(())
}

#[tokio::test]
async fn truncated_trailing_and_wrong_digest_packets_release_capacity() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    assert!(matches!(
        AdmittedEffectPacketV1::read(
            &mut b"packe".as_slice(),
            /*wire_len*/ 6,
            &expected,
            Arc::clone(&permits),
            &execution,
        ).await,
        Err(AgentdError::Io(error)) if error.kind() == ErrorKind::UnexpectedEof
    ));
    assert!(matches!(
        AdmittedEffectPacketV1::read(
            &mut b"packet!".as_slice(),
            /*wire_len*/ 6,
            &expected,
            Arc::clone(&permits),
            &execution,
        )
        .await,
        Err(AgentdError::Protocol(_))
    ));
    assert!(matches!(
        AdmittedEffectPacketV1::read(
            &mut b"packeT".as_slice(),
            /*wire_len*/ 6,
            &expected,
            Arc::clone(&permits),
            &execution,
        )
        .await,
        Err(AgentdError::Invalid(_))
    ));
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
    Ok(())
}

#[tokio::test]
async fn capacity_stays_reserved_until_last_execution_owner_finishes() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let permits = Arc::new(Semaphore::new(/*permits*/ 1));
    let packet = AdmittedEffectPacketV1::read(
        &mut body.as_slice(),
        u32::try_from(body.len())?,
        &expected,
        Arc::clone(&permits),
        &execution,
    )
    .await?;
    let retained = packet.retention();
    drop(packet);
    let mut reader = body.as_slice();
    assert!(matches!(
        AdmittedEffectPacketV1::read(
            &mut reader,
            u32::try_from(body.len())?,
            &expected,
            Arc::clone(&permits),
            &execution,
        )
        .await,
        Err(AgentdError::Overloaded { .. })
    ));
    assert_eq!(reader, body);
    drop(retained);
    let packet = AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(body.len())?,
        &expected,
        Arc::clone(&permits),
        &execution,
    )
    .await?;
    assert_eq!(packet.wire_payload(), body);
    drop(packet);
    assert_eq!(permits.available_permits(), 1);
    Ok(())
}

#[tokio::test]
async fn caller_deadline_bounds_stalled_body_and_missing_eof() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    for sent in [0, body.len() - 1, body.len()] {
        let (mut writer, mut reader) = duplex(/*max_buf_size*/ 64);
        writer.write_all(&body[..sent]).await?;
        assert!(
            timeout(
                Duration::from_millis(/*millis*/ 25),
                AdmittedEffectPacketV1::read(
                    &mut reader,
                    u32::try_from(body.len())?,
                    &expected,
                    Arc::clone(&permits),
                    &execution,
                ),
            )
            .await
            .is_err()
        );
        assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
        drop(writer);
    }
    Ok(())
}

#[tokio::test]
async fn cancelled_partial_read_releases_its_reserved_capacity() -> anyhow::Result<()> {
    let execution = NeuralCognitiveExecutionV1::bounded_read();
    let (_writer, mut reader) = duplex(/*max_buf_size*/ 64);
    let expected = Sha256Digest::for_bytes(b"packet");
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    let mut pending = Box::pin(AdmittedEffectPacketV1::read(
        &mut reader,
        /*wire_len*/ 6,
        &expected,
        Arc::clone(&permits),
        &execution,
    ));
    assert!(poll_fn(|context| { Poll::Ready(pending.as_mut().poll(context).is_pending()) }).await);
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY - 1);
    drop(pending);
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
    Ok(())
}

#[tokio::test]
async fn expired_or_cancelled_execution_refuses_before_reading() -> anyhow::Result<()> {
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let expired =
        NeuralCognitiveExecutionV1::with_deadline(Instant::now(), CancellationToken::new());
    let cancelled = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(/*secs*/ 2),
        cancellation,
    );
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    for execution in [expired, cancelled] {
        let mut reader = body.as_slice();
        assert!(matches!(
            AdmittedEffectPacketV1::read(
                &mut reader,
                u32::try_from(body.len())?,
                &expected,
                Arc::clone(&permits),
                &execution,
            )
            .await,
            Err(AgentdError::Protocol(_))
        ));
        assert_eq!(reader, body);
        assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
    }
    Ok(())
}

#[tokio::test]
async fn cancellation_before_eof_refuses_the_complete_packet() -> anyhow::Result<()> {
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let cancellation = CancellationToken::new();
    let execution = NeuralCognitiveExecutionV1::with_deadline(
        Instant::now() + Duration::from_secs(/*secs*/ 2),
        cancellation.clone(),
    );
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    let (mut writer, mut reader) = duplex(/*max_buf_size*/ 64);
    writer.write_all(body).await?;
    let mut pending = Box::pin(AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(body.len())?,
        &expected,
        Arc::clone(&permits),
        &execution,
    ));
    assert!(poll_fn(|context| { Poll::Ready(pending.as_mut().poll(context).is_pending()) }).await);
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY - 1);
    cancellation.cancel();
    writer.shutdown().await?;
    assert!(matches!(pending.await, Err(AgentdError::Protocol(_))));
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
    Ok(())
}

#[tokio::test]
async fn deadline_before_eof_refuses_the_complete_packet() -> anyhow::Result<()> {
    let body = b"packet";
    let expected = Sha256Digest::for_bytes(body);
    let permits = Arc::new(Semaphore::new(PACKET_CONNECTION_CAPACITY));
    let (mut writer, mut reader) = duplex(/*max_buf_size*/ 64);
    writer.write_all(body).await?;
    let deadline = Instant::now() + Duration::from_millis(/*millis*/ 250);
    let execution = NeuralCognitiveExecutionV1::with_deadline(deadline, CancellationToken::new());
    let mut pending = Box::pin(AdmittedEffectPacketV1::read(
        &mut reader,
        u32::try_from(body.len())?,
        &expected,
        Arc::clone(&permits),
        &execution,
    ));
    assert!(poll_fn(|context| { Poll::Ready(pending.as_mut().poll(context).is_pending()) }).await);
    tokio::time::sleep_until(tokio::time::Instant::from_std(deadline)).await;
    writer.shutdown().await?;
    assert!(matches!(pending.await, Err(AgentdError::Protocol(_))));
    assert_eq!(permits.available_permits(), PACKET_CONNECTION_CAPACITY);
    Ok(())
}
