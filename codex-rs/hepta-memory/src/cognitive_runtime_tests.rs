use std::sync::Arc;
use std::time::Duration;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveRuntime;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveUnavailableReason;
use crate::FederatedMemoryReader;
use crate::FederatedRecallSet;
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

fn discover_with_one_stalled_owner<'a>(
    owner_layout: &'a codex_hepta_paths::HeptaAgentLayout,
    consumer_agent_id: &'a codex_hepta_contracts::AgentId,
    now_unix_seconds: i64,
) -> super::cognitive_runtime::ProductDiscoveryFuture<'a> {
    if owner_layout.agent_id() == &agent_id(181) {
        Box::pin(std::future::pending())
    } else {
        Box::pin(FederatedMemoryReader::discover(
            owner_layout,
            consumer_agent_id,
            now_unix_seconds,
        ))
    }
}

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
    let second_citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "runtime-v2-source-secondary",
                "Canonical federation secondary evidence.",
            ),
        )
        .await
        .expect("second owner source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "runtime-v2-memory-secondary".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Canonical federation secondary evidence.",
                    second_citation,
                ),
            },
        )
        .await
        .expect("second owner memory");
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
    assert!(runtime.has_product_federation());
    assert_eq!(runtime.federation_consumer_agent_id(), Some(&consumer_id));
    let access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace.clone());
    let (batch, coverage) = runtime
        .retrieve_product_federated(&access, &RetrievalRequest::new("Canonical federation", 150))
        .await
        .expect("canonical product retrieval");
    assert_eq!(coverage.requested_peers, 1);
    assert_eq!(coverage.completed_peers, 1);
    assert_eq!(coverage.failed_peers, 0);
    assert_eq!(coverage.truncated_peers, 0);
    assert_eq!(coverage.omitted_peer_candidates, 0);
    assert_eq!(coverage.truncated_items, 0);
    assert_eq!(coverage.failures.discovery_unavailable, 0);
    assert_eq!(coverage.failures.deadline_or_cancelled, 0);
    assert_eq!(coverage.failures.authority_rejected, 0);
    assert_eq!(coverage.failures.integrity_rejected, 0);
    assert_eq!(coverage.failures.transport_unavailable, 0);
    assert_eq!(batch.candidates.len(), 2);
    assert!(
        batch
            .candidates
            .iter()
            .all(|candidate| candidate.source_agent_id == owner_id)
    );
    let mut contents = batch
        .candidates
        .iter()
        .map(|candidate| candidate.candidate.memory.content.as_str())
        .collect::<Vec<_>>();
    contents.sort_unstable();
    assert_eq!(
        contents,
        vec![
            "Canonical federation product evidence.",
            "Canonical federation secondary evidence.",
        ]
    );
    let bindings = batch
        .candidates
        .iter()
        .map(|candidate| candidate.revalidation.clone())
        .collect::<Vec<_>>();
    let statuses = runtime
        .revalidate_product_federated_batch(&access, &bindings, 150)
        .await
        .expect("batch physical-send revalidation");
    assert_eq!(statuses.len(), bindings.len());
    assert!(
        statuses
            .iter()
            .all(|status| matches!(status, FederatedRevalidationStatus::Current(_)))
    );
    let binding = bindings[0].clone();
    assert!(matches!(
        runtime
            .revalidate_product_federated(&access, &binding, 150)
            .await,
        Ok(FederatedRevalidationStatus::Current(_))
    ));

    owner
        .revoke_federated_recall(&owner_access, &capability, 151)
        .await
        .expect("revoke");
    let status = runtime
        .revalidate_product_federated(&access, &binding, 152)
        .await
        .expect("post-revoke physical-send revalidation");
    assert!(matches!(
        status,
        FederatedRevalidationStatus::Stale(
            FederationRevalidationDrift::CapabilityMissing | FederationRevalidationDrift::Revoked
        )
    ));
    let revoked_statuses = runtime
        .revalidate_product_federated_batch(&access, &bindings, 152)
        .await
        .expect("post-revoke batch physical-send revalidation");
    assert_eq!(revoked_statuses.len(), bindings.len());
    assert!(revoked_statuses.iter().all(|status| {
        matches!(
            status,
            FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::CapabilityMissing
                    | FederationRevalidationDrift::Revoked
            )
        )
    }));
    let (revoked_batch, revoked_coverage) = runtime
        .retrieve_product_federated(&access, &RetrievalRequest::new("Canonical federation", 152))
        .await
        .expect("revoked federation remains a bounded read result");
    assert!(revoked_batch.candidates.is_empty());
    assert_eq!(revoked_coverage.completed_peers, 0);
}

#[tokio::test]
async fn legacy_federation_is_not_admitted_to_product_attachment_api() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(86);
    let consumer_id = agent_id(87);
    let owner_layout = layout(&temp, &owner_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let consumer_workspace = workspace("runtime-legacy-consumer");
    owner
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
    let readers = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("legacy discovery");
    let federation =
        FederatedRecallSet::new(consumer_id.clone(), readers).expect("legacy recall set");
    let runtime = CognitiveRuntime::AvailableFederated {
        store: Arc::new(consumer),
        federation: Arc::new(federation),
    };
    assert!(runtime.has_federation());
    assert!(!runtime.has_product_federation());

    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    assert!(matches!(
        runtime
            .retrieve_product_federated(&access, &RetrievalRequest::new("anything", 150))
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
}

#[tokio::test]
async fn legacy_compatibility_helper_cannot_downgrade_product_v2_runtime() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(88);
    let consumer_id = agent_id(89);
    let owner_layout = layout(&temp, &owner_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let consumer_workspace = workspace("runtime-v2-no-legacy-downgrade");
    owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(CognitiveScope::AgentPrivate, consumer_workspace),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let readers = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("legacy discovery");
    let legacy = FederatedRecallSet::new(consumer_id.clone(), readers).expect("legacy recall set");

    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id, vec![owner_layout])
        .with_federation(legacy);

    assert!(runtime.has_product_federation());
    assert!(runtime.federation().is_none());
}

#[tokio::test]
async fn product_v2_unobservable_owner_is_explicit_failed_discovery_coverage() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(84);
    let consumer_id = agent_id(85);
    let owner_layout = layout(&temp, &owner_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let bad_owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store before corruption");
    let bad_database = bad_owner.path().to_path_buf();
    bad_owner.pool.close().await;
    drop(bad_owner);
    std::fs::write(&bad_database, b"not-a-sqlite-database")
        .expect("corrupt current owner database fixture");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id.clone(), vec![owner_layout]);
    let access =
        FederationConsumerAccess::new(consumer_id, workspace("runtime-v2-discovery-unavailable"));
    let (batch, coverage) = runtime
        .retrieve_product_federated(&access, &RetrievalRequest::new("anything", 150))
        .await
        .expect("discovery failure must remain bounded coverage");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 1);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.failed_peers, 1);
    assert_eq!(coverage.failures.discovery_unavailable, 1);
    assert_eq!(coverage.failures.deadline_or_cancelled, 0);
    assert_eq!(coverage.failures.authority_rejected, 0);
    assert_eq!(coverage.failures.integrity_rejected, 0);
    assert_eq!(coverage.failures.transport_unavailable, 0);
}

#[tokio::test]
async fn product_v2_scope_mismatch_is_not_enrolled_or_dispatched() {
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
        .retrieve_product_federated(&wrong_access, &RetrievalRequest::new("anything", 150))
        .await
        .expect("scope mismatch must not form a queried peer");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 0);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.failed_peers, 0);
}

#[tokio::test]
async fn product_v2_composition_reports_omitted_owner_candidates() {
    let temp = TempDir::new().expect("temp dir");
    let consumer_id = agent_id(200);
    let consumer_layout = layout(&temp, &consumer_id);
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let owner_layouts = (0..130)
        .map(|index| agent_id(u8::try_from(index + 1).expect("bounded id")))
        .map(|owner_id| layout(&temp, &owner_id))
        .collect::<Vec<_>>();
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id, owner_layouts);
    match runtime {
        CognitiveRuntime::AvailableFederatedV2 {
            owner_layouts,
            omitted_owner_candidates,
            ..
        } => {
            assert_eq!(owner_layouts.len(), 128);
            assert_eq!(omitted_owner_candidates, 2);
        }
        other => panic!("expected V2 runtime, got {other:?}"),
    }
}

#[tokio::test]
async fn product_v2_reports_peer_truncation_before_aggregation() {
    let temp = TempDir::new().expect("temp dir");
    let consumer_id = agent_id(220);
    let consumer_layout = layout(&temp, &consumer_id);
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let consumer_workspace = workspace("runtime-v2-peer-truncation");
    let mut owner_layouts = Vec::new();
    for raw_id in 1..=17 {
        let owner_id = agent_id(raw_id);
        let owner_layout = layout(&temp, &owner_id);
        let owner = CognitiveStore::open(&owner_layout)
            .await
            .expect("owner store");
        let owner_access = CognitiveAccess::agent_private(owner_id);
        owner
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
        owner_layouts.push(owner_layout);
    }

    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id.clone(), owner_layouts);
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    let (batch, coverage) = runtime
        .retrieve_product_federated(&access, &RetrievalRequest::new("anything", 150))
        .await
        .expect("bounded product retrieval");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 16);
    assert_eq!(coverage.completed_peers, 16);
    assert_eq!(coverage.failed_peers, 0);
    assert_eq!(coverage.truncated_peers, 1);
    assert_eq!(coverage.omitted_peer_candidates, 0);
}

#[tokio::test]
async fn product_v2_stalled_owner_preserves_healthy_peer_and_typed_coverage() {
    let temp = TempDir::new().expect("temp dir");
    let healthy_id = agent_id(180);
    let stalled_id = agent_id(181);
    let consumer_id = agent_id(182);
    let healthy_layout = layout(&temp, &healthy_id);
    let stalled_layout = layout(&temp, &stalled_id);
    let healthy = CognitiveStore::open(&healthy_layout)
        .await
        .expect("healthy owner store");
    let healthy_access = CognitiveAccess::agent_private(healthy_id.clone());
    let citation = healthy
        .append_source(
            &healthy_access,
            &source(
                CognitiveScope::AgentPrivate,
                "healthy-discovery-source",
                "Healthy federation evidence survives a stalled owner.",
            ),
        )
        .await
        .expect("healthy source");
    healthy
        .remember_memory(
            &healthy_access,
            &MemoryDraft {
                stable_key: "healthy-discovery-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Healthy federation evidence survives a stalled owner.",
                    citation,
                ),
            },
        )
        .await
        .expect("healthy memory");
    let consumer_workspace = workspace("stalled-owner-isolation");
    healthy
        .grant_federated_recall(
            &healthy_access,
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
        .expect("healthy grant");

    let access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace);
    let owner_layouts = vec![healthy_layout, stalled_layout];
    let (batch, coverage) = super::cognitive_runtime::retrieve_federated_product_with_discoverer(
        &consumer_id,
        &owner_layouts,
        0,
        &access,
        &RetrievalRequest::new("Healthy federation evidence", 150),
        Duration::from_secs(1),
        discover_with_one_stalled_owner,
    )
    .await
    .expect("healthy result survives stalled owner");

    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, healthy_id);
    assert_eq!(coverage.requested_peers, 2);
    assert_eq!(coverage.completed_peers, 1);
    assert_eq!(coverage.failed_peers, 1);
    assert_eq!(coverage.failures.discovery_unavailable, 0);
    assert_eq!(coverage.failures.deadline_or_cancelled, 1);
    assert_eq!(coverage.failures.authority_rejected, 0);
    assert_eq!(coverage.failures.integrity_rejected, 0);
    assert_eq!(coverage.failures.transport_unavailable, 0);
}

#[tokio::test]
async fn product_v2_bad_owner_preserves_healthy_peer_and_typed_coverage() {
    let temp = TempDir::new().expect("temp dir");
    let healthy_id = agent_id(183);
    let bad_id = agent_id(184);
    let consumer_id = agent_id(185);
    let healthy_layout = layout(&temp, &healthy_id);
    let bad_layout = layout(&temp, &bad_id);
    let consumer_layout = layout(&temp, &consumer_id);
    let healthy = CognitiveStore::open(&healthy_layout)
        .await
        .expect("healthy owner store");
    let bad = CognitiveStore::open(&bad_layout)
        .await
        .expect("bad owner store before corruption");
    let bad_database = bad.path().to_path_buf();
    bad.pool.close().await;
    drop(bad);
    std::fs::write(&bad_database, b"not-a-sqlite-database")
        .expect("corrupt current bad-owner database");
    let consumer = CognitiveStore::open(&consumer_layout)
        .await
        .expect("consumer store");
    let healthy_access = CognitiveAccess::agent_private(healthy_id.clone());
    let citation = healthy
        .append_source(
            &healthy_access,
            &source(
                CognitiveScope::AgentPrivate,
                "bad-owner-isolation-source",
                "Healthy evidence survives an unavailable owner.",
            ),
        )
        .await
        .expect("healthy source");
    healthy
        .remember_memory(
            &healthy_access,
            &MemoryDraft {
                stable_key: "bad-owner-isolation-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Healthy evidence survives an unavailable owner.",
                    citation,
                ),
            },
        )
        .await
        .expect("healthy memory");
    let consumer_workspace = workspace("bad-owner-isolation");
    healthy
        .grant_federated_recall(
            &healthy_access,
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
        .expect("healthy grant");
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer))
        .with_federation_sources(consumer_id.clone(), vec![healthy_layout, bad_layout]);
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    let (batch, coverage) = runtime
        .retrieve_product_federated(&access, &RetrievalRequest::new("Healthy evidence", 150))
        .await
        .expect("healthy result survives bad owner");

    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, healthy_id);
    assert_eq!(coverage.requested_peers, 2);
    assert_eq!(coverage.completed_peers, 1);
    assert_eq!(coverage.failed_peers, 1);
    assert_eq!(coverage.failures.discovery_unavailable, 1);
    assert_eq!(coverage.failures.deadline_or_cancelled, 0);
}

#[path = "cognitive_federation_capacity_tests.rs"]
mod capacity;
