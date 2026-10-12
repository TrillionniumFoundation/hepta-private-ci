use std::io::Write as _;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::thread;

use ed25519_dalek::{Signer as _, SigningKey};

use super::*;
use crate::cell_split_effect_rpc::{receive_frame, send_frame};

const DOMAIN: &str = "scope.journal.main";

fn signer() -> SigningKey {
    SigningKey::from_bytes(&[81; 32])
}

fn make_proof(
    domain: &str,
    nonce: &str,
    signing_key: &SigningKey,
) -> CellSplitSupervisorMonotonicFrontierV1 {
    let mut proof = CellSplitSupervisorMonotonicFrontierV1 {
        schema: CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1.to_owned(),
        journal_domain_id: domain.to_owned(),
        journal_authority_epoch: 7,
        journal_revision: 10,
        minimum_checkpoint_digest: "aa".repeat(32),
        original_store_record_digest: "bb".repeat(32),
        challenge_nonce: nonce.to_owned(),
        signature_bytes: Vec::new(),
    };
    proof.signature_bytes = signing_key
        .sign(
            &cell_split_supervisor_monotonic_frontier_signing_payload_v1(&proof)
                .expect("domain-separated signing payload"),
        )
        .to_bytes()
        .to_vec();
    proof
}

fn listener(root: &Path) -> (PathBuf, UnixListener) {
    let socket = root.join("monotonic-frontier.sock");
    let listener = UnixListener::bind(&socket).expect("independent service socket");
    (socket, listener)
}

#[test]
fn read_only_client_sends_only_domain_and_fresh_challenge() {
    let temp = tempfile::tempdir().expect("fixture");
    let (socket, listener) = listener(temp.path());
    let server = thread::spawn(move || {
        for _ in 0..2 {
            let (mut peer, _) = listener.accept().expect("signed store query");
            let raw: serde_json::Value = receive_frame(&mut peer).expect("request");
            // If the client could include an expected revision/digest, an old
            // restored local checkpoint could ask a service to sign itself.
            assert_eq!(raw.as_object().map(|fields| fields.len()), Some(4));
            assert!(raw.get("journalRevision").is_none());
            assert!(raw.get("minimumCheckpointDigest").is_none());
            assert!(raw.get("originalStoreRecordDigest").is_none());
            let request: CellSplitMonotonicRpcRequestV1 =
                serde_json::from_value(raw).expect("strict read-only request");
            assert_eq!(request.schema, CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1);
            assert_eq!(request.method, READ_METHOD);
            assert_eq!(request.journal_domain_id, DOMAIN);
            let proof = make_proof(
                &request.journal_domain_id,
                &request.challenge_nonce,
                &signer(),
            );
            send_frame(
                &mut peer,
                &CellSplitMonotonicRpcResponseV1 {
                    schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                    method: READ_METHOD.into(),
                    proof: Some(proof),
                    error: None,
                },
            )
            .expect("original independently signed frontier");
        }
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket,
        signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("pinned external port");
    let first = client
        .read_domain_frontier(DOMAIN, &"aa".repeat(32))
        .expect("independently signed first read");
    let second = client
        .read_domain_frontier(DOMAIN, &"bb".repeat(32))
        .expect("independently signed second read");
    assert_eq!(first.journal_revision, 10);
    assert_eq!(second.journal_revision, 10);
    assert_ne!(first.challenge_nonce, second.challenge_nonce);
    assert_ne!(first.signature_bytes, second.signature_bytes);
    server.join().expect("service");
}

#[test]
fn signed_response_from_wrong_service_identity_is_refused() {
    let temp = tempfile::tempdir().expect("fixture");
    let (socket, listener) = listener(temp.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("client");
        let request: CellSplitMonotonicRpcRequestV1 =
            receive_frame(&mut peer).expect("read request");
        let wrong = SigningKey::from_bytes(&[82; 32]);
        send_frame(
            &mut peer,
            &CellSplitMonotonicRpcResponseV1 {
                schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                method: READ_METHOD.into(),
                proof: Some(make_proof(
                    &request.journal_domain_id,
                    &request.challenge_nonce,
                    &wrong,
                )),
                error: None,
            },
        )
        .expect("attacker response");
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket, signer().verifying_key(), Duration::from_secs(2),
    )
    .expect("external trust pin");
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"cc".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Untrusted)
    ));
    server.join().expect("server");
}

#[test]
fn old_nonce_or_other_domain_is_rejected_even_if_signed() {
    for other_domain in [false, true] {
        let temp = tempfile::tempdir().expect("fixture");
        let (socket, listener) = listener(temp.path());
        let server = thread::spawn(move || {
            let (mut peer, _) = listener.accept().expect("query");
            let request: CellSplitMonotonicRpcRequestV1 =
                receive_frame(&mut peer).expect("read");
            let domain = if other_domain {
                "another.authority.domain"
            } else {
                request.journal_domain_id.as_str()
            };
            let old_nonce = "ee".repeat(32);
            let nonce = if other_domain {
                request.challenge_nonce.as_str()
            } else {
                old_nonce.as_str()
            };
            let forged = make_proof(domain, nonce, &signer());
            send_frame(
                &mut peer,
                &CellSplitMonotonicRpcResponseV1 {
                    schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                    method: READ_METHOD.into(),
                    proof: Some(forged),
                    error: None,
                },
            )
            .expect("signed but unrelated proof");
        });
        let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
            socket, signer().verifying_key(), Duration::from_secs(2),
        ).expect("external client");
        assert!(matches!(
            client.read_domain_frontier(DOMAIN, &"ff".repeat(32)),
            Err(CellSplitMonotonicRpcErrorV1::Invalid)
        ));
        server.join().expect("server");
    }
}

#[test]
fn absent_or_symlinked_socket_never_returns_a_monotonic_proof() {
    let temp = tempfile::tempdir().expect("fixture");
    let real = temp.path().join("real.sock");
    let _listener = UnixListener::bind(&real).expect("socket");
    let alias = temp.path().join("alias.sock");
    std::os::unix::fs::symlink(&real, &alias).expect("alias");
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        alias, signer().verifying_key(), Duration::from_millis(25),
    ).expect("path not trusted until use");
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"aa".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        temp.path().join("not-serving.sock"),
        signer().verifying_key(),
        Duration::from_millis(25),
    ).expect("client");
    assert!(client.read_domain_frontier(DOMAIN, &"bb".repeat(32)).is_err());
    assert!(CellSplitSupervisorMonotonicUnixPortV1::new(
        real, signer().verifying_key(), Duration::ZERO,
    ).is_err());
}

#[test]
fn truncated_independent_response_cannot_hold_an_owner_forever() {
    let temp = tempfile::tempdir().expect("fixture");
    let (socket, listener) = listener(temp.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("query");
        let _: CellSplitMonotonicRpcRequestV1 =
            receive_frame(&mut peer).expect("bounded client request");
        peer.write_all(&64_u32.to_be_bytes()).expect("truncated header");
        peer.write_all(b"{").expect("incomplete JSON");
        thread::sleep(Duration::from_millis(60));
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket, signer().verifying_key(), Duration::from_millis(12),
    ).expect("timeout bounded client");
    assert!(client.read_domain_frontier(DOMAIN, &"dd".repeat(32)).is_err());
    server.join().expect("slow service");
}

#[test]
fn invalid_and_dual_status_envelopes_fail_closed() {
    let temp = tempfile::tempdir().expect("fixture");
    let (socket, listener) = listener(temp.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("query");
        let request: CellSplitMonotonicRpcRequestV1 =
            receive_frame(&mut peer).expect("read");
        send_frame(
            &mut peer,
            &CellSplitMonotonicRpcResponseV1 {
                schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                method: READ_METHOD.into(),
                proof: Some(make_proof(
                    &request.journal_domain_id,
                    &request.challenge_nonce,
                    &signer(),
                )),
                error: Some("denied".into()),
            },
        )
        .expect("invalid response");
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket, signer().verifying_key(), Duration::from_secs(1),
    ).expect("pinned client");
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"dd".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    server.join().expect("service");
}
