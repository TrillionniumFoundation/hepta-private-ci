use std::future::Future;
use std::future::poll_fn;
use std::pin::Pin;
#[cfg(unix)]
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;

use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::time::sleep;
use tokio::time::timeout;

use super::*;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

struct Fixture {
    _temp: TempDir,
    writer: ProductionDurableWriter,
    #[cfg(unix)]
    queued: ProductionQueuedReceipt,
    claim: DurableDispatchClaim,
    #[cfg(unix)]
    revoked: Arc<AtomicBool>,
    #[cfg(unix)]
    grant_revocation_armed: Arc<AtomicBool>,
    #[cfg(unix)]
    grant_revoker: Arc<std::sync::Mutex<Option<FinalUseAuthority>>>,
}

async fn fixture(writer_lifetime_seconds: u64, claim_lifetime_ms: u64) -> Fixture {
    let temp = TempDir::new().expect("tempdir");
    let owner = agent_id(/*suffix*/ 89);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"claim clock grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        now_unix_seconds().expect("clock") + writer_lifetime_seconds,
        ProductionAuthorityToken::from_verified_bytes(b"claim clock token".to_vec())
            .expect("token"),
    )
    .expect("authority");
    let revoked = Arc::new(AtomicBool::new(/*v*/ false));
    let verifier_revoked = Arc::clone(&revoked);
    #[cfg(unix)]
    let grant_revocation_armed = Arc::new(AtomicBool::new(/*v*/ false));
    #[cfg(unix)]
    let verifier_grant_revocation_armed = Arc::clone(&grant_revocation_armed);
    #[cfg(unix)]
    let grant_revoker = Arc::new(std::sync::Mutex::<Option<FinalUseAuthority>>::default());
    #[cfg(unix)]
    let verifier_grant_revoker = Arc::clone(&grant_revoker);
    let verifier = move |_authority: &ProductionAuthorityLease, _owner: &AgentId| {
        #[cfg(unix)]
        if verifier_grant_revocation_armed.swap(/*val*/ false, Ordering::SeqCst) {
            let final_use = verifier_grant_revoker
                .lock()
                .map_err(|_| "revocation fixture lock poisoned".to_string())?
                .take()
                .ok_or_else(|| "revocation fixture was not attached".to_string())?;
            final_use
                .update_revocations(codex_hepta_contracts::FinalUseRevocations {
                    authority_epoch: 1,
                    revision: 2,
                    revoked_grant_ids: std::collections::BTreeSet::from(
                        ["entry-grant".to_string()],
                    ),
                })
                .map_err(|error| error.to_string())?;
        }
        if verifier_revoked.load(Ordering::SeqCst) {
            Err("writer revoked after final-use persistence".to_string())
        } else {
            Ok(())
        }
    };
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        Arc::new(verifier),
        "operation:clock",
        /*generation*/ 1,
    )
    .await
    .expect("writer");
    let operation = OperationIntentV1::new(
        StableId::new("operation:clock").expect("operation"),
        StableId::new(owner.as_str()).expect("owner"),
        StableId::new("target:clock").expect("destination"),
        Digest32::of_bytes(b"{}"),
        Digest32::of_bytes(b"claim clock scope"),
        Generation::new(/*value*/ 1).expect("generation"),
        /*expected_predecessor*/ None,
    )
    .expect("intent");
    let queued = writer
        .prepare_operation(operation, "claim.clock", "{}")
        .await
        .expect("prepare");
    let claim = writer
        .claim_dispatch_lease(&queued, claim_lifetime_ms)
        .await
        .expect("short live claim");
    Fixture {
        _temp: temp,
        writer,
        #[cfg(unix)]
        queued,
        claim,
        #[cfg(unix)]
        revoked,
        #[cfg(unix)]
        grant_revocation_armed,
        #[cfg(unix)]
        grant_revoker,
    }
}

// Compare every persisted claim field, including timestamps and both hashes.
type ClaimJournalRow = (
    String,
    i64,
    i64,
    i64,
    String,
    String,
    i64,
    i64,
    String,
    String,
    i64,
);

async fn claim_journal(store: &CognitiveStore) -> Vec<ClaimJournalRow> {
    sqlx::query_as(
        "SELECT operation_id, claim_sequence, attempt, owner_generation, fencing_token,
                claim_state, lease_expires_at_unix_ms, next_eligible_at_unix_ms,
                previous_sha256, claim_sha256, recorded_at_unix_ms
         FROM cognitive_operation_dispatch_claims ORDER BY operation_id, claim_sequence",
    )
    .fetch_all(&store.pool)
    .await
    .expect("complete claim journal")
}

fn observed_real_clock(
    reads: Arc<AtomicUsize>,
) -> impl FnOnce() -> Result<u64, LocalLeaseOutboxError> + Send {
    move || {
        reads.fetch_add(1, Ordering::SeqCst);
        resolve_dispatch_claim_time()
    }
}

async fn poll_while_sqlite_locked<F: Future>(mut future: Pin<&mut F>, reads: &AtomicUsize) {
    poll_fn(|context| {
        assert!(
            future.as_mut().poll(context).is_pending(),
            "held SQLite write fence must block the claim mutation"
        );
        Poll::Ready(())
    })
    .await;
    assert_eq!(
        reads.load(Ordering::SeqCst),
        0,
        "clock must not be resolved before the write fence"
    );
}

async fn wait_for_real_expiry(deadline_unix_ms: u64) {
    let before = resolve_dispatch_claim_time().expect("real clock");
    assert!(
        before < deadline_unix_ms,
        "the blocked mutation must start before its deadline"
    );
    sleep(Duration::from_millis(deadline_unix_ms - before)).await;
    assert!(resolve_dispatch_claim_time().expect("real clock") >= deadline_unix_ms);
}

#[tokio::test]
async fn renewal_waiting_for_sqlite_write_fence_cannot_revive_an_expired_dispatch_claim() {
    let fixture = fixture(
        /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 2_000,
    )
    .await;
    let store = &fixture.writer.store;
    let original = claim_journal(store).await;
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("controlled SQLite blocker");
    let reads = Arc::new(AtomicUsize::new(/*v*/ 0));
    let renewal = operation_claims::renew(
        store,
        &fixture.claim,
        observed_real_clock(Arc::clone(&reads)),
        /*lease_duration_ms*/ 60_000,
    );
    tokio::pin!(renewal);
    poll_while_sqlite_locked(renewal.as_mut(), &reads).await;
    wait_for_real_expiry(fixture.claim.lease_expires_at_unix_ms).await;
    assert_eq!(reads.load(Ordering::SeqCst), 0);
    blocker.rollback().await.expect("release SQLite fence");
    assert!(matches!(
        timeout(Duration::from_secs(/*secs*/ 10), renewal)
            .await
            .expect("blocked renewal must finish"),
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert_eq!(reads.load(Ordering::SeqCst), 1);
    assert_eq!(
        claim_journal(store).await,
        original,
        "no expired renewal may be appended"
    );
}

#[tokio::test]
async fn effect_entry_waiting_for_sqlite_write_fence_rejects_expiry_without_an_entered_row() {
    let fixture = fixture(
        /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 2_000,
    )
    .await;
    let writer = &fixture.writer;
    let request = writer
        .reconciliation_request("operation:clock", "target:clock")
        .await
        .expect("bound request");
    writer
        .lease
        .claim_dispatch(
            "operation:clock",
            &writer.authority.grant_digest,
            &request.operation_digest,
        )
        .await
        .expect("one-shot Indeterminate fence before effect entry");
    let store = &writer.store;
    let original = claim_journal(store).await;
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("controlled SQLite blocker");
    let reads = Arc::new(AtomicUsize::new(/*v*/ 0));
    let entry = operation_claims::mark_entered(
        store,
        &fixture.claim,
        observed_real_clock(Arc::clone(&reads)),
    );
    tokio::pin!(entry);
    poll_while_sqlite_locked(entry.as_mut(), &reads).await;
    wait_for_real_expiry(fixture.claim.lease_expires_at_unix_ms).await;
    assert_eq!(reads.load(Ordering::SeqCst), 0);
    blocker.rollback().await.expect("release SQLite fence");
    assert!(matches!(
        timeout(Duration::from_secs(/*secs*/ 10), entry)
            .await
            .expect("blocked entry must finish"),
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert_eq!(reads.load(Ordering::SeqCst), 1);
    assert_eq!(
        claim_journal(store).await,
        original,
        "no expired Entered row may be appended"
    );
    assert_eq!(
        writer
            .status("operation:clock")
            .await
            .expect("fail-closed status"),
        LocalOutcomeState::Indeterminate
    );
}

#[tokio::test]
async fn effect_entry_waiting_for_sqlite_write_fence_rejects_an_expired_writer_with_a_live_claim() {
    let fixture = fixture(
        /*writer_lifetime_seconds*/ 3, /*claim_lifetime_ms*/ 60_000,
    )
    .await;
    let writer = &fixture.writer;
    let request = writer
        .reconciliation_request("operation:clock", "target:clock")
        .await
        .expect("bound request");
    writer
        .lease
        .claim_dispatch(
            "operation:clock",
            &writer.authority.grant_digest,
            &request.operation_digest,
        )
        .await
        .expect("one-shot Indeterminate fence before effect entry");
    let store = &writer.store;
    let original = claim_journal(store).await;
    let blocker = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("controlled SQLite blocker");
    let reads = Arc::new(AtomicUsize::new(/*v*/ 0));
    let entry = operation_claims::mark_entered(
        store,
        &fixture.claim,
        observed_real_clock(Arc::clone(&reads)),
    );
    tokio::pin!(entry);
    poll_while_sqlite_locked(entry.as_mut(), &reads).await;
    wait_for_real_expiry(writer.authority.lease_expires_at_unix_seconds * 1_000).await;
    assert!(
        resolve_dispatch_claim_time().expect("real clock") < fixture.claim.lease_expires_at_unix_ms,
        "the operation claim must remain live after the writer expires"
    );
    assert_eq!(reads.load(Ordering::SeqCst), 0);
    blocker.rollback().await.expect("release SQLite fence");
    assert!(matches!(
        timeout(Duration::from_secs(/*secs*/ 10), entry)
            .await
            .expect("blocked entry must finish"),
        Err(LocalLeaseOutboxError::StaleFence(reason))
            if reason == "writer lease expired before dispatch claim mutation"
    ));
    assert_eq!(reads.load(Ordering::SeqCst), 1);
    assert_eq!(
        claim_journal(store).await,
        original,
        "no Entered row may be appended under an expired writer lease"
    );
}

#[cfg(unix)]
mod final_use_entry {
    use super::*;
    use codex_hepta_contracts::AuthorityClock;
    use codex_hepta_contracts::AuthorityTrustError;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SystemAuthorityClock;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use pretty_assertions::assert_eq;
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;

    enum PostPersistenceAction {
        Continue,
        WaitUntil(u64),
        Revoke(Arc<AtomicBool>),
        ArmGrantRevocation(Arc<AtomicBool>),
    }

    struct PersistenceBoundaryClock {
        reads: AtomicUsize,
        action: PostPersistenceAction,
    }

    impl AuthorityClock for PersistenceBoundaryClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            // FinalUseAuthority reads once on open, once before its claim CAS /
            // fsync, and once after that durable append before returning a token.
            if self.reads.fetch_add(1, Ordering::SeqCst) == 2 {
                match &self.action {
                    PostPersistenceAction::Continue => {}
                    PostPersistenceAction::WaitUntil(deadline) => {
                        let before = SystemAuthorityClock.now_unix_ms()?;
                        assert!(before < *deadline, "persistence must begin before expiry");
                        std::thread::sleep(Duration::from_millis(deadline - before));
                    }
                    PostPersistenceAction::Revoke(revoked) => {
                        revoked.store(/*val*/ true, Ordering::SeqCst);
                    }
                    PostPersistenceAction::ArmGrantRevocation(armed) => {
                        armed.store(/*val*/ true, Ordering::SeqCst);
                    }
                }
            }
            SystemAuthorityClock.now_unix_ms()
        }
    }

    struct EntryFixture {
        owner: Fixture,
        final_use: FinalUseAuthority,
        clock: Arc<PersistenceBoundaryClock>,
        target: Arc<EntryTarget>,
        signed: SignedFinalUseGrant,
        binding: FinalUseBinding,
        authority_directory: PathBuf,
        issuer: SigningKey,
    }

    async fn entry_fixture(owner: Fixture, action: PostPersistenceAction) -> EntryFixture {
        let authority_directory = owner._temp.path().join("entry-authority");
        std::fs::create_dir(&authority_directory).expect("authority directory");
        std::fs::set_permissions(&authority_directory, std::fs::Permissions::from_mode(0o700))
            .expect("private authority permissions");
        let issuer = SigningKey::from_bytes(&[83; 32]);
        let clock = Arc::new(PersistenceBoundaryClock {
            reads: AtomicUsize::new(/*v*/ 0),
            action,
        });
        let final_use = FinalUseAuthority::open_state_dir_with_clock(
            &authority_directory,
            "entry-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )
        .expect("real persistent final-use authority");
        let target = Arc::new(EntryTarget {
            calls: AtomicUsize::new(/*v*/ 0),
        });
        let binding = owner
            .writer
            .final_use_binding(&owner.queued, target.destination_id())
            .await
            .expect("canonical operation binding");
        let now = resolve_dispatch_claim_time().expect("clock");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "entry-owner".to_string(),
            authority_epoch: 1,
            grant_id: "entry-grant".to_string(),
            nonce: [89; 32],
            binding: binding.clone(),
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 120_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        EntryFixture {
            owner,
            final_use,
            clock,
            target,
            signed: SignedFinalUseGrant { grant, signature },
            binding,
            authority_directory,
            issuer,
        }
    }

    struct EntryTarget {
        calls: AtomicUsize,
    }

    impl ProductionOutboxTarget for EntryTarget {
        fn dispatch<'a>(
            &'a self,
            _request: ProductionDispatchRequest,
        ) -> ProductionDispatchFuture<'a> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Box::pin(async {
                ProductionTargetOutcome::Committed {
                    receipt: "actual entry receipt".to_string(),
                }
            })
        }
    }

    impl FinalUseProductionOutboxTarget for EntryTarget {
        fn destination_id(&self) -> &str {
            "target:clock"
        }
    }

    fn assert_nonce_consumed_after_reopen(mut fixture: EntryFixture) {
        assert!(fixture.clock.reads.load(Ordering::SeqCst) >= 3);
        assert!(
            resolve_dispatch_claim_time().expect("clock") < fixture.signed.grant.expires_at_unix_ms,
            "the final-use grant must remain live during owner rejection"
        );
        let head = fixture
            .final_use
            .revocation_head()
            .expect("persisted revocation head");
        drop(fixture.final_use);
        let reopened = FinalUseAuthority::open_state_dir(
            &fixture.authority_directory,
            "entry-owner".to_string(),
            fixture.issuer.verifying_key().to_bytes(),
            head,
        )
        .expect("reopen actual persisted nonce journal");
        assert_eq!(reopened.capacity().expect("capacity").used_nonces, 1);
        // A fresh signed grant ID cannot reuse the consumed nonce, including
        // when the original grant itself became revoked at the entry boundary.
        fixture.signed.grant.grant_id = "nonce-replay-proof".to_string();
        fixture.signed.signature = fixture
            .issuer
            .sign(&fixture.signed.grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        assert!(matches!(
            reopened.claim(&fixture.signed, &fixture.binding),
            Err(FinalUseError::AlreadyClaimed)
        ));
    }

    #[tokio::test]
    async fn final_use_persistence_crossing_writer_expiry_never_enters_target_and_burns_nonce() {
        let owner = fixture(
            /*writer_lifetime_seconds*/ 3, /*claim_lifetime_ms*/ 60_000,
        )
        .await;
        let deadline = owner.writer.authority.lease_expires_at_unix_seconds * 1_000;
        let fixture = entry_fixture(owner, PostPersistenceAction::WaitUntil(deadline)).await;
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            fixture.final_use.clone(),
            fixture.target.clone(),
        );
        assert!(matches!(
            dispatcher
                .dispatch(
                    &fixture.owner.writer,
                    &fixture.signed,
                    &fixture.binding,
                    fixture.owner.queued.clone(),
                )
                .await,
            Err(ProductionWriterError::AuthorityExpired { deadline: actual })
                if actual == deadline / 1_000
        ));
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 0);
        assert!(
            resolve_dispatch_claim_time().expect("clock")
                < fixture.owner.claim.lease_expires_at_unix_ms
        );
        drop(dispatcher);
        assert_nonce_consumed_after_reopen(fixture);
    }

    #[tokio::test]
    async fn final_use_persistence_crossing_dispatch_claim_expiry_rejects_before_actual_target_entry()
     {
        let owner = fixture(
            /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 2_000,
        )
        .await;
        let deadline = owner.claim.lease_expires_at_unix_ms;
        let fixture = entry_fixture(owner, PostPersistenceAction::WaitUntil(deadline)).await;
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            fixture.final_use.clone(),
            fixture.target.clone(),
        );
        assert!(matches!(
            dispatcher
                .dispatch(
                    &fixture.owner.writer,
                    &fixture.signed,
                    &fixture.binding,
                    fixture.owner.queued.clone(),
                )
                .await,
            Err(ProductionWriterError::Local(LocalLeaseOutboxError::StaleFence(reason)))
                if reason == "dispatch claim expired before target entry"
        ));
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            fixture
                .owner
                .writer
                .status("operation:clock")
                .await
                .expect("status"),
            LocalOutcomeState::Rejected
        );
        drop(dispatcher);
        assert_nonce_consumed_after_reopen(fixture);
    }

    #[tokio::test]
    async fn retained_writer_revocation_during_final_use_persistence_never_enters_target() {
        let owner = fixture(
            /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 60_000,
        )
        .await;
        let revoked = Arc::clone(&owner.revoked);
        let fixture = entry_fixture(owner, PostPersistenceAction::Revoke(revoked)).await;
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            fixture.final_use.clone(),
            fixture.target.clone(),
        );
        assert!(matches!(
            dispatcher
                .dispatch(
                    &fixture.owner.writer,
                    &fixture.signed,
                    &fixture.binding,
                    fixture.owner.queued.clone(),
                )
                .await,
            Err(ProductionWriterError::AuthorityRejected(reason))
                if reason == "writer revoked after final-use persistence"
        ));
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 0);
        drop(dispatcher);
        assert_nonce_consumed_after_reopen(fixture);
    }

    #[tokio::test]
    async fn live_writer_and_dispatch_claim_enter_actual_target_once_after_final_use_persistence() {
        let owner = fixture(
            /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 60_000,
        )
        .await;
        let fixture = entry_fixture(owner, PostPersistenceAction::Continue).await;
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            fixture.final_use.clone(),
            fixture.target.clone(),
        );
        let result = dispatcher
            .dispatch(
                &fixture.owner.writer,
                &fixture.signed,
                &fixture.binding,
                fixture.owner.queued.clone(),
            )
            .await
            .expect("live target entry");
        assert_eq!(result.state, LocalOutcomeState::Committed);
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 1);
        drop(dispatcher);
        assert_nonce_consumed_after_reopen(fixture);
    }

    #[tokio::test]
    async fn retained_verifier_revoking_final_use_after_claim_is_checked_before_actual_target_entry()
     {
        let owner = fixture(
            /*writer_lifetime_seconds*/ 3_600, /*claim_lifetime_ms*/ 60_000,
        )
        .await;
        let armed = Arc::clone(&owner.grant_revocation_armed);
        let fixture = entry_fixture(owner, PostPersistenceAction::ArmGrantRevocation(armed)).await;
        *fixture
            .owner
            .grant_revoker
            .lock()
            .expect("revocation fixture") = Some(fixture.final_use.clone());
        let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
            fixture.final_use.clone(),
            fixture.target.clone(),
        );
        assert!(matches!(
            dispatcher
                .dispatch(
                    &fixture.owner.writer,
                    &fixture.signed,
                    &fixture.binding,
                    fixture.owner.queued.clone(),
                )
                .await,
            Err(ProductionWriterError::FinalUse(FinalUseError::Revoked))
        ));
        assert_eq!(fixture.target.calls.load(Ordering::SeqCst), 0);
        assert!(!fixture.owner.grant_revocation_armed.load(Ordering::SeqCst));
        assert_eq!(fixture.clock.reads.load(Ordering::SeqCst), 4);
        assert!(
            resolve_dispatch_claim_time().expect("clock")
                < fixture.owner.claim.lease_expires_at_unix_ms
        );
        fixture
            .owner
            .writer
            .authority
            .validate_for_agent(fixture.owner.writer.owner_agent_id())
            .expect("owner remains live");
        assert_eq!(
            fixture
                .owner
                .writer
                .status("operation:clock")
                .await
                .expect("status"),
            LocalOutcomeState::Rejected
        );
        drop(dispatcher);
        assert_nonce_consumed_after_reopen(fixture);
    }
}
