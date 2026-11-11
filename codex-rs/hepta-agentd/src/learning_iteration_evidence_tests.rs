//! Mechanism checks use synthetic signatures, never production attestations.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::sync::Arc;

#[path = "learning_iteration_evidence_test_support.rs"]
mod support;
use support::*;

#[path = "learning_iteration_evaluation_evidence_tests.rs"]
mod evaluation;

#[tokio::test]
async fn exact_receipt_readback_supports_recovery_without_sending_a_signing_payload()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let (client, mut server) = fixture.client()?;
    let mut wrong = fixture.initial.clone();
    wrong.request.operation_id = StableId::new("another-operation")?;
    assert!(matches!(
        client.readback(&wrong, &fixture.receipt).await,
        Err(Error::WrongScope)
    ));
    let expected = fixture.signature.clone();
    let evidence = [fixture.evidence(), fixture.evidence()];
    let peer = std::thread::spawn(move || -> anyhow::Result<()> {
        for (index, evidence) in evidence.into_iter().enumerate() {
            let request = read_request(&mut server)?;
            assert_eq!(request.request_id, index as u64 + 1);
            assert_eq!(request.operation, wire::OPERATION);
            assert_eq!(request.receipt_digest, expected.payload_digest.to_string());
            let encoded = serde_json::to_value(&request)?;
            assert!(encoded.get("payload").is_none());
            assert!(encoded.get("signature").is_none());
            reply(&mut server, &response(request, evidence))?;
        }
        Ok(())
    });
    let first = client.readback(&fixture.initial, &fixture.receipt).await?;
    assert_eq!(first, fixture.signature);
    let mut recovered = LearningIterationCoordinatorV1::from_snapshot(fixture.initial)?;
    recovered.record(
        fixture.receipt.clone(),
        fixture.receipt.observed_unix_seconds,
    )?;
    assert_eq!(
        client
            .readback(recovered.snapshot(), &fixture.receipt)
            .await?,
        first
    );
    peer.join().expect("evidence fixture thread")?;
    Ok(())
}

#[tokio::test]
async fn substituted_binding_and_invalid_attestations_permanently_consume_connection()
-> anyhow::Result<()> {
    for scenario in 0..12 {
        let fixture = Fixture::new()?;
        let (client, mut server) = fixture.client()?;
        let evidence = fixture.evidence();
        let peer = std::thread::spawn(move || -> anyhow::Result<()> {
            let request = read_request(&mut server)?;
            let mut value = response(request, evidence);
            match scenario {
                0 => value.request_id += 1,
                1 => value.binding = Digest32::of_bytes(b"other-scope").to_string(),
                2 => value.snapshot_head = Digest32::of_bytes(b"other-head").to_string(),
                3 => value.receipt_digest = Digest32::of_bytes(b"other-result").to_string(),
                4 => value.evidence.principal_id = "unconfigured-owner".into(),
                5 => value.evidence.role = "generator".into(),
                6 => value.evidence.expires_at = value.evidence.issued_at - 1,
                7 => value.evidence.signature.replace_range(0..1, "!"),
                8 => value.evidence.trust_digest = Digest32::of_bytes(b"other-trust").to_string(),
                9 => value.operation = "runtime.learning.checkpoint.v1".into(),
                10 => value.evidence.signature = "A".repeat(86),
                11 => {
                    value.evidence.payload_digest = Digest32::of_bytes(b"other-payload").to_string()
                }
                _ => unreachable!(),
            }
            reply(&mut server, &value)?;
            let mut remaining = [0];
            assert_eq!(server.read(&mut remaining)?, 0);
            Ok(())
        });
        assert!(
            client
                .readback(&fixture.initial, &fixture.receipt)
                .await
                .is_err()
        );
        assert!(matches!(
            client.readback(&fixture.initial, &fixture.receipt).await,
            Err(Error::OwnerUnavailable(_))
        ));
        peer.join().expect("evidence fixture thread")?;
    }
    Ok(())
}

#[tokio::test]
async fn cancelling_an_inflight_read_drops_the_original_lane_without_reconnect()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let (client, mut server) = fixture.client()?;
    let client = Arc::new(client);
    let (requested, waiting) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let evidence = fixture.evidence();
    let peer = std::thread::spawn(move || -> anyhow::Result<()> {
        let request = read_request(&mut server)?;
        requested.send(()).expect("reader waits");
        released.recv()?;
        assert!(reply(&mut server, &response(request, evidence)).is_err());
        Ok(())
    });
    let reader = Arc::clone(&client);
    let initial = fixture.initial.clone();
    let receipt = fixture.receipt.clone();
    let first = tokio::spawn(async move { reader.readback(&initial, &receipt).await });
    waiting.await?;
    first.abort();
    assert!(first.await.expect_err("read was cancelled").is_cancelled());
    assert!(matches!(
        client.readback(&fixture.initial, &fixture.receipt).await,
        Err(Error::OwnerUnavailable(_))
    ));
    release.send(())?;
    peer.join().expect("evidence fixture thread")?;
    Ok(())
}

#[tokio::test]
async fn public_constructor_refuses_the_daemons_own_uid_before_any_request() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let (stream, mut server) = UnixStream::pair()?;
    let original = identity(std::process::id())?;
    let peer = LearningIterationEvidencePeerV1 {
        pid: original.pid,
        // SAFETY: read the current fixture process's UID only.
        uid: unsafe { libc::geteuid() },
        boot_id: original.boot_id,
        process_start_ticks: original.process_start_ticks,
        actor_id: fixture.receipt.actor_id,
    };
    assert!(matches!(
        LearningIterationEvidenceClientV1::from_owner_stream(
            stream,
            peer,
            pidfd(std::process::id())?,
            fixture.initial,
            fixture.verifier,
            Duration::from_millis(500),
            Duration::from_secs(5),
        ),
        Err(Error::WrongScope)
    ));
    assert_eq!(server.read(&mut [0])?, 0);
    Ok(())
}

#[path = "learning_iteration_evidence_root_tests.rs"]
mod root;

#[path = "learning_iteration_generation_evidence_tests.rs"]
mod generation;

/// Same-UID, synthetic evidence transport for original receipt-owner mechanism
/// tests. The public constructor still refuses this custody configuration.
pub(crate) fn fixture_original_receipt_client(
    initial: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    verifier: LearningEvidenceVerifierV1,
    signature: SignedLearningEvidenceV1,
    expected_reads: usize,
) -> anyhow::Result<(
    LearningIterationEvidenceClientV1,
    std::thread::JoinHandle<anyhow::Result<()>>,
)> {
    let fixture = Fixture {
        initial,
        receipt,
        verifier,
        signature,
    };
    let (client, mut channel) = fixture.original_owner_client()?;
    let expected = fixture.signature.payload_digest.to_string();
    let evidence: Vec<_> = (0..expected_reads).map(|_| fixture.evidence()).collect();
    let peer = std::thread::spawn(move || -> anyhow::Result<()> {
        for (index, evidence) in evidence.into_iter().enumerate() {
            // The original channel fixes one lifetime at construction, waits
            // for the first byte only until that end, then shares one 500ms
            // deadline across the whole request, handler and response.
            let exchanged = channel.exchange(|bytes| {
                let request: wire::Request = serde_json::from_slice(bytes)
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::InvalidRequest)?;
                assert_eq!(request.request_id, index as u64 + 1);
                assert_eq!(request.operation, wire::OPERATION);
                assert_eq!(request.receipt_digest, expected);
                let encoded = serde_json::to_value(&request)
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::InvalidRequest)?;
                assert!(encoded.get("payload").is_none());
                assert!(encoded.get("signature").is_none());
                serde_json::to_vec(&response(request, evidence))
                    .map_err(|_| codex_hepta_contracts::HostIssuerTransportError::Unavailable)
            })?;
            anyhow::ensure!(
                exchanged,
                "original receipt fixture closed before request {index}"
            );
        }
        Ok(())
    });
    Ok((client, peer))
}

#[tokio::test]
async fn original_receipt_fixture_retains_peer_during_owner_work_between_frames()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let (client, peer) = fixture_original_receipt_client(
        fixture.initial.clone(),
        fixture.receipt.clone(),
        fixture.verifier.clone(),
        fixture.signature.clone(),
        2,
    )?;
    assert_eq!(
        client.readback(&fixture.initial, &fixture.receipt).await?,
        fixture.signature
    );
    // No frame is in flight while the original owner reads its CURRENTs.
    // This crosses both former fixture limits (2-second idle, 5-second life)
    // without changing the real client's 500-millisecond frame deadline.
    tokio::time::sleep(Duration::from_millis(5_100)).await;
    assert_eq!(
        client.readback(&fixture.initial, &fixture.receipt).await?,
        fixture.signature
    );
    drop(client);
    peer.join().expect("original receipt peer")?;
    Ok(())
}
