use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveRuntime;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveUnavailableReason;
use crate::FederatedRevalidationStatus;
use crate::FederationConsumerAccess;
use crate::FederationGrantRequest;
use crate::FederationGrantScope;
use crate::FederationRevalidationDrift;
use crate::MemoryDraft;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[test]
fn unavailable_runtime_exposes_only_a_stable_sanitized_code() {
    let runtime = CognitiveRuntime::from_open_result(Err(CognitiveStoreError::Unavailable(
        "/private/store/path: secret database detail".to_string(),
    )));
    assert_eq!(
        runtime.unavailable_reason(),
        Some(CognitiveUnavailableReason::StorageUnavailable)
    );
    assert_eq!(
        runtime
            .unavailable_reason()
            .map(super::cognitive_runtime::CognitiveUnavailableReason::code),
        Some("storage_unavailable")
    );
    assert_eq!(
        format!("{runtime:?}"),
        "CognitiveRuntime::Unavailable(StorageUnavailable)"
    );
}

#[tokio::test]
async fn product_v2_runtime_reads_only_explicit_grants_and_preserves_coverage() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(80);
    let consumer_id = agent_id(81);
    let owner_layout = layout(&temp, &owner_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let owner_access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "runtime-v2-source",
                "Canonical federation product evidence.",
            ),
        )
        .await
        .expect("owner source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "runtime-v2-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Canonical federation product evidence.",
                    citation,
                ),
            },
        )
        .await
        .expect("owner memory");
    let consumer_workspace = workspace("runtime-v2-consumer");
    let capability = owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");

    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id.clone(), vec![owner_layout.clone()]);
    assert!(runtime.has_federation());
    assert_eq!(runtime.federation_consumer_agent_id(), Some(&consumer_id));
    let access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace.clone());
    let (batch, coverage) = runtime
        .retrieve_federated(&access, &RetrievalRequest::new("Canonical federation", 150))
        .await
        .expect("canonical product retrieval");
    assert_eq!(coverage.requested_peers, 1);
    assert_eq!(coverage.completed_peers, 1);
    assert_eq!(coverage.failed_peers, 0);
    assert_eq!(coverage.truncated_items, 0);
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, owner_id);
    assert_eq!(
        batch.candidates[0].candidate.memory.content,
        "Canonical federation product evidence."
    );
    let binding = batch.candidates[0].revalidation.clone();
    assert!(matches!(
        runtime.revalidate_federated(&access, &binding, 150).await,
        Ok(FederatedRevalidationStatus::Current(_))
    ));

    owner
        .revoke_federated_recall(&owner_access, &capability, 151)
        .await
        .expect("revoke");
    let status = runtime
        .revalidate_federated(&access, &binding, 152)
        .await
        .expect("post-revoke physical-send revalidation");
    assert!(matches!(
        status,
        FederatedRevalidationStatus::Stale(
            FederationRevalidationDrift::CapabilityMissing | FederationRevalidationDrift::Revoked
        )
    ));
    let (revoked_batch, revoked_coverage) = runtime
        .retrieve_federated(&access, &RetrievalRequest::new("Canonical federation", 152))
        .await
        .expect("revoked federation remains a bounded read result");
    assert!(revoked_batch.candidates.is_empty());
    assert_eq!(revoked_coverage.completed_peers, 0);
}

#[tokio::test]
async fn product_v2_scope_failure_is_explicit_failed_coverage_not_empty_success() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(82);
    let consumer_id = agent_id(83);
    let owner_layout = layout(&temp, &owner_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let allowed_workspace = workspace("runtime-v2-allowed");
    owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(CognitiveScope::AgentPrivate, allowed_workspace),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id.clone(), vec![owner_layout]);
    let wrong_access = FederationConsumerAccess::new(consumer_id, workspace("runtime-v2-wrong"));
    let (batch, coverage) = runtime
        .retrieve_federated(&wrong_access, &RetrievalRequest::new("anything", 150))
        .await
        .expect("scope mismatch is represented as failed coverage");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 1);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.failed_peers, 1);
}
