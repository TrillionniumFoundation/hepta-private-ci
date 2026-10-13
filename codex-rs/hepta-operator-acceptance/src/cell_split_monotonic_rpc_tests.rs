use std::io::Write as _;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::thread;

use ed25519_dalek::SigningKey;

use super::*;
use crate::cell_split_effect_rpc::receive_frame;
use crate::cell_split_effect_rpc::send_frame;

const DOMAIN: &str = "scope.journal.main";

fn signer() -> SigningKey {
    SigningKey::from_bytes(&[81; 32])
}

fn custody_signer() -> SigningKey {
    SigningKey::from_bytes(&[93; 32])
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
            assert_eq!(raw.as_object().map(serde_json::Map::len), Some(4));
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
        socket,
        signer().verifying_key(),
        Duration::from_secs(2),
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
            let request: CellSplitMonotonicRpcRequestV1 = receive_frame(&mut peer).expect("read");
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
            socket,
            signer().verifying_key(),
            Duration::from_secs(2),
        )
        .expect("external client");
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
        alias,
        signer().verifying_key(),
        Duration::from_millis(25),
    )
    .expect("path not trusted until use");
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"aa".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        temp.path().join("not-serving.sock"),
        signer().verifying_key(),
        Duration::from_millis(25),
    )
    .expect("client");
    assert!(
        client
            .read_domain_frontier(DOMAIN, &"bb".repeat(32))
            .is_err()
    );
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
        peer.write_all(&64_u32.to_be_bytes())
            .expect("truncated header");
        peer.write_all(b"{").expect("incomplete JSON");
        thread::sleep(Duration::from_millis(60));
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket,
        signer().verifying_key(),
        Duration::from_millis(12),
    )
    .expect("timeout bounded client");
    assert!(
        client
            .read_domain_frontier(DOMAIN, &"dd".repeat(32))
            .is_err()
    );
    server.join().expect("slow service");
}

#[test]
fn invalid_and_dual_status_envelopes_fail_closed() {
    let temp = tempfile::tempdir().expect("fixture");
    let (socket, listener) = listener(temp.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("query");
        let request: CellSplitMonotonicRpcRequestV1 = receive_frame(&mut peer).expect("read");
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
        socket,
        signer().verifying_key(),
        Duration::from_secs(1),
    )
    .expect("pinned client");
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"dd".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    server.join().expect("service");
}

/// A disk-backed *test-only* view of an external domain high-water registry.
/// A real deployment must replace this with independently operated monotonic
/// custody; a signed local file cannot detect full directory restoration.
struct DiskAuthoritativeRegistry {
    file: PathBuf,
    reads: usize,
    revoke_on_read: Option<usize>,
    custody_delay: Option<Duration>,
}

impl DiskAuthoritativeRegistry {
    fn open(file: PathBuf) -> Self {
        Self {
            file,
            reads: 0,
            revoke_on_read: None,
            custody_delay: None,
        }
    }
}

impl CellSplitMonotonicAuthoritativeRegistryV1 for DiskAuthoritativeRegistry {
    type Error = std::io::Error;

    fn read_committed_domain(
        &mut self,
        domain: &str,
    ) -> Result<CellSplitMonotonicDurableFrontierV1, Self::Error> {
        self.reads += 1;
        if self.revoke_on_read == Some(self.reads) {
            std::fs::remove_file(&self.file)?;
        }
        let bytes = std::fs::read(&self.file)?;
        let record: CellSplitMonotonicDurableFrontierV1 =
            serde_json::from_slice(&bytes).map_err(std::io::Error::other)?;
        if record.journal_domain_id != domain
            || crate::durable::canonical_json(&record).map_err(std::io::Error::other)? != bytes
        {
            return Err(std::io::Error::other("untrusted domain registry record"));
        }
        Ok(record)
    }

    fn verify_still_current(
        &mut self,
        committed: &CellSplitMonotonicDurableFrontierV1,
    ) -> Result<bool, Self::Error> {
        let bytes = std::fs::read(&self.file)?;
        Ok(crate::durable::canonical_json(committed).map_err(std::io::Error::other)? == bytes)
    }

    fn read_independent_custody(
        &mut self,
        domain: &str,
        nonce: &str,
    ) -> Result<CellSplitMonotonicCustodyProofV1, Self::Error> {
        // Test-only file fixture, NOT a production external trust root.
        if let Some(delay) = self.custody_delay {
            thread::sleep(delay);
        }
        let file = self.file.with_file_name("independently-retained-floor.json");
        let bytes = std::fs::read(file)?;
        let floor: CellSplitMonotonicDurableFrontierV1 =
            serde_json::from_slice(&bytes).map_err(std::io::Error::other)?;
        if floor.journal_domain_id != domain
            || crate::durable::canonical_json(&floor)
                .map_err(std::io::Error::other)? != bytes
        {
            return Err(std::io::Error::other("independent floor mismatch"));
        }
        let mut proof = CellSplitMonotonicCustodyProofV1 {
            schema: CELL_SPLIT_MONOTONIC_CUSTODY_SCHEMA_V1.into(),
            current: floor,
            challenge_nonce: nonce.to_owned(),
            signature_bytes: Vec::new(),
        };
        proof.signature_bytes = custody_signer()
            .sign(
                &cell_split_monotonic_custody_signing_payload_v1(&proof)
                    .map_err(std::io::Error::other)?,
            )
            .to_bytes()
            .to_vec();
        Ok(proof)
    }
}

fn write_test_registry(root: &Path) -> PathBuf {
    let path = root.join("external-domain-highwater.json");
    let record = CellSplitMonotonicDurableFrontierV1 {
        journal_domain_id: DOMAIN.to_owned(),
        journal_authority_epoch: 7,
        journal_revision: 10,
        minimum_checkpoint_digest: "aa".repeat(32),
        original_store_record_digest: "bb".repeat(32),
        durable_source_sequence: 41,
    };
    crate::durable::write_private_new(
        &path,
        &crate::durable::canonical_json(&record).expect("canonical highwater"),
    )
    .expect("fsynced external fixture registry");
    crate::durable::write_private_new(
        &root.join("independently-retained-floor.json"),
        &crate::durable::canonical_json(&record).expect("fixture custody floor"),
    )
    .expect("fsynced custody fixture");
    path
}

#[test]
fn independent_server_reads_real_durable_domain_and_signs_client_challenge() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let (socket, listener) = listener(root.path());
    let server = thread::spawn(move || {
        let (mut peer, _) = listener.accept().expect("real Unix socket");
        let owner = DiskAuthoritativeRegistry::open(file);
        let mut service =
            CellSplitMonotonicRpcServiceV1::new(
                owner,
                signer(),
                custody_signer().verifying_key(),
                Duration::from_secs(3),
            )
                .expect("separately pinned signer");
        service
            .serve_connection(&mut peer)
            .expect("fresh durable frontier");
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket,
        signer().verifying_key(),
        Duration::from_secs(3),
    )
    .expect("original trusted signer");
    let accepted = client
        .read_domain_frontier(DOMAIN, &"aa".repeat(32))
        .expect("independently signed original source");
    assert_eq!(accepted.journal_authority_epoch, 7);
    assert_eq!(accepted.journal_revision, 10);
    assert_eq!(accepted.challenge_nonce, "aa".repeat(32));
    server.join().expect("owner finished");
}

#[test]
fn independent_server_fences_revoked_domain_before_signed_reply() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let mut backend = DiskAuthoritativeRegistry::open(file.clone());
    // First read succeeds; the next read observes an externally revoked
    // authoritative record and may not sign the old current snapshot.
    backend.revoke_on_read = Some(2);
    let mut service =
        CellSplitMonotonicRpcServiceV1::new(
            backend,
            signer(),
            custody_signer().verifying_key(),
            Duration::from_secs(2),
        )
            .expect("independent owner");
    let (mut client, mut server) = std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "cc".repeat(32),
        },
    )
    .expect("read-only request");
    assert!(service.serve_connection(&mut server).is_err());
    assert!(!file.exists());
}

#[test]
fn independent_server_rejects_revoke_during_final_signed_read() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let mut backend = DiskAuthoritativeRegistry::open(file.clone());
    // The first two checks see committed state; the third check runs after
    // signing the reply but before it is sent and must suppress that reply.
    backend.revoke_on_read = Some(3);
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        backend,
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("independent owner");
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "ce".repeat(32),
        },
    )
    .expect("read-only request");
    assert!(service.serve_connection(&mut server).is_err());
    assert!(!file.exists());
}

#[test]
fn independent_server_rejects_caller_supplied_highwater_and_missing_domain() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file.clone()),
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("trusted signer");
    let (mut client, mut server) = std::os::unix::net::UnixStream::pair().expect("pair");
    send_frame(
        &mut client,
        &serde_json::json!({
            "schema": CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1,
            "method": READ_METHOD,
            "journalDomainId": DOMAIN,
            "challengeNonce": "dd".repeat(32),
            "journalRevision": 999,
        }),
    )
    .expect("forged self-affirming request");
    assert!(service.serve_connection(&mut server).is_err());
    let (mut client, mut server) = std::os::unix::net::UnixStream::pair().expect("pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: "unrelated.domain".into(),
            challenge_nonce: "ee".repeat(32),
        },
    )
    .expect("wrong domain request");
    assert!(service.serve_connection(&mut server).is_err());
    assert!(file.exists());
}


/// Single-process ratchet regression: even a freshly signed response from
/// an otherwise valid-looking restored record must not move this signer
/// backward. The external monotonic store remains mandatory across restarts.
fn read_through_signed_service(
    service: &mut CellSplitMonotonicRpcServiceV1<DiskAuthoritativeRegistry>,
    nonce: &str,
) -> Result<CellSplitMonotonicRpcResponseV1, CellSplitMonotonicRpcErrorV1> {
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("private socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.to_owned(),
            method: READ_METHOD.to_owned(),
            journal_domain_id: DOMAIN.to_owned(),
            challenge_nonce: nonce.to_owned(),
        },
    )
    .expect("bounded read-only request");
    service.serve_connection(&mut server)?;
    receive_frame(&mut client).map_err(Into::into)
}

fn replace_test_frontier(
    path: &Path,
    frontier: &CellSplitMonotonicDurableFrontierV1,
) {
    std::fs::write(
        path,
        crate::durable::canonical_json(frontier).expect("canonical registry"),
    )
    .expect("external domain source mutation");
}

#[test]
fn same_signer_denies_rolled_back_or_equivocated_frontier() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let original: CellSplitMonotonicDurableFrontierV1 =
        serde_json::from_slice(&std::fs::read(&file).expect("original record"))
            .expect("typed original");
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file.clone()),
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("pinned signer");
    assert!(read_through_signed_service(&mut service, &"aa".repeat(32)).is_ok());

    let mut rollback = original.clone();
    rollback.journal_revision -= 1;
    rollback.durable_source_sequence -= 1;
    replace_test_frontier(&file, &rollback);
    assert!(read_through_signed_service(&mut service, &"bb".repeat(32)).is_err());

    let mut equivocated = original.clone();
    equivocated.minimum_checkpoint_digest = "cc".repeat(32);
    replace_test_frontier(&file, &equivocated);
    assert!(read_through_signed_service(&mut service, &"cc".repeat(32)).is_err());

    replace_test_frontier(&file, &original);
    assert!(read_through_signed_service(&mut service, &"dd".repeat(32)).is_ok());

    let mut successor = original.clone();
    successor.journal_revision += 1;
    successor.durable_source_sequence += 1;

    // An epoch/revision advance must be accompanied by a new immutable
    // checkpoint and store record. A newly allocated source sequence alone
    // cannot make an old signed terminal checkpoint current again.
    let stale_checkpoint = successor.clone();
    replace_test_frontier(&file, &stale_checkpoint);
    assert!(read_through_signed_service(&mut service, &"ab".repeat(32)).is_err());

    successor.minimum_checkpoint_digest = "ee".repeat(32);
    replace_test_frontier(&file, &successor);
    assert!(read_through_signed_service(&mut service, &"ac".repeat(32)).is_err());

    successor.original_store_record_digest = "dd".repeat(32);
    replace_test_frontier(&file, &successor);
    assert!(read_through_signed_service(&mut service, &"ee".repeat(32)).is_ok());

    // The previous epoch/revision cannot be accepted again, even if it
    // carries its original valid domain registry bytes.
    replace_test_frontier(&file, &original);
    assert!(read_through_signed_service(&mut service, &"ff".repeat(32)).is_err());
}

#[test]
fn same_signer_allows_epoch_rollover_only_with_new_durable_source_sequence() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let original: CellSplitMonotonicDurableFrontierV1 =
        serde_json::from_slice(&std::fs::read(&file).expect("original"))
            .expect("typed original");
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file.clone()),
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("pinned signer");
    assert!(read_through_signed_service(&mut service, &"aa".repeat(32)).is_ok());

    let mut stale_rollover = original.clone();
    stale_rollover.journal_authority_epoch += 1;
    stale_rollover.journal_revision = 1;
    replace_test_frontier(&file, &stale_rollover);
    assert!(read_through_signed_service(&mut service, &"bb".repeat(32)).is_err());

    stale_rollover.durable_source_sequence += 1;
    replace_test_frontier(&file, &stale_rollover);
    assert!(read_through_signed_service(&mut service, &"cc".repeat(32)).is_err());
    stale_rollover.minimum_checkpoint_digest = "cc".repeat(32);
    replace_test_frontier(&file, &stale_rollover);
    assert!(read_through_signed_service(&mut service, &"cd".repeat(32)).is_err());
    stale_rollover.original_store_record_digest = "dd".repeat(32);
    replace_test_frontier(&file, &stale_rollover);
    assert!(read_through_signed_service(&mut service, &"ce".repeat(32)).is_ok());
    replace_test_frontier(&file, &original);
    assert!(read_through_signed_service(&mut service, &"dd".repeat(32)).is_err());
}


#[test]
fn client_rejects_old_still_signed_highwater_after_remote_restart() {
    let root = tempfile::tempdir().expect("Unix RPC fixture");
    let (socket, listener) = listener(root.path());
    let service = thread::spawn(move || {
        for sequence in 0..2 {
            let (mut peer, _) = listener.accept().expect("current domain query");
            let request: CellSplitMonotonicRpcRequestV1 =
                receive_frame(&mut peer).expect("read-only request");
            let mut proof = make_proof(
                &request.journal_domain_id,
                &request.challenge_nonce,
                &signer(),
            );
            if sequence == 1 {
                // The same trusted signing identity restarted from an older
                // but internally valid revision. The client must not accept
                // a fresh nonce as evidence that the state is current.
                proof.journal_revision = 9;
                proof.signature_bytes.clear();
                proof.signature_bytes = signer()
                    .sign(&cell_split_supervisor_monotonic_frontier_signing_payload_v1(&proof)
                        .expect("original signing grammar"))
                    .to_bytes()
                    .to_vec();
            }
            send_frame(
                &mut peer,
                &CellSplitMonotonicRpcResponseV1 {
                    schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                    method: READ_METHOD.into(),
                    proof: Some(proof),
                    error: None,
                },
            )
            .expect("signed response");
        }
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket,
        signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("pinned verifier");
    let first = client.read_domain_frontier(DOMAIN, &"11".repeat(32))
        .expect("signed initial high water");
    assert_eq!(first.journal_revision, 10);
    assert!(matches!(
        client.read_domain_frontier(DOMAIN, &"22".repeat(32)),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    service.join().expect("service");
}

#[test]
fn client_accepts_advanced_signed_highwater_with_new_checkpoint_identity() {
    let root = tempfile::tempdir().expect("Unix RPC fixture");
    let (socket, listener) = listener(root.path());
    let service = thread::spawn(move || {
        for sequence in 0..2 {
            let (mut peer, _) = listener.accept().expect("current domain query");
            let request: CellSplitMonotonicRpcRequestV1 =
                receive_frame(&mut peer).expect("read-only request");
            let mut proof = make_proof(
                &request.journal_domain_id,
                &request.challenge_nonce,
                &signer(),
            );
            if sequence == 1 {
                proof.journal_revision = 11;
                proof.minimum_checkpoint_digest = "cc".repeat(32);
                proof.original_store_record_digest = "dd".repeat(32);
                proof.signature_bytes.clear();
                proof.signature_bytes = signer()
                    .sign(&cell_split_supervisor_monotonic_frontier_signing_payload_v1(&proof)
                        .expect("fresh higher frontier"))
                    .to_bytes()
                    .to_vec();
            }
            send_frame(
                &mut peer,
                &CellSplitMonotonicRpcResponseV1 {
                    schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
                    method: READ_METHOD.into(),
                    proof: Some(proof),
                    error: None,
                },
            )
            .expect("signed response");
        }
    });
    let mut client = CellSplitSupervisorMonotonicUnixPortV1::new(
        socket,
        signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("pinned verifier");
    assert_eq!(
        client.read_domain_frontier(DOMAIN, &"11".repeat(32))
            .expect("first observation").journal_revision,
        10,
    );
    assert_eq!(
        client.read_domain_frontier(DOMAIN, &"22".repeat(32))
            .expect("new independent committed frontier").journal_revision,
        11,
    );
    service.join().expect("service");
}



#[test]
fn independently_retained_newer_floor_denies_rolled_back_registry_after_server_restart() {
    let root = tempfile::tempdir().expect("private test root");
    let file = write_test_registry(root.path());
    // The Registry process restarts with its signed old revision 10 file,
    // while an independent custody owner has already retained revision 11.
    // Process-local ratchets are empty, so the separate signature must
    // reject the stale record before the RPC server signs any response.
    let floor_path = root.path().join("independently-retained-floor.json");
    let mut newer: CellSplitMonotonicDurableFrontierV1 =
        serde_json::from_slice(&std::fs::read(&floor_path).expect("original floor"))
            .expect("floor record");
    newer.journal_revision += 1;
    newer.durable_source_sequence += 1;
    newer.minimum_checkpoint_digest = "cc".repeat(32);
    newer.original_store_record_digest = "dd".repeat(32);
    std::fs::write(
        &floor_path,
        crate::durable::canonical_json(&newer).expect("new custody floor"),
    )
    .expect("independent custody advanced");
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file.clone()),
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("new signing process with no retained memory");
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "aa".repeat(32),
        },
    )
    .expect("read-only frontier request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    assert!(file.exists(), "the old signed Registry record is still present");
}

#[test]
fn independently_pinned_custody_key_must_not_be_selected_by_rpc_signer() {
    let root = tempfile::tempdir().expect("private test root");
    let file = write_test_registry(root.path());
    let untrusted = SigningKey::from_bytes(&[95_u8; 32]).verifying_key();
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file),
        signer(),
        untrusted,
        Duration::from_secs(2),
    )
    .expect("distinct but incorrect custody trust root");
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "bb".repeat(32),
        },
    )
    .expect("read-only request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitMonotonicRpcErrorV1::Untrusted)
    ));
    assert!(
        CellSplitMonotonicRpcServiceV1::new(
            DiskAuthoritativeRegistry::open(root.path().join("external-domain-highwater.json")),
            signer(),
            signer().verifying_key(),
            Duration::from_secs(2),
        )
        .is_err(),
        "RPC signer must never self-certify independent custody"
    );
}

#[test]
fn missing_independent_custody_denies_fresh_remote_monotonic_signature() {
    let root = tempfile::tempdir().expect("private test root");
    let file = write_test_registry(root.path());
    std::fs::remove_file(root.path().join("independently-retained-floor.json"))
        .expect("independent floor withdrawn");
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        DiskAuthoritativeRegistry::open(file),
        signer(),
        custody_signer().verifying_key(),
        Duration::from_secs(2),
    )
    .expect("separate signatures");
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "cc".repeat(32),
        },
    )
    .expect("query");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitMonotonicRpcErrorV1::Denied(_))
    ));
}


#[test]
fn slow_independent_custody_cannot_sign_after_owner_request_budget_expires() {
    let root = tempfile::tempdir().expect("private registry");
    let file = write_test_registry(root.path());
    let mut backend = DiskAuthoritativeRegistry::open(file.clone());
    backend.custody_delay = Some(Duration::from_millis(15));
    let mut service = CellSplitMonotonicRpcServiceV1::new(
        backend,
        signer(),
        custody_signer().verifying_key(),
        Duration::from_millis(2),
    )
    .expect("small bounded owner budget");
    let (mut client, mut server) =
        std::os::unix::net::UnixStream::pair().expect("socket pair");
    send_frame(
        &mut client,
        &CellSplitMonotonicRpcRequestV1 {
            schema: CELL_SPLIT_MONOTONIC_RPC_SCHEMA_V1.into(),
            method: READ_METHOD.into(),
            journal_domain_id: DOMAIN.into(),
            challenge_nonce: "ab".repeat(32),
        },
    )
    .expect("fully queued request");
    assert!(matches!(
        service.serve_connection(&mut server),
        Err(CellSplitMonotonicRpcErrorV1::Invalid)
    ));
    drop(server);
    assert!(receive_frame::<CellSplitMonotonicRpcResponseV1>(&mut client).is_err());
    assert!(file.exists(), "timeout must not mutate durable custody");
}
