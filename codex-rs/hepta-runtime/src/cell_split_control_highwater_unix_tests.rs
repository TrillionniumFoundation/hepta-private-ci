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

fn read_request_for_split(
    peer: &mut UnixStream,
    expected_split: &str,
) -> CellSplitControlHighwaterRpcRequestV1 {
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
        assert!(
            raw.get(forbidden).is_none(),
            "untrusted echo input {forbidden}"
        );
    }
    let request: CellSplitControlHighwaterRpcRequestV1 =
        serde_json::from_value(raw).expect("strict read-only wire schema");
    assert_eq!(request.schema, CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1);
    assert_eq!(request.method, READ_METHOD);
    assert_eq!(request.split_id, expected_split);
    assert_eq!(request.scope_id, SCOPE);
    request
}

fn read_request(peer: &mut UnixStream) -> CellSplitControlHighwaterRpcRequestV1 {
    read_request_for_split(peer, SPLIT)
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
    assert_ne!(
        first.observer_signature_bytes,
        second.observer_signature_bytes
    );
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
            let signer = if wrong_signer {
                SigningKey::from_bytes(&[99; 32])
            } else {
                test_signer()
            };
            let mut proof = signed_proof(&req, &signer, 10);
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
            send_response(
                &mut peer,
                &response(signed_proof(&req, &test_signer(), sequence)),
            );
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
fn signed_same_sequence_cannot_rewrite_checkpoint_or_frozen_plan() {
    // A remote signer can still sign conflicting bytes. The client must not
    // accept two distinct original Control states at the same WAL sequence.
    for wrong_plan in [false, true] {
        let root = tempfile::tempdir().expect("separate witness root");
        let (socket_path, listener) = socket(root.path());
        let server = thread::spawn(move || {
            for observation in 0..2 {
                let (mut peer, _) = listener.accept().expect("read-only RPC");
                let request = read_request(&mut peer);
                let mut claim = signed_proof(&request, &test_signer(), 10);
                if observation == 1 {
                    if wrong_plan {
                        claim.plan_digest = "dd".repeat(32);
                    } else {
                        claim.checkpoint_digest = "ee".repeat(32);
                    }
                    claim.observer_signature_bytes = test_signer()
                        .sign(
                            &cell_split_control_highwater_signing_bytes_v1(&claim)
                                .expect("signed contradictory same-revision claim"),
                        )
                        .to_bytes()
                        .to_vec();
                }
                send_response(&mut peer, &response(claim));
            }
        });
        let mut verifier = client(socket_path, Duration::from_secs(2));
        verifier
            .read_signed_highwater(SPLIT, SCOPE, &"11".repeat(32))
            .expect("first independently signed original state");
        assert!(
            verifier
                .read_signed_highwater(SPLIT, SCOPE, &"22".repeat(32))
                .is_err(),
            "same Control sequence cannot assert a different checkpoint or plan"
        );
        server.join().expect("contradictory signed server");
    }
}

#[test]
fn signed_newer_sequence_cannot_shrink_original_wal_or_lower_fences() {
    for smaller_wal in [true, false] {
        let root = tempfile::tempdir().expect("separate witness root");
        let (socket_path, listener) = socket(root.path());
        let server = thread::spawn(move || {
            for observation in 0..2 {
                let (mut peer, _) = listener.accept().expect("read-only RPC");
                let request = read_request(&mut peer);
                let mut claim = signed_proof(
                    &request,
                    &test_signer(),
                    if observation == 0 { 10 } else { 11 },
                );
                if observation == 1 {
                    // A correct advanced WAL would be longer. Isolate the
                    // independent minimum-byte and fence checks instead of
                    // having both failures caused by an unchanged byte count.
                    claim.wal_bytes = 2_048;
                    if smaller_wal {
                        claim.wal_bytes = 512;
                    } else {
                        claim.route_fence = 6;
                    }
                    claim.observer_signature_bytes = test_signer()
                        .sign(
                            &cell_split_control_highwater_signing_bytes_v1(&claim)
                                .expect("signed but invalid successor frontier"),
                        )
                        .to_bytes()
                        .to_vec();
                }
                send_response(&mut peer, &response(claim));
            }
        });
        let mut verifier = client(socket_path, Duration::from_secs(2));
        verifier
            .read_signed_highwater(SPLIT, SCOPE, &"33".repeat(32))
            .expect("initial original WAL frontier");
        assert!(
            verifier
                .read_signed_highwater(SPLIT, SCOPE, &"44".repeat(32))
                .is_err(),
            "newer signed Control sequence cannot shrink WAL or lower fences"
        );
        server.join().expect("forked signed server");
    }
}

#[test]
fn valid_signed_control_wal_append_is_accepted_without_evicting_history() {
    // A stricter rollback guard must still accept a genuine advanced
    // sequence and allow a subsequent nonce-bound observation of that same
    // committed state. All state claims are fixture-signed on an OS socket.
    let root = tempfile::tempdir().expect("separate observer owner");
    let (socket_path, listener) = socket(root.path());
    let server = thread::spawn(move || {
        for observation in 0..3 {
            let (mut peer, _) = listener.accept().expect("bounded read-only RPC");
            let request = read_request(&mut peer);
            let mut claim = signed_proof(
                &request,
                &test_signer(),
                if observation == 0 { 10 } else { 11 },
            );
            if observation > 0 {
                claim.wal_bytes = 2_048;
                claim.checkpoint_digest = "dd".repeat(32);
                claim.observer_signature_bytes = test_signer()
                    .sign(
                        &cell_split_control_highwater_signing_bytes_v1(&claim)
                            .expect("new durable frontier proof"),
                    )
                    .to_bytes()
                    .to_vec();
            }
            send_response(&mut peer, &response(claim));
        }
    });
    let mut verifier = client(socket_path, Duration::from_secs(2));
    let first = verifier
        .read_signed_highwater(SPLIT, SCOPE, &"66".repeat(32))
        .expect("old signed committed Control state");
    let next = verifier
        .read_signed_highwater(SPLIT, SCOPE, &"77".repeat(32))
        .expect("valid original WAL append");
    let repeated = verifier
        .read_signed_highwater(SPLIT, SCOPE, &"88".repeat(32))
        .expect("unchanged newly committed frontier with a new challenge");
    assert_eq!(first.sequence, 10);
    assert_eq!(next.sequence, 11);
    assert_eq!(next.wal_bytes, 2_048);
    assert_eq!(next.sequence, repeated.sequence);
    assert_eq!(next.wal_head, repeated.wal_head);
    assert_eq!(next.checkpoint_digest, repeated.checkpoint_digest);
    assert_ne!(next.challenge_nonce, repeated.challenge_nonce);
    assert_ne!(
        next.observer_signature_bytes,
        repeated.observer_signature_bytes
    );
    server.join().expect("signed Control test service");
}

#[test]
fn signed_later_control_wal_cannot_forget_an_original_cns_receipt_binding() {
    // Control records an original CNS receipt in an fsynced C row. A later
    // checkpoint P or cutover C can advance its binding but cannot erase it.
    // This is a signed Unix RPC test, not a local digest-only declaration.
    for (new_split, erased_binding) in [
        (false, true),
        (true, true),
        (false, false),
        (true, false),
    ] {
        let root = tempfile::tempdir().expect("separate signed Observer root");
        let (socket_path, listener) = socket(root.path());
        let server = thread::spawn(move || {
            for observation in 0..2 {
                let (mut peer, _) = listener.accept().expect("original read-only request");
                let split = if new_split && observation == 1 {
                    "split-2"
                } else {
                    SPLIT
                };
                let request = read_request_for_split(&mut peer, split);
                let mut claim = signed_proof(
                    &request,
                    &test_signer(),
                    if observation == 0 {
                        10
                    } else if new_split {
                        12
                    } else {
                        11
                    },
                );
                claim.original_cns_receipt_binding = if observation == 0 || !new_split && !erased_binding {
                    Some("dd".repeat(32))
                } else if erased_binding {
                    None
                } else {
                    Some("ee".repeat(32))
                };
                if observation == 1 {
                    claim.wal_bytes = 2_048;
                    if new_split {
                        claim.plan_digest = "ff".repeat(32);
                        claim.ndu_snapshot_digest = "ee".repeat(32);
                        claim.generation = 4;
                        claim.route_fence = 8;
                        claim.revocation_epoch = 10;
                    }
                }
                claim.observer_signature_bytes = test_signer()
                    .sign(
                        &cell_split_control_highwater_signing_bytes_v1(&claim)
                            .expect("fully signed CNS binding history"),
                    )
                    .to_bytes()
                    .to_vec();
                send_response(&mut peer, &response(claim));
            }
        });

        let mut verifier = client(socket_path, Duration::from_secs(2));
        let first = verifier
            .read_signed_highwater(SPLIT, SCOPE, &"33".repeat(32))
            .expect("signed original committed CNS binding");
        assert_eq!(first.original_cns_receipt_binding, Some("dd".repeat(32)));
        let successor_split = if new_split { "split-2" } else { SPLIT };
        let second = verifier.read_signed_highwater(successor_split, SCOPE, &"44".repeat(32));
        if erased_binding {
            assert!(
                second.is_err(),
                "a newer signed WAL must not erase an original CNS effect binding"
            );
            assert_eq!(
                verifier
                    .seen
                    .get(SCOPE)
                    .expect("original Scope remains pinned")
                    .original_cns_receipt_binding,
                Some("dd".repeat(32))
            );
        } else {
            let next = second.expect("a genuine post-Commit or unchanged P frontier is permitted");
            assert_eq!(next.sequence, if new_split { 12 } else { 11 });
            assert_eq!(next.wal_bytes, 2_048);
            let expected_binding = if new_split { "ee" } else { "dd" };
            assert_eq!(next.original_cns_receipt_binding, Some(expected_binding.repeat(32)));
        }
        server.join().expect("signed original high-water RPC server");
    }
}

#[test]
fn changed_original_cns_binding_requires_begin_commit_and_new_route_fence() {
    // An original CNS binding can change only on a Control C record after B.
    // Signed claims with just one new row, no new route fence, or a reused
    // already-committed Split ID cannot manufacture another physical effect.
    for violation in 0_u8..3 {
        let root = tempfile::tempdir().expect("separate signed Observer");
        let (path, listener) = socket(root.path());
        let server = thread::spawn(move || {
            for observation in 0..2 {
                let (mut peer, _) = listener.accept().expect("original read-only RPC");
                let new_split = violation != 2;
                let split = if new_split && observation == 1 {
                    "split-2"
                } else {
                    SPLIT
                };
                let request = read_request_for_split(&mut peer, split);
                let sequence = if observation == 0 {
                    10
                } else if violation == 0 {
                    11
                } else {
                    12
                };
                let mut claim = signed_proof(&request, &test_signer(), sequence);
                let receipt_digest = if observation == 0 { "dd" } else { "ee" };
                claim.original_cns_receipt_binding = Some(receipt_digest.repeat(32));
                if observation == 1 {
                    claim.wal_bytes = 2_048;
                    claim.generation = 4;
                    claim.route_fence = if violation == 1 { 7 } else { 8 };
                    claim.revocation_epoch = 10;
                    if new_split {
                        claim.plan_digest = "ff".repeat(32);
                        claim.ndu_snapshot_digest = "ee".repeat(32);
                    }
                }
                claim.observer_signature_bytes = test_signer()
                    .sign(
                        &cell_split_control_highwater_signing_bytes_v1(&claim)
                            .expect("signed but impossible original Control C claim"),
                    )
                    .to_bytes()
                    .to_vec();
                send_response(&mut peer, &response(claim));
            }
        });

        let mut verifier = client(path, Duration::from_secs(2));
        verifier
            .read_signed_highwater(SPLIT, SCOPE, &"11".repeat(32))
            .expect("real prior original CNS binding");
        let second_split = if violation == 2 { SPLIT } else { "split-2" };
        assert!(
            verifier
                .read_signed_highwater(second_split, SCOPE, &"22".repeat(32))
                .is_err(),
            "a complete original B/C and independent new Split fence are required"
        );
        let retained = verifier.seen.get(SCOPE).expect("original ratchet retained");
        assert_eq!(retained.sequence, 10);
        assert_eq!(retained.original_cns_receipt_binding, Some("dd".repeat(32)));
        server.join().expect("signed two-stage Control test service");
    }
}

#[test]
fn signed_new_split_id_cannot_reset_original_scope_wal_ratchet() {
    // A genuine remote signature is not enough to reset a previously seen
    // original WAL by changing only the Cell Split request identity.
    // Four independent adversarial cases: lower sequence, same-sequence
    // fork, swapped original WAL inode, and unsigned NDU trust-root change.
    for fork in 0_u8..4 {
        let root = tempfile::tempdir().expect("private independent Observer");
        let (path, listener) = socket(root.path());
        let server = thread::spawn(move || {
            for observation in 0..2 {
                let (mut peer, _) = listener.accept().expect("read-only request");
                let split = if observation == 0 { SPLIT } else { "split-2" };
                let request = read_request_for_split(&mut peer, split);
                let sequence = if observation == 0 {
                    10
                } else if fork == 0 {
                    9
                } else if fork == 1 {
                    10
                } else {
                    11
                };
                let mut claim = signed_proof(&request, &test_signer(), sequence);
                if observation == 1 {
                    claim.plan_digest = "dd".repeat(32);
                    if fork >= 2 {
                        claim.wal_bytes = 2_048;
                    }
                    if fork == 2 {
                        claim.wal_inode = 99;
                    }
                    if fork == 3 {
                        claim.ndu_owner_id = "another-ndu-owner".into();
                    }
                    claim.observer_signature_bytes = test_signer()
                        .sign(
                            &cell_split_control_highwater_signing_bytes_v1(&claim)
                                .expect("fully signed hostile cross-Split proof"),
                        )
                        .to_bytes()
                        .to_vec();
                }
                send_response(&mut peer, &response(claim));
            }
        });
        let mut verifier = client(path, Duration::from_secs(2));
        verifier
            .read_signed_highwater(SPLIT, SCOPE, &"11".repeat(32))
            .expect("first signed original WAL frontier");
        assert!(
            verifier
                .read_signed_highwater("split-2", SCOPE, &"22".repeat(32))
                .is_err(),
            "Split IDs cannot hide rollback, fork, inode ABA or owner change"
        );
        assert_eq!(verifier.seen.len(), 1);
        assert_eq!(
            verifier
                .seen
                .get(SCOPE)
                .expect("original Scope ratchet")
                .split_id,
            SPLIT
        );
        server.join().expect("hostile signed Observer fixture");
    }
}

#[test]
fn new_split_may_follow_actual_same_inode_wal_append_without_erasing_scope_ratchet() {
    // Distinct frozen plans/snapshots are possible after a REAL committed
    // WAL advancement. The original Scope's inode and trusted owner remain
    // pinned, while its sequence, bytes and fences advance monotonically.
    let root = tempfile::tempdir().expect("private independent Observer");
    let (path, listener) = socket(root.path());
    let server = thread::spawn(move || {
        for observation in 0..3 {
            let (mut peer, _) = listener.accept().expect("read-only request");
            let split = if observation == 0 { SPLIT } else { "split-2" };
            let request = read_request_for_split(&mut peer, split);
            let mut claim = signed_proof(
                &request,
                &test_signer(),
                if observation == 0 { 10 } else { 11 },
            );
            if observation > 0 {
                claim.wal_bytes = 2_048;
                claim.generation = 4;
                claim.route_fence = 8;
                claim.revocation_epoch = 10;
                claim.plan_digest = "dd".repeat(32);
                claim.ndu_snapshot_digest = "ee".repeat(32);
                claim.checkpoint_digest = "ff".repeat(32);
                claim.observer_signature_bytes = test_signer()
                    .sign(
                        &cell_split_control_highwater_signing_bytes_v1(&claim)
                            .expect("advanced original WAL proof"),
                    )
                    .to_bytes()
                    .to_vec();
            }
            send_response(&mut peer, &response(claim));
        }
    });
    let mut verifier = client(path, Duration::from_secs(2));
    let original = verifier
        .read_signed_highwater(SPLIT, SCOPE, &"33".repeat(32))
        .expect("first original Scope frontier");
    let next = verifier
        .read_signed_highwater("split-2", SCOPE, &"44".repeat(32))
        .expect("different Split ID with real monotonic original WAL append");
    let repeated = verifier
        .read_signed_highwater("split-2", SCOPE, &"55".repeat(32))
        .expect("same new Split, different fresh challenge, same original WAL");
    assert_eq!(original.sequence, 10);
    assert_eq!(next.sequence, 11);
    assert_eq!(repeated.sequence, 11);
    assert_eq!(next.wal_bytes, 2_048);
    assert_eq!(next.wal_inode, original.wal_inode);
    assert_ne!(original.plan_digest, next.plan_digest);
    assert_eq!(next.plan_digest, repeated.plan_digest);
    assert_ne!(
        next.observer_signature_bytes,
        repeated.observer_signature_bytes
    );
    assert_eq!(verifier.seen.len(), 1);
    assert_eq!(
        verifier
            .seen
            .get(SCOPE)
            .expect("one monotonic Scope frontier")
            .split_id,
        "split-2"
    );
    server.join().expect("monotonic original Scope fixture");
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
    let mut symlink_client = client(alias, Duration::from_millis(25));
    assert!(
        symlink_client
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
