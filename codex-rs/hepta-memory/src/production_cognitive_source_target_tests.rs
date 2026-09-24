#![cfg(unix)]

use super::*;

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::LocalOutcomeState;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionDispatchFuture;
use crate::ProductionDispatchRequest;
use crate::ProductionDurableWriter;
use crate::ProductionFinalUseOutboxDispatcher;
use crate::ProductionOutboxTarget;
use crate::ProductionTargetOutcome;
use crate::ProductionTerminalObservation;
use crate::ProductionTerminalObservationFuture;

fn agent() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d00").expect("agent")
}

async fn store(temp: &TempDir) -> CognitiveStore {
    let root = temp.path().join("fleet-real-target");
    std::fs::create_dir_all(&root).expect("fleet root");
    let fleet =
        HeptaFleetRoot::parse(root.canonicalize().expect("canonical root")).expect("fleet root");
    CognitiveStore::open(&fleet.layout().agent(&agent()))
        .await
        .expect("store")
}

struct AllowVerifier;

impl ProductionAuthorityVerifier for AllowVerifier {
    fn verify(
        &self,
        _authority: &ProductionAuthorityLease,
        _expected_agent: &AgentId,
    ) -> Result<(), String> {
        Ok(())
    }
}

fn unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
}

fn production_authority(owner: AgentId) -> ProductionAuthorityLease {
    ProductionAuthorityLease::from_verified_parts(
        owner,
        Sha256Digest::for_bytes(b"real-target-production-grant"),
        90,
        100,
        unix_seconds() + 3_600,
        ProductionAuthorityToken::from_verified_bytes(b"real-target-production-token".to_vec())
            .expect("token"),
    )
    .expect("production authority")
}

fn source_payload(operation_id: &str, content: &[u8]) -> (SourceDraft, String) {
    let draft = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::PersistedToolResult,
        event_key: operation_id.to_string(),
        content: content.to_vec(),
        observed_at_unix_seconds: 1_900_000_000,
    };
    let payload = CognitiveSourceOperationV1::from_draft(&draft)
        .to_json()
        .expect("payload json");
    (draft, payload)
}

fn scope_digest(draft: &SourceDraft) -> Digest32 {
    let (scope_kind, workspace_sha256) = draft.scope.database_parts();
    let mut bytes = b"hepta.cognitive.source.final-use-scope.v1\0".to_vec();
    bytes.extend_from_slice(&(scope_kind.len() as u32).to_be_bytes());
    bytes.extend_from_slice(scope_kind.as_bytes());
    match workspace_sha256 {
        Some(workspace) => {
            bytes.push(1);
            bytes.extend_from_slice(&(workspace.len() as u32).to_be_bytes());
            bytes.extend_from_slice(workspace.as_bytes());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn operation(
    owner: &AgentId,
    operation_id: &str,
    payload: &str,
    draft: &SourceDraft,
    predecessor: Option<Digest32>,
) -> OperationIntentV1 {
    OperationIntentV1::new(
        StableId::new(operation_id).expect("operation id"),
        StableId::new(owner.as_str()).expect("subject"),
        StableId::new(COGNITIVE_SOURCE_DESTINATION_V1).expect("destination"),
        Digest32::of_bytes(payload.as_bytes()),
        scope_digest(draft),
        Generation::new(1).expect("policy generation"),
        predecessor,
    )
    .expect("operation intent")
}

fn direct_request(intent: &OperationIntentV1, payload: String) -> ProductionDispatchRequest {
    ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "lease:destination-direct".to_string(),
        occurrence_key: intent.operation_id().as_str().to_string(),
        topic: COGNITIVE_SOURCE_TOPIC_V1.to_string(),
        payload_json: payload.clone(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        idempotency_key: intent.operation_id().as_str().to_string(),
        operation_scope_sha256: Sha256Digest::parse(intent.scope_digest().to_string())
            .expect("scope digest"),
        operation_subject_id: intent.subject_id().as_str().to_string(),
        operation_destination_id: intent.destination_id().as_str().to_string(),
        operation_semantic_sha256: Sha256Digest::parse(intent.semantic_digest().to_string())
            .expect("semantic digest"),
        operation_policy_generation: intent.policy_generation().get(),
        expected_predecessor_sha256: intent
            .expected_predecessor()
            .map(|digest| Sha256Digest::parse(digest.to_string()).expect("predecessor digest")),
        operation_digest: Sha256Digest::for_bytes(b"qualification-operation-digest"),
    }
}

fn test_nonce(label: &str) -> [u8; 32] {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let material = format!("{label}:{now_nanos}:{}", std::process::id());
    <sha2::Sha256 as sha2::Digest>::digest(material.as_bytes()).into()
}

fn signed_final_use(
    issuer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
) -> SignedFinalUseGrant {
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "real-target-final-use-owner".to_string(),
        authority_epoch: 111,
        grant_id: grant_id.to_string(),
        nonce: test_nonce(grant_id),
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn final_use(temp: &TempDir, issuer: &SigningKey) -> FinalUseAuthority {
    let authority_dir = temp.path().join("final-use-real-target");
    std::fs::create_dir(&authority_dir).expect("authority dir");
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
        .expect("authority permissions");
    FinalUseAuthority::open_state_dir(
        &authority_dir,
        "real-target-final-use-owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 111,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority")
}

#[derive(Clone, Debug)]
struct LostAckTarget {
    inner: CognitiveSourceOutboxTarget,
}

impl ProductionOutboxTarget for LostAckTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            match self.inner.dispatch(request).await {
                ProductionTargetOutcome::Committed { .. } => {
                    ProductionTargetOutcome::Indeterminate {
                        reason: "transport acknowledgement lost after destination commit"
                            .to_string(),
                    }
                }
                other => other,
            }
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for LostAckTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            match self.inner.observe_terminal(request).await {
                CognitiveSourceTerminalObservation::Applied { receipt } => {
                    ProductionTerminalObservation::Applied { receipt }
                }
                CognitiveSourceTerminalObservation::NotApplied => {
                    ProductionTerminalObservation::NotApplied {
                        reason: "destination has no committed source row".to_string(),
                    }
                }
                CognitiveSourceTerminalObservation::Quarantined { reason } => {
                    ProductionTerminalObservation::Quarantined { reason }
                }
                CognitiveSourceTerminalObservation::Indeterminate { reason } => {
                    ProductionTerminalObservation::Indeterminate { reason }
                }
                CognitiveSourceTerminalObservation::Unavailable { reason } => {
                    ProductionTerminalObservation::Unavailable { reason }
                }
            }
        })
    }
}

#[derive(Clone, Debug)]
struct PausedTarget {
    inner: CognitiveSourceOutboxTarget,
    entered: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
}

impl ProductionOutboxTarget for PausedTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
            self.inner.dispatch(request).await
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for PausedTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            match self.inner.observe_terminal(request).await {
                CognitiveSourceTerminalObservation::Applied { receipt } => {
                    ProductionTerminalObservation::Applied { receipt }
                }
                CognitiveSourceTerminalObservation::NotApplied => {
                    ProductionTerminalObservation::NotApplied {
                        reason: "destination terminal proof records NotApplied".to_string(),
                    }
                }
                CognitiveSourceTerminalObservation::Quarantined { reason } => {
                    ProductionTerminalObservation::Quarantined { reason }
                }
                CognitiveSourceTerminalObservation::Indeterminate { reason } => {
                    ProductionTerminalObservation::Indeterminate { reason }
                }
                CognitiveSourceTerminalObservation::Unavailable { reason } => {
                    ProductionTerminalObservation::Unavailable { reason }
                }
            }
        })
    }
}

#[derive(Clone, Debug)]
struct CountingTarget {
    inner: CognitiveSourceOutboxTarget,
    entries: Arc<AtomicUsize>,
}

impl ProductionOutboxTarget for CountingTarget {
    fn dispatch<'a>(&'a self, request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async move {
            self.entries.fetch_add(1, Ordering::SeqCst);
            self.inner.dispatch(request).await
        })
    }
}

impl crate::FinalUseProductionOutboxTarget for CountingTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            match self.inner.observe_terminal(request).await {
                CognitiveSourceTerminalObservation::Applied { receipt } => {
                    ProductionTerminalObservation::Applied { receipt }
                }
                CognitiveSourceTerminalObservation::NotApplied => {
                    ProductionTerminalObservation::NotApplied {
                        reason: "destination terminal proof records NotApplied".to_string(),
                    }
                }
                CognitiveSourceTerminalObservation::Quarantined { reason } => {
                    ProductionTerminalObservation::Quarantined { reason }
                }
                CognitiveSourceTerminalObservation::Indeterminate { reason } => {
                    ProductionTerminalObservation::Indeterminate { reason }
                }
                CognitiveSourceTerminalObservation::Unavailable { reason } => {
                    ProductionTerminalObservation::Unavailable { reason }
                }
            }
        })
    }
}

#[tokio::test]
async fn destination_recomputes_full_semantics_and_deduplicates_exact_replay() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let target =
        CognitiveSourceOutboxTarget::new(store, CognitiveAccess::agent_private(owner.clone()))
            .expect("target");

    let operation_id = "operation:cognitive-dedupe";
    let (draft, payload) = source_payload(operation_id, b"stable-source-content");
    let intent = operation(&owner, operation_id, &payload, &draft, None);
    let request = direct_request(&intent, payload);

    let first = target.dispatch(request.clone()).await;
    let second = target.dispatch(request.clone()).await;
    let first_receipt = match first {
        ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("unexpected first outcome: {other:?}"),
    };
    let second_receipt = match second {
        ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("unexpected replay outcome: {other:?}"),
    };
    assert_eq!(first_receipt, second_receipt);

    let mut drifted = request;
    drifted.operation_policy_generation += 1;
    assert!(matches!(
        target.dispatch(drifted).await,
        ProductionTargetOutcome::Rejected { .. }
    ));
}

#[tokio::test]
async fn predecessor_mismatch_is_deterministic_not_applied_inside_destination_transaction() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let target =
        CognitiveSourceOutboxTarget::new(store, CognitiveAccess::agent_private(owner.clone()))
            .expect("target");

    let operation_id = "operation:cognitive-predecessor-mismatch";
    let (draft, payload) = source_payload(operation_id, b"predecessor-mismatch");
    let predecessor = Digest32::of_bytes(b"expected-existing-head");
    let intent = operation(&owner, operation_id, &payload, &draft, Some(predecessor));
    let request = direct_request(&intent, payload);

    assert!(matches!(
        target.dispatch(request.clone()).await,
        ProductionTargetOutcome::NotApplied { .. }
    ));
    assert_eq!(
        target.observe_terminal(&request).await,
        CognitiveSourceTerminalObservation::NotApplied
    );
    let proof_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_operation_destination_terminal
         WHERE destination_id = ? AND operation_id = ? AND disposition = 'not_applied'",
    )
    .bind(COGNITIVE_SOURCE_DESTINATION_V1)
    .bind(operation_id)
    .fetch_one(&target.store.pool)
    .await
    .expect("terminal proof count");
    assert_eq!(proof_count, 1);
}

#[tokio::test]
async fn absent_destination_record_is_indeterminate_not_negative_proof() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let target =
        CognitiveSourceOutboxTarget::new(store, CognitiveAccess::agent_private(owner.clone()))
            .expect("target");
    let operation_id = "operation:cognitive-not-yet-entered";
    let (draft, payload) = source_payload(operation_id, b"not-yet-entered");
    let intent = operation(&owner, operation_id, &payload, &draft, None);
    let request = direct_request(&intent, payload);

    assert!(matches!(
        target.observe_terminal(&request).await,
        CognitiveSourceTerminalObservation::Indeterminate { .. }
    ));
}

#[tokio::test]
async fn revocation_before_async_effect_entry_keeps_target_entry_count_zero() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:revoked-before-entry",
        1,
    )
    .await
    .expect("production writer");
    let entries = Arc::new(AtomicUsize::new(0));
    let target = Arc::new(CountingTarget {
        inner: CognitiveSourceOutboxTarget::new(
            store,
            CognitiveAccess::agent_private(owner.clone()),
        )
        .expect("target"),
        entries: entries.clone(),
    });
    let issuer = SigningKey::from_bytes(&[92; 32]);
    let final_use = final_use(&temp, &issuer);

    let operation_id = "operation:cognitive-revoked-before-entry";
    let (draft, payload) = source_payload(operation_id, b"must-not-enter");
    let queued = writer
        .prepare_operation(
            operation(&owner, operation_id, &payload, &draft, None),
            COGNITIVE_SOURCE_TOPIC_V1,
            &payload,
        )
        .await
        .expect("prepare");
    let binding = writer
        .final_use_binding(&queued, COGNITIVE_SOURCE_DESTINATION_V1)
        .await
        .expect("binding");
    let signed = signed_final_use(&issuer, binding.clone(), "revoked-before-entry-grant");
    final_use
        .update_revocations(FinalUseRevocations {
            authority_epoch: 111,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        })
        .expect("revoke before effect entry");
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use, target);

    assert!(matches!(
        dispatcher
            .dispatch(&writer, &signed, &binding, queued)
            .await,
        Err(crate::ProductionWriterError::FinalUse(
            FinalUseError::Revoked
        ))
    ));
    assert_eq!(entries.load(Ordering::SeqCst), 0);
    assert_eq!(
        writer.status(operation_id).await.expect("status"),
        LocalOutcomeState::Rejected
    );
}

#[tokio::test]
async fn active_async_effect_blocks_revocation_and_absence_cannot_terminalize_it() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:active-async-effect",
        1,
    )
    .await
    .expect("production writer");
    let real_target =
        CognitiveSourceOutboxTarget::new(store, CognitiveAccess::agent_private(owner.clone()))
            .expect("target");
    let entered = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let target = Arc::new(PausedTarget {
        inner: real_target,
        entered: entered.clone(),
        release: release.clone(),
    });
    let issuer = SigningKey::from_bytes(&[93; 32]);
    let final_use = final_use(&temp, &issuer);
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use.clone(), target);

    let operation_id = "operation:cognitive-active-async-effect";
    let (draft, payload) = source_payload(operation_id, b"late-commit");
    let queued = writer
        .prepare_operation(
            operation(&owner, operation_id, &payload, &draft, None),
            COGNITIVE_SOURCE_TOPIC_V1,
            &payload,
        )
        .await
        .expect("prepare");
    let binding = writer
        .final_use_binding(&queued, COGNITIVE_SOURCE_DESTINATION_V1)
        .await
        .expect("binding");
    let signed = signed_final_use(&issuer, binding.clone(), "active-effect-grant");
    let task_dispatcher = dispatcher.clone();
    let task_writer = writer.clone();
    let task_signed = signed.clone();
    let task_binding = binding.clone();
    let dispatch = tokio::spawn(async move {
        task_dispatcher
            .dispatch(&task_writer, &task_signed, &task_binding, queued)
            .await
    });

    entered.notified().await;
    assert_eq!(
        final_use.update_revocations(FinalUseRevocations {
            authority_epoch: 111,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
        }),
        Err(FinalUseError::DispatchInProgress)
    );
    assert_eq!(
        dispatcher.reconcile(&writer, 8).await.expect("reconcile"),
        1
    );
    assert_eq!(
        writer.status(operation_id).await.expect("status"),
        LocalOutcomeState::Indeterminate,
        "temporary destination absence must not terminalize an active effect"
    );

    release.notify_one();
    let receipt = dispatch
        .await
        .expect("dispatch task")
        .expect("dispatch result");
    assert_eq!(receipt.state, LocalOutcomeState::Committed);
    assert_eq!(
        writer.status(operation_id).await.expect("terminal status"),
        LocalOutcomeState::Committed
    );
    final_use
        .update_revocations(FinalUseRevocations {
            authority_epoch: 111,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([signed.grant.grant_id]),
        })
        .expect("revocation after effect completion");
}

#[tokio::test]
async fn full_durable_final_use_slice_reconciles_lost_ack_without_redispatch() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:h4:real-cognitive-source",
        1,
    )
    .await
    .expect("production writer");
    let real_target =
        CognitiveSourceOutboxTarget::new(store, CognitiveAccess::agent_private(owner.clone()))
            .expect("real target");
    let target = Arc::new(LostAckTarget {
        inner: real_target.clone(),
    });
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use(&temp, &issuer), target);

    let operation_id = "operation:cognitive-lost-ack";
    let (draft, payload) = source_payload(operation_id, b"durable-real-effect");
    let queued = writer
        .prepare_operation(
            operation(&owner, operation_id, &payload, &draft, None),
            COGNITIVE_SOURCE_TOPIC_V1,
            &payload,
        )
        .await
        .expect("atomic prepare + outbox");

    let binding = writer
        .final_use_binding(&queued, COGNITIVE_SOURCE_DESTINATION_V1)
        .await
        .expect("canonical binding");
    let signed = signed_final_use(&issuer, binding.clone(), "real-target-grant");
    let dispatched = dispatcher
        .dispatch(&writer, &signed, &binding, queued)
        .await
        .expect("dispatch with lost ack");
    assert_eq!(dispatched.state, LocalOutcomeState::Indeterminate);

    assert_eq!(
        dispatcher
            .reconcile(&writer, 8)
            .await
            .expect("observer-only reconciliation"),
        1
    );
    assert_eq!(
        writer.status(operation_id).await.expect("terminal status"),
        LocalOutcomeState::Committed
    );
}
