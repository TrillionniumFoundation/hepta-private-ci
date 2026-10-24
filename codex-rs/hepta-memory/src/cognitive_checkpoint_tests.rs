//! Test-only protocol peer. This exercises original SQLite/owner integration;
//! it does not qualify a protected service, filesystem durability, or restart.

use super::test_support::*;
use super::*;
use crate::cognitive_checkpoint::*;
use crate::cognitive_checkpoint_wire::*;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use tokio::sync::Notify;

struct ProtocolPeer {
    receipt: Mutex<CognitiveCheckpointReceipt>,
    commands: Mutex<Vec<CognitiveCheckpointCommand>>,
    hold_current_reply: AtomicBool,
    hold_prepare_reply: AtomicBool,
    prepared: Notify,
    resume_prepare: Notify,
    wrong_owner_reply: AtomicBool,
    published: Notify,
    revoke_after_publication: AtomicBool,
    verifier: Arc<TestVerifier>,
}

impl CognitiveCheckpointTransport for ProtocolPeer {
    async fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        let request: CognitiveCheckpointRequest = serde_json::from_slice(bytes).unwrap();
        self.commands.lock().unwrap().push(request.command);
        let current = {
            let mut current = self.receipt.lock().unwrap();
            if request.command != CognitiveCheckpointCommand::ReadHead {
                assert_eq!(
                    u64::from_str_radix(&request.request_id[..16], 16).unwrap(),
                    current.head.publisher_epoch
                );
                assert!(
                    u64::from_str_radix(&request.request_id[16..], 16).unwrap()
                        > current.head.last_mutation_sequence
                );
                assert_eq!(request.expected, Some(current.token.clone()));
                let predecessor_token = current.token.clone();
                let head = &mut current.head;
                match request.command {
                    CognitiveCheckpointCommand::BeginWrites => {
                        assert_eq!(head.phase, CognitiveCheckpointPhase::Current);
                        head.phase = CognitiveCheckpointPhase::Dirty;
                    }
                    CognitiveCheckpointCommand::PreparePublication => {
                        assert_eq!(head.phase, CognitiveCheckpointPhase::Dirty);
                        let proposal = request.proposal.as_ref().unwrap();
                        head.phase = CognitiveCheckpointPhase::Publishing;
                        head.proposal = Some(CognitiveCheckpointRetainedProposal {
                            request_id: request.request_id.clone(),
                            cut: proposal.cut.clone(),
                            writer_fence: proposal.writer_fence.clone(),
                        });
                    }
                    CognitiveCheckpointCommand::CommitPublication => {
                        assert_eq!(head.phase, CognitiveCheckpointPhase::Publishing);
                        head.last_current = head.proposal.take().unwrap().cut;
                        head.phase = CognitiveCheckpointPhase::Current;
                    }
                    CognitiveCheckpointCommand::FencePublisher => {
                        head.phase = CognitiveCheckpointPhase::Fenced;
                    }
                    CognitiveCheckpointCommand::ReadHead => unreachable!(),
                }
                head.counter += 1;
                head.last_mutation_sequence =
                    u64::from_str_radix(&request.request_id[16..], 16).unwrap();
                head.last_request = Some(CognitiveCheckpointRetainedRequest {
                    request_id: request.request_id.clone(),
                    request_sha256: Sha256Digest::from_sha256_output(Sha256::digest(bytes)),
                    command: request.command,
                    predecessor_token,
                });
                current.token = token_for(head);
            }
            current.clone()
        };
        if request.command == CognitiveCheckpointCommand::PreparePublication
            && self.hold_prepare_reply.load(Ordering::SeqCst)
        {
            self.prepared.notify_one();
            self.resume_prepare.notified().await;
        }
        if request.command == CognitiveCheckpointCommand::CommitPublication
            && self.revoke_after_publication.load(Ordering::SeqCst)
        {
            self.verifier.revoked.store(true, Ordering::SeqCst);
        }
        if request.command == CognitiveCheckpointCommand::CommitPublication
            && self.hold_current_reply.load(Ordering::SeqCst)
        {
            self.published.notify_one();
            std::future::pending::<()>().await;
        }
        let mut head = current.head;
        if self.wrong_owner_reply.load(Ordering::SeqCst) {
            head.owner_agent_id = AgentId::parse("fe4d9e62-67be-4ca8-bfed-8080d473e6a9").unwrap();
        }
        Ok(serde_json::to_vec(&CognitiveCheckpointResponse {
            schema_version: 1,
            request_id: request.request_id,
            status: CognitiveCheckpointStatus::Ack,
            reason: None,
            token: Some(current.token),
            head: Some(head),
        })
        .unwrap())
    }
}

fn token_for(head: &CognitiveCheckpointHead) -> CognitiveCheckpointToken {
    CognitiveCheckpointToken {
        publisher_epoch: head.publisher_epoch,
        counter: head.counter,
        head_sha256: Sha256Digest::from_sha256_output(Sha256::digest(
            serde_json::to_vec(head).unwrap(),
        )),
    }
}

struct ManagedFixture {
    _temp: tempfile::TempDir,
    store: crate::CognitiveStore,
    writer: Arc<ProductionDurableWriter>,
    checkpoint: Arc<ProtectedCognitiveCheckpoint<ProtocolPeer>>,
    peer: Arc<ProtocolPeer>,
}

impl ManagedFixture {
    async fn new() -> Self {
        Self::in_directory(tempfile::TempDir::new().unwrap()).await
    }

    async fn in_directory(temp: tempfile::TempDir) -> Self {
        let owner = crate::cognitive_test_support::agent_id(OWNER);
        let layout = crate::cognitive_test_support::layout(&temp, &owner);
        let genesis = crate::CognitiveStore::open(&layout).await.unwrap();
        let cut = genesis.recovery_anchor().await.unwrap();
        genesis.close().await;
        let verifier = Arc::new(TestVerifier::new());
        let grant = authority(&owner, 87);
        let store = crate::CognitiveStore::open_with_recovery(
            &layout,
            crate::CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
            &grant,
            verifier.as_ref(),
        )
        .await
        .unwrap();
        let head = CognitiveCheckpointHead {
            schema_version: 1,
            owner_agent_id: owner,
            publisher_epoch: 9,
            counter: 7,
            last_mutation_sequence: 41,
            writer_binding: CognitiveCheckpointWriterBinding {
                lease_id: LEASE.to_string(),
                generation: 1,
                authority_epoch: grant.authority_epoch,
                owner_epoch: grant.owner_epoch,
                authority_grant_digest: grant.grant_digest.clone(),
                fencing_token_digest: grant.fencing_token_digest().unwrap(),
                expires_at_unix_seconds: grant.lease_expires_at_unix_seconds,
            },
            peer_lifetime: CognitiveCheckpointPeerLifetime {
                uid: 1,
                pid: 1,
                boot_id: "test-protocol-peer".to_string(),
                process_start_ticks: 1,
            },
            phase: CognitiveCheckpointPhase::Current,
            last_current: cut,
            proposal: None,
            last_request: Some(CognitiveCheckpointRetainedRequest {
                request_id: format!("{:016x}{:016x}", 9, 41),
                request_sha256: Sha256Digest::from_sha256_output(Sha256::digest(
                    b"prior fixture transition",
                )),
                command: CognitiveCheckpointCommand::CommitPublication,
                predecessor_token: CognitiveCheckpointToken {
                    publisher_epoch: 9,
                    counter: 6,
                    head_sha256: Sha256Digest::from_sha256_output(Sha256::digest(
                        b"prior fixture head",
                    )),
                },
            }),
        };
        let receipt = CognitiveCheckpointReceipt {
            token: token_for(&head),
            head,
        };
        let peer = Arc::new(ProtocolPeer {
            receipt: Mutex::new(receipt.clone()),
            commands: Mutex::new(Vec::new()),
            hold_current_reply: AtomicBool::new(false),
            hold_prepare_reply: AtomicBool::new(false),
            prepared: Notify::new(),
            resume_prepare: Notify::new(),
            wrong_owner_reply: AtomicBool::new(false),
            published: Notify::new(),
            revoke_after_publication: AtomicBool::new(false),
            verifier: verifier.clone(),
        });
        let (store, checkpoint) = store
            .bind_protected_checkpoint(peer.clone(), receipt, Duration::from_secs(2))
            .await
            .unwrap();
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store.clone(),
                grant,
                verifier,
                LEASE,
                1,
            )
            .await
            .unwrap(),
        );
        Self {
            _temp: temp,
            store,
            writer,
            checkpoint,
            peer,
        }
    }

    fn sender(&self) -> ProductionObjectiveSender<ProtectedCognitiveCheckpoint<ProtocolPeer>> {
        self.writer
            .objective_sender(self.checkpoint.clone(), Duration::from_secs(2))
            .unwrap()
    }
}

#[cfg(test)]
#[path = "cognitive_checkpoint_barrier_tests.rs"]
mod barrier_tests;

#[cfg(test)]
#[path = "cognitive_checkpoint_observation_tests.rs"]
mod observation_tests;

#[tokio::test]
async fn protected_checkpoint_invalidates_current_before_normal_owner_writes_and_can_republish() {
    let fixture = ManagedFixture::new().await;
    let mut prior_connection = fixture.store.pool.acquire().await.unwrap();
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    let current = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(current.head.phase, CognitiveCheckpointPhase::Current);
    assert!(!fixture.store.commit_gate.commit_allowed());
    // A connection checked out during the preceding Dirty interval cannot
    // commit behind the newly acknowledged Current head without a new Dirty ACK.
    assert!(
        sqlx::query("CREATE TABLE stale_dirty_permission_probe (v INTEGER)")
            .execute(&mut *prior_connection)
            .await
            .is_err()
    );
    drop(prior_connection);

    fixture
        .writer
        .admit("after-current", "test", "{}")
        .await
        .unwrap();
    let dirty = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(dirty.head.phase, CognitiveCheckpointPhase::Dirty);
    assert_eq!(dirty.head.last_current, current.head.last_current);
    let changed = fixture.store.recovery_anchor().await.unwrap();
    assert_ne!(changed, current.head.last_current);
    sender.snapshot_acknowledged(&ticket).await.unwrap();
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.last_current,
        changed
    );
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Current
    );
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(!fixture.writer.checkpoint_fenced());
    assert_eq!(
        fixture.peer.commands.lock().unwrap().as_slice(),
        &[
            CognitiveCheckpointCommand::ReadHead,
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
            CognitiveCheckpointCommand::CommitPublication,
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
            CognitiveCheckpointCommand::CommitPublication,
        ]
    );
}

#[tokio::test]
async fn protected_checkpoint_lost_current_ack_fences_waiting_and_previously_checked_out_connections()
 {
    let fixture = ManagedFixture::new().await;
    let mut prior_connection = fixture.store.pool.acquire().await.unwrap();
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let sender = fixture.sender();
    let sending = tokio::spawn(async move { sender.retain_before_send(request()).await });
    fixture.peer.published.notified().await;
    let checkout = fixture.store.pool.acquire();
    tokio::pin!(checkout);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut checkout)
            .await
            .is_err()
    );
    sending.abort();
    assert!(matches!(sending.await, Err(error) if error.is_cancelled()));
    assert!(fixture.writer.checkpoint_fenced());
    let mut later_connection = checkout.await.unwrap();
    for connection in [&mut prior_connection, &mut later_connection] {
        assert!(
            sqlx::query("CREATE TABLE checkpoint_bypass_probe (v INTEGER)")
                .execute(&mut **connection)
                .await
                .is_err()
        );
    }
    drop(prior_connection);
    drop(later_connection);
    let retained = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), retained);
    assert!(
        fixture
            .writer
            .admit("after-unknown", "test", "{}")
            .await
            .is_err()
    );
    fixture
        .peer
        .hold_current_reply
        .store(false, Ordering::SeqCst);
    let sender = fixture.sender();
    let recovered = sender.recover_pending(request()).await.unwrap();
    assert!(sender.snapshot_acknowledged(&recovered).await.is_ok());
    assert!(sender.mark_send_started(&recovered).await.is_err());
    assert!(fixture.writer.checkpoint_fenced());
}

#[tokio::test]
async fn protected_checkpoint_mismatched_dirty_ack_never_opens_commit_permission() {
    let fixture = ManagedFixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    fixture.peer.wrong_owner_reply.store(true, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .admit("wrong-host-owner", "test", "{}")
            .await
            .is_err()
    );
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(sender.snapshot(&ticket).await.is_ok());
    assert!(sender.mark_send_started(&ticket).await.is_err());
}

#[path = "cognitive_checkpoint_notes_retirement_tests.rs"]
mod notes_retirement_tests;

#[cfg(unix)]
#[path = "cognitive_checkpoint_hos2_retirement_tests.rs"]
mod hos2_retirement_tests;

#[cfg(unix)]
#[path = "cognitive_checkpoint_effect_entry_tests.rs"]
mod effect_entry_tests;

#[path = "cognitive_checkpoint_serialization_tests.rs"]
mod serialization_tests;
