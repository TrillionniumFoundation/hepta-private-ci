use std::io::Read as _;
use std::io::Write as _;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::thread;

use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::*;

const SPLIT: &str = "split-1";
const SCOPE: &str = "scope-1";
const OBSERVER: &str = "independent-control-observer";

fn test_signer() -> SigningKey {
    SigningKey::from_bytes(&[81; 32])
}

fn socket(dir: &Path) -> (PathBuf, UnixListener) {
    let path = dir.join("external-control-observer.sock");
    let server = UnixListener::bind(&path).expect("external test service");
    (path, server)
}

fn read_request(peer: &mut UnixStream) -> CellSplitControlHighwaterRpcRequestV1 {
    let mut size = [0_u8; 4];
    peer.read_exact(&mut size).expect("read request frame size");
    let len = u32::from_be_bytes(size) as usize;
    assert!((1..=MAX_FRAME_BYTES).contains(&len));
    let mut body = vec![0_u8; len];
    peer.read_exact(&mut body).expect("read request bytes");
    let raw: serde_json::Value = serde_json::from_slice(&body).expect("valid JSON");
    assert_eq!(
        raw.as_object().map(serde_json::Map::len),
        Some(5),
        "the client must not pass WAL bytes, checkpoints or claimed high-water"
    );
    for forbidden in [
        "walHead",
        "walBytes",
        "checkpointDigest",
        "generation",
        "sequence",
        "nduSnapshotDigest",
        "originalCnsReceiptBinding",
    ] {
        assert!(raw.get(forbidden).is_none(), "untrusted echo input {forbidden}");
    }
    let request: CellSplitControlHighwaterRpcRequestV1 =
        serde_json::from_value(raw).expect("strict read-only wire schema");
    assert_eq!(request.schema, CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1);
    assert_eq!(request.method, READ_METHOD);
    assert_eq!(request.split_id, SPLIT);
    assert_eq!(request.scope_id, SCOPE);
    request
}

fn send_response(peer: &mut UnixStream, response: &CellSplitControlHighwaterRpcResponseV1) {
    let bytes = serde_json::to_vec(response).expect("response serialization");
    assert!(bytes.len() <= MAX_FRAME_BYTES);
    peer.write_all(&(bytes.len() as u32).to_be_bytes())
        .expect("send bounded response header");
    peer.write_all(&bytes).expect("send bounded response");
}

fn signed_proof(
    req: &CellSplitControlHighwaterRpcRequestV1,
    signer: &SigningKey,
    sequence: u64,
) -> CellSplitSignedControlHighwaterV1 {
    let mut proof = CellSplitSignedControlHighwaterV1 {
        schema: CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1.to_owned(),
        observer_id: OBSERVER.to_owned(),
        plan_digest: "aa".repeat(32),
        split_id: req.split_id.clone(),
        scope_id: req.scope_id.clone(),
        ndu_owner_id: "original-control-owner".into(),
        ndu_snapshot_digest: "bb".repeat(32),
        generation: 3,
        route_fence: 7,
        revocation_epoch: 9,
        sequence,
        wal_head: format!("{sequence:064x}"),
        checkpoint_digest: "cc".repeat(32),
        wal_bytes: 1_024,
        wal_device: 2,
        wal_inode: 13,
        marker_device: 2,
        marker_inode: 14,
        original_cns_receipt_binding: None,
        challenge_nonce: req.challenge_nonce.clone(),
        observer_signature_bytes: Vec::new(),
    };
    proof.observer_signature_bytes = signer
        .sign(
            &cell_split_control_highwater_signing_bytes_v1(&proof)
                .expect("domain-separated exact Observer proof"),
        )
        .to_bytes()
        .to_vec();
    proof
}

fn response(proof: CellSplitSignedControlHighwaterV1) -> CellSplitControlHighwaterRpcResponseV1 {
    CellSplitControlHighwaterRpcResponseV1 {
        schema: CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1.to_owned(),
        method: READ_METHOD.to_owned(),
        proof: Some(proof),
        error: None,
    }
}

fn client(path: PathBuf, timeout: Duration) -> CellSplitControlHighwaterUnixPortV1 {
    CellSplitControlHighwaterUnixPortV1::new(
        path,
        test_signer().verifying_key(),
        OBSERVER.to_owned(),
        timeout,
    )
    .expect("externally pinned read-only client")
}

#[test]
fn signed_unix_observer_requests_only_scope_split_and_fresh_challenge() {
    let dir = tempfile::tempdir().expect("private test directory");
    let (path, listener) = socket(dir.path());
    let server = thread::spawn(move || {
        for _ in 0..2 {
            let (mut peer, _) = listener.accept().expect("read-only remote request");
            let req = read_request(&mut peer);
            send_response(&mut peer, &response(signed_proof(&req, &test_signer(), 10)));
        }
    });
    let mut client = client(path, Duration::from_secs(2));
    assert_eq!(client.observer_id(), OBSERVER);
    assert_eq!(client.verifying_key(), &test_signer().verifying_key());
    let first = client
        .read_signed_highwater(SPLIT, SCOPE, &"aa".repeat(32))
        .expect("authentic original Observer proof");
    let second = client
        .read_signed_highwater(SPLIT, SCOPE, &"bb".repeat(32))
        .expect("new signed challenge with unchanged high-water");
    assert_eq!(first.sequence, 10);
    assert_eq!(first.wal_head, second.wal_head);
    assert_ne!(first.challenge_nonce, second.challenge_nonce);
    assert_ne!(first.observer_signature_bytes, second.observer_signature_bytes);
    server.join().expect("independent test service");
}

#[test]
fn mismatched_signer_or_signed_replayed_nonce_never_returns_evidence() {
    for wrong_signer in [false, true] {
        let dir = tempfile::tempdir().expect("isolated service");
        let (path, listener) = socket(dir.path());
        let server = thread::spawn(move || {
            let (mut peer, _) = listener.accept().expect("read-only client");
            let req = read_request(&mut peer);
            let mut proof = signed_proof(
                &req,
                if wrong_signer {
                    &SigningKey::from_bytes(&[99; 32])
                } else {
                    &test_signer()
                },
                10,
            );
            if !wrong_signer {
                proof.challenge_nonce = "ff".repeat(32);
                proof.observer_signature_bytes = test_signer()
                    .sign(
                        &cell_split_control_highwater_signing_bytes_v1(&proof)
                            .expect("replayed signed proof"),
                    )
                    .to_bytes()
                    .to_vec();
            }
            send_response(&mut peer, &response(proof));
        });
        let mut client = client(path, Duration::from_secs(2));
        assert!(
            client
                .read_signed_highwater(SPLIT, SCOPE, &"aa".repeat(32))
                .is_err(),
            "wrong signer or stale signed nonce cannot qualify original Control"
        );
        server.join().expect("independent negative service");
    }
}

#[test]
fn even_a_validly_signed_remote_rollback_is_denied_by_client_ratchet() {
    let dir = tempfile::tempdir().expect("service root");
    let (path, listener) = socket(dir.path());
    let server = thread::spawn(move || {
        for sequence in [10, 9] {
            let (mut peer, _) = listener.accept().expect("read-only client");
            let req = read_request(&mut peer);
            send_response(&mut peer, &response(signed_proof(&req, &test_signer(), sequence)));
        }
    });
    let mut client = client(path, Duration::from_secs(2));
    client
        .read_signed_highwater(SPLIT, SCOPE, &"11".repeat(32))
        .expect("first signed remote high-water");
    assert!(
        client
            .read_signed_highwater(SPLIT, SCOPE, &"22".repeat(32))
            .is_err(),
        "signed backwards Control WAL is not a new authoritative baseline"
    );
    server.join().expect("rollback test server");
}

#[test]
fn malformed_denial_and_oversized_frame_are_rejected_before_positive_proof() {
    for oversize in [false, true] {
        let dir = tempfile::tempdir().expect("service");
        let (path, listener) = socket(dir.path());
        let server = thread::spawn(move || {
            let (mut peer, _) = listener.accept().expect("client");
            let req = read_request(&mut peer);
            if oversize {
                peer.write_all(&((MAX_FRAME_BYTES as u32) + 1).to_be_bytes())
                    .expect("oversized header only");
            } else {
                send_response(
                    &mut peer,
                    &CellSplitControlHighwaterRpcResponseV1 {
                        schema: CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1.to_owned(),
                        method: READ_METHOD.to_owned(),
                        proof: Some(signed_proof(&req, &test_signer(), 10)),
                        error: Some("denied".to_owned()),
                    },
                );
            }
        });
        let mut client = client(path, Duration::from_secs(2));
        assert!(
            client
                .read_signed_highwater(SPLIT, SCOPE, &"33".repeat(32))
                .is_err(),
            "mixed or oversized RPC frame must not return signed evidence"
        );
        server.join().expect("malformed RPC service");
    }
}

#[test]
fn missing_or_symlinked_socket_and_unbounded_timeout_fail_closed() {
    let dir = tempfile::tempdir().expect("service");
    let (path, _listener) = socket(dir.path());
    let alias = dir.path().join("forged-observer.sock");
    std::os::unix::fs::symlink(&path, &alias).expect("malicious symlink");
    let mut client = client(alias, Duration::from_millis(25));
    assert!(
        client
            .read_signed_highwater(SPLIT, SCOPE, &"44".repeat(32))
            .is_err(),
        "socket symlink must not redirect high-water trust"
    );
    let mut absent = client(dir.path().join("missing.sock"), Duration::from_millis(25));
    assert!(
        absent
            .read_signed_highwater(SPLIT, SCOPE, &"55".repeat(32))
            .is_err()
    );
    assert!(
        CellSplitControlHighwaterUnixPortV1::new(
            path,
            test_signer().verifying_key(),
            OBSERVER.into(),
            Duration::ZERO,
        )
        .is_err()
    );
}

#[test]
fn truncated_frame_times_out_within_bounded_read_budget() {
    let dir = tempfile::tempdir().expect("service");
    let (path, listener) = socket(dir.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("read-only client");
        let _req = read_request(&mut peer);
        peer.write_all(&(200_u32).to_be_bytes())
            .expect("partial frame header");
        thread::sleep(Duration::from_millis(120));
    });
    let mut client = client(path, Duration::from_millis(20));
    assert!(
        client
            .read_signed_highwater(SPLIT, SCOPE, &"66".repeat(32))
            .is_err(),
        "no signed response may be inferred from a stalled server"
    );
    server.join().expect("stalled read-only server");
}
