//! Original SQLite/FinalUse path with an explicit test-only checkpoint peer.
//! These fixtures are not an independent production Root or native device.

use super::*;
use crate::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
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

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(1_000_000)
    }
}

struct Target {
    peer: Arc<ProtocolPeer>,
    store: CognitiveStore,
    destination: String,
    receipt: String,
    effects: AtomicUsize,
    retirements: AtomicUsize,
    lose_effect_reply: bool,
    lose_terminal_current_reply: bool,
}
impl ProductionOutboxTarget for Target {
    fn dispatch<'a>(&'a self, _: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            let current = self.peer.receipt.lock().unwrap().clone();
            assert_eq!(current.head.phase, CognitiveCheckpointPhase::Current);
            assert_eq!(
                current.head.last_current,
                self.store.recovery_anchor().await.unwrap()
            );
            self.effects.fetch_add(1, Ordering::SeqCst);
            self.peer
                .hold_current_reply
                .store(self.lose_terminal_current_reply, Ordering::SeqCst);
            if self.lose_effect_reply {
                ProductionTargetOutcome::Indeterminate {
                    reason: "fixture applied but withheld reply".into(),
                }
            } else {
                ProductionTargetOutcome::Committed {
                    receipt: self.receipt.clone(),
                }
            }
        })
    }
}
impl FinalUseProductionOutboxTarget for Target {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        _: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            ProductionTerminalObservation::Applied {
                receipt: self.receipt.clone(),
            }
        })
    }
    fn retire_notes_receipt(&self, _: &NotesRetirementPermit) -> Result<(), String> {
        assert_eq!(
            self.peer.receipt.lock().unwrap().head.phase,
            CognitiveCheckpointPhase::Current
        );
        self.retirements.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

enum Failure {
    EffectReply,
    EntryPublication,
    TerminalPublication,
    ClaimRejection,
}

async fn exercise(failure: Failure) {
    let fixture = ManagedFixture::new().await;
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-recovery-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap().to_owned();
    let value: serde_json::Value = serde_json::from_str(&payload).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(value["target"].clone()).unwrap();
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(fixture.writer.owner_agent_id().as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let queued = fixture
        .writer
        .prepare_operation(intent, NOTES_REPLACE_TOPIC_V1, payload)
        .await
        .unwrap();
    let operation = queued.occurrence_key.clone();
    let binding = fixture
        .writer
        .final_use_binding(&queued, &identity.destination_id())
        .await
        .unwrap();
    let target = Arc::new(Target {
        peer: fixture.peer.clone(),
        store: fixture.store.clone(),
        destination: identity.destination_id(),
        receipt: golden["application_response_utf8"].as_str().unwrap().into(),
        effects: AtomicUsize::new(0),
        retirements: AtomicUsize::new(0),
        lose_effect_reply: matches!(failure, Failure::EffectReply),
        lose_terminal_current_reply: matches!(failure, Failure::TerminalPublication),
    });
    let dir = fixture._temp.path().join("final-use-fixture");
    std::fs::create_dir(&dir).unwrap();
    std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    let key = SigningKey::from_bytes(&[85; 32]);
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        &dir,
        "current-fixture".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 71,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        Arc::new(Clock),
    )
    .unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "current-fixture".into(),
        authority_epoch: 71,
        grant_id: "current-boundary".into(),
        nonce: [86; 32],
        binding: binding.clone(),
        not_before_unix_ms: 999_000,
        expires_at_unix_ms: 1_060_000,
    };
    let mut signature = key
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    if matches!(failure, Failure::ClaimRejection) {
        signature[0] ^= 1;
    }
    let signed = SignedFinalUseGrant { grant, signature };
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(authority, target.clone());
    fixture.peer.hold_current_reply.store(
        matches!(failure, Failure::EntryPublication),
        Ordering::SeqCst,
    );
    let result = dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued)
        .await;
    match failure {
        Failure::ClaimRejection => {
            assert!(matches!(result, Err(ProductionWriterError::FinalUse(_))));
            assert_eq!(
                fixture.writer.status(&operation).await.unwrap(),
                LocalOutcomeState::Rejected
            );
            assert_eq!(target.effects.load(Ordering::SeqCst), 0);
            assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
            assert_eq!(
                fixture.peer.receipt.lock().unwrap().head.phase,
                CognitiveCheckpointPhase::Current
            );
            let observed = fixture.store.recovery_anchor().await.unwrap();
            assert_eq!(
                fixture.peer.receipt.lock().unwrap().head.last_current,
                observed
            );
            assert!(!fixture.writer.checkpoint_fenced());
        }
        Failure::EffectReply => {
            assert_eq!(result.unwrap().state, LocalOutcomeState::Indeterminate);
            let observed = fixture.store.recovery_anchor().await.unwrap();
            assert_eq!(
                fixture.peer.receipt.lock().unwrap().head.last_current,
                observed
            );
            assert_eq!(
                fixture
                    .writer
                    .reconcile_target_batch(target.as_ref(), 1)
                    .await
                    .unwrap(),
                1
            );
            assert_eq!(
                fixture.writer.status(&operation).await.unwrap(),
                LocalOutcomeState::Committed
            );
            assert_eq!(target.effects.load(Ordering::SeqCst), 1);
            assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
            assert_eq!(
                fixture.peer.receipt.lock().unwrap().head.phase,
                CognitiveCheckpointPhase::Current
            );
            let observed = fixture.store.recovery_anchor().await.unwrap();
            assert_eq!(
                fixture.peer.receipt.lock().unwrap().head.last_current,
                observed
            );
        }
        Failure::EntryPublication | Failure::TerminalPublication => {
            assert!(result.is_err());
            assert!(fixture.writer.checkpoint_fenced());
            assert_eq!(
                target.effects.load(Ordering::SeqCst),
                usize::from(matches!(failure, Failure::TerminalPublication))
            );
            assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
            let expected = if matches!(failure, Failure::TerminalPublication) {
                "reconcile_committed"
            } else {
                "indeterminate"
            };
            let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE occurrence_key = ? AND event_kind = ?")
                .bind(&operation).bind(expected).fetch_one(fixture.store.observation_pool()).await.unwrap();
            assert_eq!(count, 1);
            // A late independent Current read never reopens the original pool.
            fixture
                .peer
                .hold_current_reply
                .store(false, Ordering::SeqCst);
            assert!(fixture.writer.acknowledge_external_current().await.is_err());
            assert!(
                fixture
                    .writer
                    .admit("after-unknown", "test", "{}")
                    .await
                    .is_err()
            );
        }
    }
}

#[tokio::test]
async fn lost_effect_reply_observes_then_publishes_terminal_before_receipt_retirement() {
    exercise(Failure::EffectReply).await;
}
#[tokio::test]
async fn uncertain_entry_current_never_enters_effect_and_permanently_fences_owner() {
    exercise(Failure::EntryPublication).await;
}
#[tokio::test]
async fn uncertain_terminal_current_retains_sqlite_result_but_never_retires_receipt() {
    exercise(Failure::TerminalPublication).await;
}

#[tokio::test]
async fn exact_final_use_rejection_publishes_original_terminal_without_entering_effect() {
    exercise(Failure::ClaimRejection).await;
}
