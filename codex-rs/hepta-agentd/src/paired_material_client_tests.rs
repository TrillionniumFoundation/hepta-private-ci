//! Socket/cancellation/complete-decoding component controls. The test-local
//! peer is not a production Root; no original human or writer receipt is made.
use super::*;
use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

const FAILURE: &[u8] = b"synthetic failure";
const CORRECTION: &[u8] = b"synthetic correction";

fn local_peer() -> (Arc<AgentdPairedMaterialClient>, tokio::net::UnixStream) {
    let manifest = crate::PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(FAILURE),
        failure_bytes: FAILURE.len() as u64,
        correction_sha256: Digest32::of_bytes(CORRECTION),
        correction_bytes: CORRECTION.len() as u64,
    };
    let registration = PairedPreparationRegistration {
        study: Digest32::of_bytes(b"synthetic study"),
        enrollment: Digest32::of_bytes(b"synthetic enrollment"),
        frozen_materials: manifest.commitment().unwrap(),
        principal_id: "synthetic-person".into(),
        policy_generation: Generation::new(1).unwrap(),
    };
    let (client, peer) = UnixStream::pair().unwrap();
    // SAFETY: opens only this process; the successful pidfd is uniquely owned.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(fd >= 0, "{}", std::io::Error::last_os_error());
    let original = unsafe { OwnedFd::from_raw_fd(fd as i32) };
    let shutdown = client.try_clone().unwrap();
    let channel = HostAuthorityPeerChannel::from_stream(
        client,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(1),
            lifetime: Duration::from_secs(3),
            request_bound: FRAME_BOUND,
            response_bound: FRAME_BOUND,
        },
        original,
    )
    .unwrap();
    peer.set_nonblocking(true).unwrap();
    (
        Arc::new(AgentdPairedMaterialClient {
            registration,
            manifest,
            channel: Mutex::new(Some(channel)),
            shutdown,
        }),
        tokio::net::UnixStream::from_std(peer).unwrap(),
    )
}

async fn request(peer: &mut tokio::net::UnixStream) -> Vec<u8> {
    let length = peer.read_u32().await.unwrap() as usize;
    assert!(length <= FRAME_BOUND);
    let mut raw = vec![0; length];
    peer.read_exact(&mut raw).await.unwrap();
    raw
}

#[tokio::test]
async fn paired_material_cancel_closes_only_the_consumed_original_socket() {
    let (client, mut peer) = local_peer();
    let delivery = Digest32::of_bytes(b"synthetic delivery");
    let (started_tx, started_rx) = oneshot::channel();
    let mut peers = tokio::task::JoinSet::new();
    peers.spawn(async move {
        assert_eq!(
            request(&mut peer).await,
            b"synthetic transport-only request"
        );
        started_tx.send(()).unwrap();
        let mut suffix = Vec::new();
        peer.read_to_end(&mut suffix).await.unwrap();
        suffix
    });
    let original = Arc::clone(&client);
    let running = tokio::spawn(async move {
        original
            .exchange_original(b"synthetic transport-only request".to_vec(), delivery)
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), started_rx)
        .await
        .unwrap()
        .unwrap();
    running.abort();
    assert!(
        running
            .await
            .err()
            .expect("original caller must be cancelled")
            .is_cancelled()
    );
    let suffix = tokio::time::timeout(Duration::from_secs(2), peers.join_next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(suffix.is_empty());
    assert!(client.channel.lock().unwrap().is_none());
    assert!(
        client
            .exchange_original(b"retry forbidden".to_vec(), delivery)
            .await
            .is_err()
    );
    assert!(peers.is_empty());
}

#[tokio::test]
async fn paired_material_complete_commitment_is_checked_before_bytes_escape() {
    for valid in [false, true] {
        let (client, mut peer) = local_peer();
        let delivery = Digest32::of_bytes(b"synthetic delivery");
        let raw = serde_json::to_vec(&PairedTrainingReadResponse::FreshRead {
            original_delivery: delivery.to_string(),
            materials_sha256: client.registration.frozen_materials.to_string(),
            failure_base64: base64::engine::general_purpose::STANDARD.encode(if valid {
                FAILURE
            } else {
                b"wrong-content"
            }),
            correction_base64: base64::engine::general_purpose::STANDARD.encode(CORRECTION),
        })
        .unwrap();
        let mut peers = tokio::task::JoinSet::new();
        peers.spawn(async move {
            assert_eq!(
                request(&mut peer).await,
                b"synthetic transport-only request"
            );
            peer.write_u32(raw.len() as u32).await.unwrap();
            peer.write_all(&raw).await.unwrap();
        });
        let result = client
            .exchange_original(b"synthetic transport-only request".to_vec(), delivery)
            .await;
        if valid {
            let PairedTrainingReadResult::FreshRead(material) = result.unwrap() else {
                panic!("complete original frame expected");
            };
            assert_eq!(material.failure(), FAILURE);
            assert_eq!(material.correction(), CORRECTION);
        } else {
            assert!(result.is_err());
        }
        assert!(client.channel.lock().unwrap().is_none());
        assert!(
            client
                .exchange_original(b"retry forbidden".to_vec(), delivery)
                .await
                .is_err()
        );
        tokio::time::timeout(Duration::from_secs(2), peers.join_next())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
    }
}

#[tokio::test]
async fn paired_material_partial_response_stays_unknown_and_cannot_reconnect() {
    let (client, mut peer) = local_peer();
    let delivery = Digest32::of_bytes(b"synthetic delivery");
    let mut peers = tokio::task::JoinSet::new();
    peers.spawn(async move {
        assert_eq!(
            request(&mut peer).await,
            b"synthetic transport-only request"
        );
        peer.write_u32(30).await.unwrap();
        peer.write_all(b"partial").await.unwrap();
    });
    assert!(
        client
            .exchange_original(b"synthetic transport-only request".to_vec(), delivery)
            .await
            .is_err()
    );
    assert!(client.channel.lock().unwrap().is_none());
    assert!(
        client
            .exchange_original(b"retry forbidden".to_vec(), delivery)
            .await
            .is_err()
    );
    tokio::time::timeout(Duration::from_secs(2), peers.join_next())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
}
