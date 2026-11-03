use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use tempfile::TempDir;

use super::*;
use crate::CognitiveStore;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;

// All authority material and permissive guards below are isolated fixtures.
// Product composition supplies its existing external grant provider instead.
struct FixtureVerifier(Arc<AtomicBool>);

impl ProductionAuthorityVerifier for FixtureVerifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        if self.0.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err("fixture owner revoked".to_string())
        }
    }
}

struct FixtureCurrentness {
    allowed: bool,
    entered: AtomicUsize,
}

impl ProductionEntryCurrentness for FixtureCurrentness {
    fn enter(
        &self,
        _request: &ProductionDispatchRequest,
        enter: &mut dyn FnMut() -> std::result::Result<(), ProductionWriterError>,
    ) -> Result<Box<dyn Send>, ProductionWriterError> {
        if !self.allowed {
            return Err(ProductionWriterError::AuthorityRejected(
                "fixture turn cancelled".to_string(),
            ));
        }
        enter()?;
        self.entered.fetch_add(1, Ordering::SeqCst);
        Ok(Box::new(()))
    }
}

struct Fixture {
    _temp: TempDir,
    writer: ProductionDurableWriter,
    live: Arc<AtomicBool>,
    final_use: FinalUseAuthority,
    issuer: SigningKey,
}

type FixtureResult<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

impl Fixture {
    async fn new() -> FixtureResult<Self> {
        let temp = TempDir::new()?;
        let fleet_root = temp.path().join("fleet");
        std::fs::create_dir(&fleet_root)?;
        let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize()?)
            ?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cee")
            ?;
        let store = CognitiveStore::open(&fleet.layout().agent(&agent))
            .await
            ?;
        let authority = ProductionAuthorityLease::from_verified_parts(
            agent,
            Sha256Digest::for_bytes(b"fixture effect-entry authority"),
            /*authority_epoch*/ 9,
            /*owner_epoch*/ 4,
            super::super::now_unix_seconds()? + 3600,
            ProductionAuthorityToken::from_verified_bytes(b"fixture-token".to_vec())
                ?,
        )
        ?;
        let live = Arc::new(AtomicBool::new(true));
        let writer = ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            Arc::new(FixtureVerifier(Arc::clone(&live))),
            "lease:fixture:effect-entry",
            /*generation*/ 1,
        )
        .await
        ?;
        let directory = temp.path().join("final-use");
        std::fs::create_dir(&directory)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
                ?;
        }
        let issuer = SigningKey::from_bytes(&[31; 32]);
        let final_use = FinalUseAuthority::open_state_dir(
            &directory,
            "fixture-issuer".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 17,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        ?;
        Ok(Self {
            _temp: temp,
            writer,
            live,
            final_use,
            issuer,
        })
    }

    async fn queued(&self, operation_id: &str) -> FixtureResult<(ProductionQueuedReceipt, FinalUseBinding)> {
        let payload = r#"{"request":"fixture exact original bytes"}"#;
        let operation = OperationIntentV1::new(
            StableId::new(operation_id)?,
            StableId::new(self.writer.owner_agent_id().as_str())?,
            StableId::new("destination:fixture:model")?,
            Digest32::of_bytes(payload.as_bytes()),
            Digest32::of_bytes(b"fixture scope"),
            Generation::new(1)?,
            /*expected_predecessor*/ None,
        )
        ?;
        let queued = self
            .writer
            .prepare_operation(operation, "native.model", payload)
            .await
            ?;
        let binding = self
            .writer
            .final_use_binding(&queued, "destination:fixture:model")
            .await
            ?;
        Ok((queued, binding))
    }

    fn grant(&self, binding: &FinalUseBinding, id: &str) -> FixtureResult<SignedFinalUseGrant> {
        let now = now_unix_ms()?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "fixture-issuer".to_string(),
            authority_epoch: 17,
            grant_id: id.to_string(),
            nonce: Sha256::digest(id.as_bytes()).into(),
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = self
            .issuer
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }
}

#[tokio::test]
async fn dropped_handoff_cannot_authorize_a_second_entry() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:drop").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:drop:first").expect("original grant fixture");
    let (entry, observation) = fixture
        .writer
        .begin_effect_entry(
            &fixture.final_use,
            &signed,
            &binding,
            "destination:fixture:model",
            queued.clone(),
        )
        .await
        .expect("first entry");
    assert_eq!(entry.request().occurrence_key, queued.occurrence_key);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    drop(entry);
    drop(observation);
    let second_grant = fixture.grant(&binding, "grant:drop:second").expect("original grant fixture");
    assert!(
        fixture
            .writer
            .begin_effect_entry(
                &fixture.final_use,
                &second_grant,
                &binding,
                "destination:fixture:model",
                queued.clone(),
            )
            .await
            .is_err()
    );
    assert_eq!(
        fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
}

#[tokio::test]
async fn owner_revocation_after_async_revalidation_blocks_final_entry() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:revoked").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:revoked").expect("original grant fixture");
    let (entry, observation) = fixture
        .writer
        .begin_effect_entry(
            &fixture.final_use,
            &signed,
            &binding,
            "destination:fixture:model",
            queued,
        )
        .await
        .expect("prepared");
    let ready = entry.revalidate()
        .await
        .expect("revalidated");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    fixture.live.store(false, Ordering::SeqCst);
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::AuthorityRejected(_))));
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    assert!(!observation.started());
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
}

#[tokio::test]
async fn host_cancellation_blocks_entry_without_making_it_retryable() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:cancelled").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:cancelled").expect("original grant fixture");
    let (entry, observation) = fixture
        .writer
        .begin_effect_entry(
            &fixture.final_use,
            &signed,
            &binding,
            "destination:fixture:model",
            queued.clone(),
        )
        .await
        .expect("prepared");
    let ready = entry.revalidate()
        .await
        .expect("revalidated");
    let gate = FixtureCurrentness { allowed: false, entered: AtomicUsize::new(0) };
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::AuthorityRejected(_))));
    assert_eq!(
        fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate
    );
    assert!(!observation.started());
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
}

#[tokio::test]
async fn final_use_revocation_after_preparation_prevents_physical_entry() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:final-revoked").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:final-revoked").expect("original grant fixture");
    let (entry, observation) = fixture
        .writer
        .begin_effect_entry(
            &fixture.final_use,
            &signed,
            &binding,
            "destination:fixture:model",
            queued,
        )
        .await
        .expect("prepared");
    let ready = entry.revalidate()
        .await
        .expect("revalidated");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    fixture.final_use.update_revocations(FinalUseRevocations {
        authority_epoch: 17,
        revision: 2,
        revoked_grant_ids: BTreeSet::from(["grant:final-revoked".to_string()]),
    }).expect("revocation");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::FinalUse(FinalUseError::Revoked))));
    assert!(!observation.started());
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
}

#[tokio::test]
async fn invalid_grant_at_final_entry_keeps_original_operation_indeterminate() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:invalid-final-grant")
        .await.expect("original operation fixture");
    let mut signed = fixture.grant(&binding, "grant:invalid-final-grant")
        .expect("original grant fixture");
    signed.signature = vec![0; 64];
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("original operation is claimed before final grant verification");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    let ready = entry.revalidate().await.expect("original owner is current");
    assert!(matches!(ready.enter(&gate),
        Err(ProductionWriterError::FinalUse(FinalUseError::InvalidSignature))));
    assert!(!observation.started());
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate);
    drop(observation);

    let replacement = fixture.grant(&binding, "grant:invalid-final-grant:replacement")
        .expect("replacement grant fixture");
    assert!(fixture.writer.begin_effect_entry(
        &fixture.final_use, &replacement, &binding, "destination:fixture:model", queued.clone(),
    ).await.is_err(), "a fresh grant cannot retry the already claimed original operation");
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
}

#[tokio::test]
async fn repeated_owner_callback_cannot_claim_or_enter_the_handoff_twice() {
    struct RepeatedCurrentness {
        callbacks: AtomicUsize,
    }
    impl ProductionEntryCurrentness for RepeatedCurrentness {
        fn enter(
            &self,
            _request: &ProductionDispatchRequest,
            enter: &mut dyn FnMut() -> Result<(), ProductionWriterError>,
        ) -> Result<Box<dyn Send>, ProductionWriterError> {
            self.callbacks.fetch_add(1, Ordering::SeqCst);
            enter()?;
            self.callbacks.fetch_add(1, Ordering::SeqCst);
            enter()?;
            Ok(Box::new(()))
        }
    }

    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:repeated-callback")
        .await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:repeated-callback")
        .expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("original handoff");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    let gate = RepeatedCurrentness { callbacks: AtomicUsize::new(0) };
    let ready = entry.revalidate().await.expect("original owner is current");
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::Invalid(reason))
        if reason == "entry callback was invoked twice"));
    assert_eq!(gate.callbacks.load(Ordering::SeqCst), 2);
    assert!(observation.started(), "the first callback consumed the one handoff");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 1);
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate);
}

#[tokio::test]
async fn resolver_preserves_the_original_receipt_and_never_admits_missing_operations() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, _) = fixture.queued("operation:resolve").await.expect("original operation fixture");
    let recovered = fixture.writer.resolve_queued_operation(
        &queued.occurrence_key, "destination:fixture:model",
    ).await.expect("original receipt");
    assert_eq!(recovered.event_id, queued.event_id);
    assert_eq!(recovered.outbox_id, queued.outbox_id);
    assert_eq!(recovered.payload_json, queued.payload_json);
    assert!(fixture.writer.resolve_queued_operation(
        "operation:missing", "destination:fixture:model",
    ).await.is_err());
    assert!(fixture.writer.resolve_queued_operation(
        &queued.occurrence_key, "destination:foreign",
    ).await.is_err());
    let rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox")
        .fetch_one(&fixture.writer.store.pool).await.expect("outbox count");
    assert_eq!(rows, 1);
}

#[tokio::test]
async fn dropped_observation_closes_a_prepared_entry_without_resending() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:observation-drop").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:observation-drop").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let ready = entry.revalidate().await.expect("revalidated");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    drop(observation);
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::StaleReceipt)));
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    // FinalUse may already be consumed when the paired observation closes.
    // Preserve that conservative loss without authorizing a physical entry.
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 1);
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Indeterminate);
}

#[tokio::test]
async fn terminal_observation_settles_the_original_claim_and_outbox_once() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:terminal").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:terminal").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    let entered = entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry");
    assert!(observation.started());
    assert_eq!(gate.entered.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 1);
    drop(entered);
    let receipt = fixture.writer.settle_effect_entry(
        observation, super::super::ProductionTargetOutcome::Committed {
            receipt: "fixture independently observed terminal".to_string(),
        },
    ).await.expect("settled");
    assert_eq!(receipt.state, LocalOutcomeState::Committed);
    assert_eq!(receipt.request.occurrence_key, queued.occurrence_key);
    let state: String = sqlx::query_scalar(
        "SELECT claim_state FROM cognitive_operation_dispatch_claims
         WHERE operation_id = ? ORDER BY claim_sequence DESC LIMIT 1",
    ).bind(&queued.occurrence_key).fetch_one(&fixture.writer.store.pool).await.expect("claim");
    assert_eq!(state, "settled");
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 1);
    assert!(fixture.writer.resolve_queued_operation(
        &queued.occurrence_key, "destination:fixture:model",
    ).await.is_err());
}

#[tokio::test]
async fn rejection_after_entry_stays_unknown_until_original_terminal_reconciliation() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:ambiguous").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:ambiguous").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    drop(entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry"));
    let unknown = fixture.writer.settle_effect_entry(
        observation, super::super::ProductionTargetOutcome::Rejected {
            reason: "fixture transport lost response after entry".to_string(),
        },
    ).await.expect("unknown");
    assert_eq!(unknown.state, LocalOutcomeState::Indeterminate);
    let terminal = fixture.writer.reconcile_observed_operation(
        &queued.occurrence_key, "destination:fixture:model",
        super::super::ProductionTargetOutcome::Committed {
            receipt: "fixture recovered the same original response".to_string(),
        },
    ).await.expect("observed terminal");
    assert_eq!(terminal.state, LocalOutcomeState::Committed);
    let state: String = sqlx::query_scalar(
        "SELECT claim_state FROM cognitive_operation_dispatch_claims
         WHERE operation_id = ? ORDER BY claim_sequence DESC LIMIT 1",
    ).bind(&queued.occurrence_key).fetch_one(&fixture.writer.store.pool).await.expect("claim");
    assert_eq!(state, "settled");
}

#[tokio::test]
async fn release_between_revalidation_and_entry_blocks_entry_and_keeps_reconciliation_available() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:release-race").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:release-race").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let ready = entry.revalidate().await.expect("revalidated");
    let writer = fixture.writer.clone();
    let close = tokio::spawn(async move { writer.release().await });
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while fixture.writer.lifecycle.lock_open().is_ok() {
            tokio::task::yield_now().await;
        }
    }).await.expect("release reached synchronous fence");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    assert!(matches!(ready.enter(&gate), Err(ProductionWriterError::StaleReceipt)));
    assert!(close.await.expect("close task").is_err());
    assert!(!observation.started());
    assert_eq!(gate.entered.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.final_use.capacity().expect("authority capacity").used_nonces, 0);
    fixture.writer.settle_effect_entry(
        observation, super::super::ProductionTargetOutcome::Rejected {
            reason: "fixture entry was synchronously canceled before send".to_string(),
        },
    ).await.expect("pre-entry rejection");
    fixture.writer.release().await.expect("resolved generation closes");
}

#[tokio::test]
async fn canceled_close_waiter_does_not_release_the_commit_guard() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let permit = fixture.writer.acquire_current_lease().await.expect("lease permit");
    let writer = fixture.writer.clone();
    let close = tokio::spawn(async move { writer.release().await });
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        while fixture.writer.lifecycle.lock_open().is_ok() {
            tokio::task::yield_now().await;
        }
    }).await.expect("release is waiting for existing permit");
    close.abort();
    let _ = close.await;
    let head = fixture.writer.store.inspect_local_lease_head(fixture.writer.lease_id())
        .await.expect("head");
    assert_eq!(head.disposition, crate::LocalLeaseHeadDisposition::Active);
    drop(permit);
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        loop {
            let head = fixture.writer.store.inspect_local_lease_head(fixture.writer.lease_id())
                .await.expect("head");
            if head.disposition == crate::LocalLeaseHeadDisposition::Released {
                break;
            }
            tokio::task::yield_now().await;
        }
    }).await.expect("owned release task completes after its waiter was canceled");
}

#[tokio::test]
async fn lost_checkpoint_ack_replay_requires_the_original_terminal_receipt() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:checkpoint-ack-lost").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:checkpoint-ack-lost").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    drop(entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry"));

    // The Responses transport separately tests that this digest covers all
    // actual SSE/GET output. Here the real writer exercises the lost checkpoint
    // acknowledgement window after the original stream terminal was committed.
    let original_receipt = serde_json::json!({
        "schema": "hepta.native.model.observed.v1",
        "operation_id": queued.occurrence_key,
        "response_id": "response-original",
        "evidence_sha256": Sha256Digest::for_bytes(b"fixture terminal.v2 original full output"),
    }).to_string();
    let committed = fixture.writer.settle_effect_entry(
        observation,
        super::super::ProductionTargetOutcome::Committed { receipt: original_receipt.clone() },
    ).await.expect("original stream terminal committed");

    let recovered = fixture.writer.reconcile_observed_operation(
        &queued.occurrence_key, "destination:fixture:model",
        super::super::ProductionTargetOutcome::Committed { receipt: original_receipt.clone() },
    ).await.expect("same GET evidence is idempotent after lost checkpoint acknowledgement");
    assert_eq!(recovered.local_event_id, committed.local_event_id);

    let changed_receipt = serde_json::json!({
        "schema": "hepta.native.model.observed.v1",
        "operation_id": queued.occurrence_key,
        "response_id": "response-original",
        "evidence_sha256": Sha256Digest::for_bytes(b"fixture terminal.v2 changed tool arguments"),
    }).to_string();
    assert!(matches!(
        fixture.writer.reconcile_observed_operation(
            &queued.occurrence_key, "destination:fixture:model",
            super::super::ProductionTargetOutcome::Committed { receipt: changed_receipt },
        ).await,
        Err(ProductionWriterError::Local(LocalLeaseOutboxError::CasConflict(_)))
    ));
    let (count, payload): (i64, String) = sqlx::query_as(
        "SELECT COUNT(*), MIN(payload_json) FROM cognitive_local_events
         WHERE occurrence_key = ? AND event_kind = 'reconcile_committed'",
    ).bind(&queued.occurrence_key).fetch_one(&fixture.writer.store.pool).await.expect("original terminal");
    assert_eq!(count, 1);
    assert_eq!(payload, original_receipt);
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Committed);
    assert!(fixture.writer.resolve_queued_operation(
        &queued.occurrence_key, "destination:fixture:model",
    ).await.is_err());
}

#[tokio::test]
async fn first_recovery_persists_actual_terminal_evidence_in_the_original_event() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:recover-terminal-evidence").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:recover-terminal-evidence").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    drop(entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry"));
    drop(observation);
    let evidence = "fixture terminal.v2 complete original output receipt".to_string();
    let first = fixture.writer.reconcile_observed_operation(
        &queued.occurrence_key, "destination:fixture:model",
        super::super::ProductionTargetOutcome::Committed { receipt: evidence.clone() },
    ).await.expect("independent GET terminal");
    let persisted: String = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events WHERE event_id = ? AND lease_id = ?",
    ).bind(&first.local_event_id).bind(fixture.writer.lease_id())
        .fetch_one(&fixture.writer.store.pool).await.expect("actual receipt persisted");
    assert_eq!(persisted, evidence);
    let replay = fixture.writer.reconcile_observed_operation(
        &queued.occurrence_key, "destination:fixture:model",
        super::super::ProductionTargetOutcome::Committed { receipt: evidence },
    ).await.expect("same observer receipt");
    assert_eq!(first.local_event_id, replay.local_event_id);
}

struct PausedTerminalObserver {
    reached: tokio::sync::Notify,
    release: tokio::sync::Notify,
    outcome: super::super::ProductionTerminalObservation,
}

impl super::super::ProductionOutboxTarget for PausedTerminalObserver {
    fn dispatch<'a>(
        &'a self,
        _request: ProductionDispatchRequest,
    ) -> super::super::ProductionDispatchFuture<'a> {
        Box::pin(async {
            panic!("observer-only fixture must never dispatch")
        })
    }
}

impl super::super::FinalUseProductionOutboxTarget for PausedTerminalObserver {
    fn destination_id(&self) -> &str {
        "destination:fixture:model"
    }

    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> super::super::ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            self.reached.notify_one();
            self.release.notified().await;
            self.outcome.clone()
        })
    }
}

#[tokio::test]
async fn background_unknown_overtaken_by_native_terminal_does_not_fail_the_service() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:background-unknown-race").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:background-unknown-race").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    drop(entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry"));
    let observer = Arc::new(PausedTerminalObserver {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
        outcome: super::super::ProductionTerminalObservation::Indeterminate {
            reason: "fixture job was pending when the background observer read it".to_string(),
        },
    });
    let background = {
        let writer = fixture.writer.clone();
        let observer = Arc::clone(&observer);
        tokio::spawn(async move { writer.reconcile_target_batch(observer.as_ref(), 1).await })
    };
    tokio::time::timeout(std::time::Duration::from_secs(2), observer.reached.notified())
        .await.expect("background discovered original pending operation");
    let committed = fixture.writer.settle_effect_entry(
        observation, super::super::ProductionTargetOutcome::Committed {
            receipt: "fixture native callback terminal evidence".to_string(),
        },
    ).await.expect("native terminal wins the race");
    observer.release.notify_one();
    let count = tokio::time::timeout(std::time::Duration::from_secs(2), background)
        .await.expect("background finished").expect("background task")
        .expect("stale weak observation is benign");
    assert_eq!(count, 0);
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Committed);
    let payload: String = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events WHERE lease_id = ? AND event_id = ?",
    ).bind(fixture.writer.lease_id()).bind(committed.local_event_id)
        .fetch_one(&fixture.writer.store.pool).await.expect("original terminal event");
    assert_eq!(payload, "fixture native callback terminal evidence");
}

#[tokio::test]
async fn conflicting_background_terminal_cannot_replace_the_native_callback_receipt() {
    let fixture = Fixture::new().await.expect("effect entry fixture");
    let (queued, binding) = fixture.queued("operation:background-conflict-race").await.expect("original operation fixture");
    let signed = fixture.grant(&binding, "grant:background-conflict-race").expect("original grant fixture");
    let (entry, observation) = fixture.writer.begin_effect_entry(
        &fixture.final_use, &signed, &binding, "destination:fixture:model", queued.clone(),
    ).await.expect("entry");
    let gate = FixtureCurrentness { allowed: true, entered: AtomicUsize::new(0) };
    drop(entry.revalidate().await.expect("revalidated").enter(&gate).expect("entry"));
    let observer = Arc::new(PausedTerminalObserver {
        reached: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
        outcome: super::super::ProductionTerminalObservation::Applied {
            receipt: "fixture conflicting background output".to_string(),
        },
    });
    let background = {
        let writer = fixture.writer.clone();
        let observer = Arc::clone(&observer);
        tokio::spawn(async move { writer.reconcile_target_batch(observer.as_ref(), 1).await })
    };
    tokio::time::timeout(std::time::Duration::from_secs(2), observer.reached.notified())
        .await.expect("background discovered original pending operation");
    let committed = fixture.writer.settle_effect_entry(
        observation, super::super::ProductionTargetOutcome::Committed {
            receipt: "fixture original native output".to_string(),
        },
    ).await.expect("native terminal wins the race");
    observer.release.notify_one();
    let result = tokio::time::timeout(std::time::Duration::from_secs(2), background)
        .await.expect("background finished").expect("background task");
    assert!(matches!(result,
        Err(ProductionWriterError::Local(LocalLeaseOutboxError::CasConflict(_)))
    ));
    assert_eq!(fixture.writer.status(&queued.occurrence_key).await.expect("state"),
        LocalOutcomeState::Committed);
    let payload: String = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events WHERE lease_id = ? AND event_id = ?",
    ).bind(fixture.writer.lease_id()).bind(committed.local_event_id)
        .fetch_one(&fixture.writer.store.pool).await.expect("original terminal event");
    assert_eq!(payload, "fixture original native output");
}




#[path = "production_unused_scope_tests.rs"]
mod unused_scope_tests;

#[path = "production_scope_frontier_tests.rs"]
mod scope_frontier_tests;
