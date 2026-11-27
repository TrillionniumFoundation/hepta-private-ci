//! Original FinalUse + Notes adapter with explicit issuer, channel and Root peer
//! fixtures. This does not qualify an application process or production issuer.

use super::*;
use crate::LocalOutcomeState;
use crate::NotesPrivateChannel;
use crate::NotesTargetIdentity;
use crate::ProductionFinalUseOutboxDispatcher;
use crate::ProductionNotesTarget;
use crate::ProductionQueuedReceipt;
use crate::ProductionWriterError;
use crate::notes_operation_intent;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;

struct EntryClock {
    reads: AtomicUsize,
    expires_on_read: AtomicUsize,
    stall_once: AtomicBool,
    stalled: AtomicBool,
}
impl AuthorityClock for EntryClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if self.stall_once.swap(false, Ordering::SeqCst) {
            self.stalled.store(true, Ordering::SeqCst);
            // Explicit fixture delay in original FinalUse, after the real
            // operation claim was entered. The operation clock is unmodified.
            std::thread::sleep(Duration::from_secs(3));
        }
        let read = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        Ok(if read >= self.expires_on_read.load(Ordering::SeqCst) {
            1_060_000
        } else {
            1_000_000
        })
    }
}
struct Channel {
    request: Vec<u8>,
    response: Vec<u8>,
    calls: AtomicUsize,
    peer: Arc<ProtocolPeer>,
    entry_head: Mutex<Option<CognitiveCheckpointReceipt>>,
    entered: Notify,
    release: Mutex<Option<std::sync::mpsc::Receiver<()>>>,
}
impl NotesPrivateChannel for Channel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        assert_eq!(request, self.request);
        self.calls.fetch_add(1, Ordering::SeqCst);
        *self.entry_head.lock().unwrap() = Some(self.peer.receipt.lock().unwrap().clone());
        self.entered.notify_one();
        if let Some(release) = self.release.lock().unwrap().as_ref() {
            release.recv_timeout(Duration::from_secs(5)).unwrap();
        }
        Ok(self.response.clone())
    }
    fn invalidate(&self) {}
}
struct PreparedEntry {
    queued: ProductionQueuedReceipt,
    binding: FinalUseBinding,
    signed: SignedFinalUseGrant,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    channel: Arc<Channel>,
    clock: Arc<EntryClock>,
}
async fn prepared_entry(fixture: &ManagedFixture) -> PreparedEntry {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap().to_string();
    let request: serde_json::Value = serde_json::from_str(&payload).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone()).unwrap();
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(fixture.writer.owner_agent_id().as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let queued = fixture
        .writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await
        .unwrap();
    let binding = fixture
        .writer
        .final_use_binding(&queued, &identity.destination_id())
        .await
        .unwrap();
    let channel = Arc::new(Channel {
        request: payload.into_bytes(),
        response: golden["application_response_utf8"]
            .as_str()
            .unwrap()
            .as_bytes()
            .to_vec(),
        calls: AtomicUsize::new(0),
        peer: fixture.peer.clone(),
        entry_head: Mutex::new(None),
        entered: Notify::new(),
        release: Mutex::new(None),
    });
    let target = Arc::new(ProductionNotesTarget::new(identity, channel.clone()).unwrap());
    let authority_dir = fixture._temp.path().join("effect-final-use");
    std::fs::create_dir(&authority_dir).unwrap();
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[87; 32]);
    let clock = Arc::new(EntryClock {
        reads: AtomicUsize::new(0),
        expires_on_read: AtomicUsize::new(usize::MAX),
        stall_once: AtomicBool::new(false),
        stalled: AtomicBool::new(false),
    });
    let final_use = FinalUseAuthority::open_state_dir_with_clock(
        &authority_dir,
        "effect-entry-fixture".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 71,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        clock.clone(),
    )
    .unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "effect-entry-fixture".to_string(),
        authority_epoch: 71,
        grant_id: "effect-entry-test-grant".to_string(),
        nonce: [88; 32],
        binding: binding.clone(),
        not_before_unix_ms: 999_000,
        expires_at_unix_ms: 1_060_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    PreparedEntry {
        queued,
        binding,
        signed: SignedFinalUseGrant { grant, signature },
        dispatcher: ProductionFinalUseOutboxDispatcher::attach(final_use, target),
        channel,
        clock,
    }
}

#[tokio::test]
async fn managed_effect_entry_never_dispatches_before_bound_entered_cut_ack() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let operation = entry.queued.occurrence_key.clone();
    let result = entry
        .dispatcher
        .dispatch(&fixture.writer, &entry.signed, &entry.binding, entry.queued)
        .await;
    assert_eq!(
        entry.channel.calls.load(Ordering::SeqCst),
        0,
        "the actual synchronous Notes adapter cannot enter while its original entered claim has no independent Current acknowledgement"
    );
    assert!(result.is_err());
    assert!(fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        crate::LocalOutcomeState::Indeterminate
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn managed_effect_entry_holds_exact_entered_cut_through_synchronous_channel_entry() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    let channel = entry.channel.clone();
    let (release, receive) = std::sync::mpsc::channel();
    *channel.release.lock().unwrap() = Some(receive);
    // Acquire the original writer connection before entry. A zero-timeout
    // BEGIN below must observe an actual SQLite lock, not scheduler delay.
    let mut lock_competitor = fixture.store.pool.acquire().await.unwrap();
    lock_competitor.close_on_drop();
    sqlx::query("PRAGMA busy_timeout=0")
        .execute(&mut *lock_competitor)
        .await
        .unwrap();
    let writer = fixture.writer.clone();
    let dispatching = tokio::spawn(async move {
        entry
            .dispatcher
            .dispatch(&writer, &entry.signed, &entry.binding, entry.queued)
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), channel.entered.notified())
        .await
        .unwrap();
    let acknowledged = channel.entry_head.lock().unwrap().clone().unwrap();
    assert_eq!(acknowledged.head.phase, CognitiveCheckpointPhase::Current);
    // A WAL read observes the same committed cut while the entry barrier holds
    // BEGIN IMMEDIATE. Taking a second writer lock here would self-deadlock.
    let mut observation = fixture.store.observation_pool().begin().await.unwrap();
    let cut = crate::cognitive_store::capture_recovery_anchor(
        &mut observation,
        fixture.writer.owner_agent_id(),
    )
    .await
    .unwrap();
    assert_eq!(acknowledged.head.last_current, cut);
    let claim_state: String = sqlx::query_scalar("SELECT claim_state FROM cognitive_operation_dispatch_claims ORDER BY claim_sequence DESC LIMIT 1")
        .fetch_one(&mut *observation).await.unwrap();
    assert_eq!(claim_state, "entered");
    observation.rollback().await.unwrap();
    let error = sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *lock_competitor)
        .await
        .unwrap_err();
    assert_eq!(
        error.as_database_error().unwrap().code().as_deref(),
        Some("5"),
        "synchronous Notes entry must still own the physical SQLite barrier"
    );
    let writer = fixture.writer.clone();
    let mut competitor = tokio::spawn(async move {
        writer
            .admit("effect-entry-competitor", "fixture", "{}")
            .await
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(100), &mut competitor)
            .await
            .is_err()
    );
    release.send(()).unwrap();
    let receipt = tokio::time::timeout(Duration::from_secs(5), dispatching)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(receipt.state, LocalOutcomeState::Committed);
    let admission = tokio::time::timeout(Duration::from_secs(5), competitor)
        .await
        .unwrap()
        .unwrap();
    if let Err(error) = admission {
        // A connection checked out before another Current publication can
        // lose Dirty commit permission. This is an explicit rolled-back
        // SQLite commit, not evidence of an admitted or replayable effect.
        assert!(
            matches!(
                &error,
                ProductionWriterError::Local(crate::LocalLeaseOutboxError::Store(
                    crate::CognitiveStoreError::Unavailable(reason)
                )) if reason.contains("(code: 531)")
            ),
            "unexpected competing admission failure: {error:?}"
        );
        let retained: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM cognitive_local_events WHERE occurrence_key = ?",
        )
        .bind("effect-entry-competitor")
        .fetch_one(fixture.store.observation_pool())
        .await
        .unwrap();
        assert_eq!(retained, 0);
        assert!(!fixture.store.commit_gate.is_fenced());
        fixture
            .writer
            .admit("effect-entry-competitor", "fixture", "{}")
            .await
            .unwrap();
    }
    assert_eq!(
        fixture
            .writer
            .status("effect-entry-competitor")
            .await
            .unwrap(),
        LocalOutcomeState::Queued
    );
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *lock_competitor)
        .await
        .unwrap();
    sqlx::query("ROLLBACK")
        .execute(&mut *lock_competitor)
        .await
        .unwrap();
    assert_eq!(channel.calls.load(Ordering::SeqCst), 1);
    assert!(!fixture.store.commit_gate.is_fenced());
}

#[tokio::test]
async fn managed_effect_entry_cancelled_publication_never_replays_or_mints_rejection_proof() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    let channel = entry.channel.clone();
    let retained_queued = entry.queued.clone();
    let writer = fixture.writer.clone();
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let dispatching = tokio::spawn(async move {
        entry
            .dispatcher
            .dispatch(&writer, &entry.signed, &entry.binding, entry.queued)
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), fixture.peer.published.notified())
        .await
        .unwrap();
    dispatching.abort();
    assert!(dispatching.await.unwrap_err().is_cancelled());
    assert_eq!(channel.calls.load(Ordering::SeqCst), 0);
    assert!(fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture
            .writer
            .status(&retained_queued.occurrence_key)
            .await
            .unwrap(),
        LocalOutcomeState::Indeterminate
    );
    let proofs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_pre_boundary_rejections")
            .fetch_one(fixture.store.observation_pool())
            .await
            .unwrap();
    assert_eq!(proofs, 0);
    assert!(
        fixture
            .writer
            .claim_dispatch_lease(&retained_queued, 2_000)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn managed_effect_entry_revoked_after_current_ack_never_calls_channel() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    fixture
        .peer
        .revoke_after_publication
        .store(true, Ordering::SeqCst);
    let result = entry
        .dispatcher
        .dispatch(&fixture.writer, &entry.signed, &entry.binding, entry.queued)
        .await;
    assert!(matches!(
        result,
        Err(ProductionWriterError::AuthorityRejected(_))
    ));
    assert_eq!(entry.channel.calls.load(Ordering::SeqCst), 0);
    assert!(fixture.store.commit_gate.is_fenced());
    let state: String = sqlx::query_scalar(
        "SELECT event_kind FROM cognitive_local_events ORDER BY event_sequence DESC LIMIT 1",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    assert_eq!(state, "indeterminate");
}

#[tokio::test]
async fn managed_effect_entry_known_final_use_rejections_release_lock_before_original_settlement() {
    // The first clock read rejects claim; the third rejects verified use after
    // claim persisted. Both are original FinalUse pre-entry rejections.
    for expires_on_read in [1, 3] {
        let fixture = ManagedFixture::new().await;
        let entry = prepared_entry(&fixture).await;
        let operation = entry.queued.occurrence_key.clone();
        entry.clock.reads.store(0, Ordering::SeqCst);
        entry
            .clock
            .expires_on_read
            .store(expires_on_read, Ordering::SeqCst);
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            entry
                .dispatcher
                .dispatch(&fixture.writer, &entry.signed, &entry.binding, entry.queued),
        )
        .await
        .unwrap();
        assert!(matches!(result, Err(ProductionWriterError::FinalUse(_))));
        assert_eq!(entry.channel.calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            fixture.writer.status(&operation).await.unwrap(),
            LocalOutcomeState::Rejected
        );
        assert!(!fixture.store.commit_gate.is_fenced());
    }
}

#[tokio::test]
async fn managed_effect_entry_rechecks_real_claim_expiry_after_synchronous_final_use_cost() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    let operation = entry.queued.occurrence_key.clone();
    let claim = fixture
        .writer
        .claim_dispatch_lease(&entry.queued, 2_000)
        .await
        .unwrap();
    entry.clock.stall_once.store(true, Ordering::SeqCst);
    let result = entry
        .dispatcher
        .dispatch(&fixture.writer, &entry.signed, &entry.binding, entry.queued)
        .await;
    assert!(
        entry.clock.stalled.load(Ordering::SeqCst),
        "the original FinalUse boundary was reached before testing its synchronous delay"
    );
    let actual_now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis();
    assert!(actual_now >= u128::from(claim.lease_expires_at_unix_ms));
    assert!(matches!(result, Err(ProductionWriterError::StaleReceipt)));
    assert_eq!(entry.channel.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        LocalOutcomeState::Indeterminate
    );
    assert!(fixture.store.commit_gate.is_fenced());
    let proofs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_operation_pre_boundary_rejections")
            .fetch_one(fixture.store.observation_pool())
            .await
            .unwrap();
    assert_eq!(proofs, 0);
}

#[tokio::test]
async fn managed_effect_entry_revalidates_original_claim_chain_and_current_dispatch_event() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    let claim = fixture
        .writer
        .claim_dispatch_lease(&entry.queued, 10_000)
        .await
        .unwrap();
    let head = fixture
        .store
        .inspect_local_lease_head(LEASE)
        .await
        .unwrap()
        .head
        .unwrap();
    let authority = fixture.writer.authority();
    let lease = fixture
        .store
        .reopen_host_bound_lease(
            head,
            authority.authority_epoch,
            authority.owner_epoch,
            authority.lease_expires_at_unix_seconds,
        )
        .await
        .unwrap();
    let digest = Sha256Digest::from_sha256_output(entry.binding.request_sha256.into());
    let dispatched = lease
        .claim_dispatch(&claim.operation_id, &authority.grant_digest, &digest)
        .await
        .unwrap();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let entered = crate::operation_claims::mark_entered(&fixture.store, &claim, now)
        .await
        .unwrap();
    let mut transaction = fixture
        .store
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    crate::operation_claims::require_entered_transaction(
        &mut transaction,
        &fixture.store,
        &entered,
    )
    .await
    .unwrap();
    lease
        .require_dispatch_entry_transaction(
            &mut transaction,
            &claim.operation_id,
            &dispatched.event_id,
            &digest,
        )
        .await
        .unwrap();
    let mut different = entered.clone();
    different.lease_expires_at_unix_ms += 1;
    assert!(
        crate::operation_claims::require_entered_transaction(
            &mut transaction,
            &fixture.store,
            &different
        )
        .await
        .is_err()
    );
    transaction.rollback().await.unwrap();

    // Original observation can append another indeterminate event without
    // altering the Entered claim. It must invalidate this exact entry event.
    fixture
        .writer
        .reconcile(
            &claim.operation_id,
            crate::LocalReconcileOutcome::StillIndeterminate,
        )
        .await
        .unwrap();
    let mut transaction = fixture
        .store
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    crate::operation_claims::require_entered_transaction(
        &mut transaction,
        &fixture.store,
        &entered,
    )
    .await
    .unwrap();
    assert!(
        lease
            .require_dispatch_entry_transaction(
                &mut transaction,
                &claim.operation_id,
                &dispatched.event_id,
                &digest
            )
            .await
            .is_err()
    );
    transaction.rollback().await.unwrap();

    // Explicit corrupt-storage fixture: changing an earlier immutable claim
    // while leaving the complete latest receipt unchanged must be detected.
    sqlx::query("DROP TRIGGER cognitive_operation_dispatch_claims_no_update")
        .execute(&fixture.store.pool)
        .await
        .unwrap();
    sqlx::query("UPDATE cognitive_operation_dispatch_claims SET lease_expires_at_unix_ms = lease_expires_at_unix_ms + 1 WHERE claim_sequence = 1")
        .execute(&fixture.store.pool).await.unwrap();
    let mut transaction = fixture
        .store
        .observation_pool()
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    assert!(
        crate::operation_claims::require_entered_transaction(
            &mut transaction,
            &fixture.store,
            &entered
        )
        .await
        .is_err()
    );
    transaction.rollback().await.unwrap();
    assert_eq!(entry.channel.calls.load(Ordering::SeqCst), 0);
}
