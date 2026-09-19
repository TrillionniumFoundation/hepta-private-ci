use super::*;

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::OperationIntent;
use codex_hepta_operations::OperationKey;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::LocalOutcomeState;
use crate::LocalReconcileOutcome;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::ProductionDurableWriter;
use crate::ProductionFinalUseOutboxDispatcher;
use crate::ProductionOutboxTarget;

fn agent() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d00").expect("agent")
}

async fn store(temp: &TempDir) -> CognitiveStore {
    let root = temp.path().join("fleet-real-target");
    std::fs::create_dir_all(&root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(root.canonicalize().expect("canonical root"))
        .expect("fleet root");
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

fn operation(
    owner: &AgentId,
    operation_id: &str,
    payload: &str,
) -> OperationIntent {
    OperationIntent {
        key: OperationKey {
            id: StableId::new(operation_id).expect("operation id"),
            payload_digest: Digest32::of_bytes(payload.as_bytes()),
        },
        scope: StableId::new("scope:cognitive-source:agent-private").expect("scope"),
        owner: StableId::new(owner.as_str()).expect("owner"),
        destination: StableId::new(COGNITIVE_SOURCE_DESTINATION_V1).expect("destination"),
        expected_predecessor: None,
    }
}

fn signed_final_use(
    issuer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce: [u8; 32],
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
        nonce,
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
    std::fs::set_permissions(
        &authority_dir,
        std::fs::Permissions::from_mode(0o700),
    )
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

#[derive(Clone, Debug)]
struct LostAckTarget {
    inner: CognitiveSourceOutboxTarget,
}

impl ProductionOutboxTarget for LostAckTarget {
    fn dispatch<'a>(
        &'a self,
        request: crate::ProductionDispatchRequest,
    ) -> crate::ProductionDispatchFuture<'a> {
        Box::pin(async move {
            match self.inner.dispatch(request).await {
                crate::ProductionTargetOutcome::Committed { .. } => {
                    crate::ProductionTargetOutcome::Indeterminate {
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
}

#[cfg(unix)]
#[tokio::test]
async fn real_cognitive_destination_deduplicates_same_operation_and_rejects_payload_drift() {
    let temp = TempDir::new().expect("temp");
    let store = store(&temp).await;
    let owner = store.owner_agent_id().clone();
    let target = CognitiveSourceOutboxTarget::new(
        store.clone(),
        CognitiveAccess::agent_private(owner.clone()),
    )
    .expect("target");

    let operation_id = "operation:cognitive-dedupe";
    let (_draft, payload) = source_payload(operation_id, b"stable-source-content");
    let request = crate::ProductionDispatchRequest {
        schema_version: crate::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION,
        namespace: crate::PRODUCTION_DURABLE_WRITER_NAMESPACE.to_string(),
        lease_id: "lease:destination-direct".to_string(),
        occurrence_key: operation_id.to_string(),
        topic: COGNITIVE_SOURCE_TOPIC_V1.to_string(),
        payload_json: payload.clone(),
        payload_sha256: Sha256Digest::for_bytes(payload.as_bytes()),
        idempotency_key: operation_id.to_string(),
        operation_digest: Sha256Digest::for_bytes(b"operation-digest"),
    };
    let first = target.dispatch(request.clone()).await;
    let second = target.dispatch(request.clone()).await;
    let first_receipt = match first {
        crate::ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("unexpected first outcome: {other:?}"),
    };
    let second_receipt = match second {
        crate::ProductionTargetOutcome::Committed { receipt } => receipt,
        other => panic!("unexpected replay outcome: {other:?}"),
    };
    assert_eq!(first_receipt, second_receipt);

    let (_changed_draft, changed_payload) =
        source_payload(operation_id, b"changed-source-content");
    let changed = crate::ProductionDispatchRequest {
        payload_json: changed_payload.clone(),
        payload_sha256: Sha256Digest::for_bytes(changed_payload.as_bytes()),
        ..request
    };
    assert!(matches!(
        target.dispatch(changed).await,
        crate::ProductionTargetOutcome::Rejected { .. }
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn full_durable_final_use_slice_reconciles_lost_ack_from_real_destination() {
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

    let real_target = CognitiveSourceOutboxTarget::new(
        store.clone(),
        CognitiveAccess::agent_private(owner.clone()),
    )
    .expect("real target");
    let lost_ack_target = Arc::new(LostAckTarget {
        inner: real_target.clone(),
    });
    let issuer = SigningKey::from_bytes(&[91; 32]);
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(
        final_use(&temp, &issuer),
        lost_ack_target,
    );

    let operation_id = "operation:cognitive-lost-ack";
    let (_draft, payload) = source_payload(operation_id, b"durable-real-effect");
    let queued = writer
        .prepare_operation(
            operation(&owner, operation_id, &payload),
            COGNITIVE_SOURCE_TOPIC_V1,
            &payload,
        )
        .await
        .expect("atomic prepare + outbox");

    let binding = writer
        .final_use_binding(&queued, COGNITIVE_SOURCE_DESTINATION_V1)
        .await
        .expect("canonical binding");
    let signed = signed_final_use(&issuer, binding.clone(), "real-target-grant", [41; 32]);
    let dispatched = dispatcher
        .dispatch(&writer, &signed, &binding, queued)
        .await
        .expect("dispatch with lost ack");
    assert_eq!(dispatched.state, LocalOutcomeState::Indeterminate);
    assert_eq!(
        writer.status(operation_id).await.expect("indeterminate status"),
        LocalOutcomeState::Indeterminate
    );

    match real_target.observe_terminal(&dispatched.request).await {
        CognitiveSourceTerminalObservation::Applied { receipt } => {
            assert!(receipt.contains("source:v1:"));
            writer
                .reconcile(operation_id, LocalReconcileOutcome::Committed)
                .await
                .expect("trusted destination reconciliation");
        }
        other => panic!("expected applied destination observation, got {other:?}"),
    }
    assert_eq!(
        writer.status(operation_id).await.expect("terminal status"),
        LocalOutcomeState::Committed
    );
}
