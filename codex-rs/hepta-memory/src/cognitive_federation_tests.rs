use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::FederatedMemoryReader;
use crate::FederatedRecallSet;
use crate::FederatedRevalidationStatus;
use crate::FederationCapabilityState;
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

#[tokio::test]
async fn explicit_grant_is_owner_written_consumer_read_only_and_scope_exact() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(30);
    let consumer_id = agent_id(31);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_workspace = workspace("owner-project");
    let consumer_workspace = workspace("consumer-project");
    let owner_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: owner_workspace.clone(),
    };
    let owner_access = CognitiveAccess::workspace_private(owner_id.clone(), owner_workspace);
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                owner_scope.clone(),
                "owner-orbit-source",
                "The owner recorded a private orbital result.",
            ),
        )
        .await
        .expect("owner source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "owner-orbit-memory".to_string(),
                revision: memory_revision(
                    owner_scope.clone(),
                    "The orbital period is forty two days.",
                    citation,
                ),
            },
        )
        .await
        .expect("owner memory");
    let private_source = owner
        .append_source(
            &CognitiveAccess::agent_private(owner_id.clone()),
            &source(
                CognitiveScope::AgentPrivate,
                "agent-private-source",
                "The agent-private orbital secret is not shared.",
            ),
        )
        .await
        .expect("private source");
    owner
        .remember_memory(
            &CognitiveAccess::agent_private(owner_id.clone()),
            &MemoryDraft {
                stable_key: "agent-private-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "The agent-private orbital secret is not shared.",
                    private_source,
                ),
            },
        )
        .await
        .expect("private memory");

    let cross_agent_grant = owner
        .grant_federated_recall(
            &CognitiveAccess::agent_private(consumer_id.clone()),
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(owner_scope.clone(), consumer_workspace.clone()),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect_err("consumer cannot write an owner grant");
    assert!(matches!(
        cross_agent_grant,
        CognitiveStoreError::AccessDenied(_)
    ));

    let capability = owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(owner_scope, consumer_workspace.clone()),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let listed = owner
        .list_federation_capabilities(16)
        .await
        .expect("list grants");
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].capability, capability);
    assert_eq!(listed[0].state, FederationCapabilityState::Granted);
    assert_eq!(
        owner
            .federation_capability_status(capability.id())
            .await
            .expect("grant status")
            .expect("grant exists")
            .state,
        FederationCapabilityState::Granted
    );
    assert_eq!(capability.generation(), 1);
    assert_eq!(capability.revision(), 1);

    let readers = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover");
    assert_eq!(readers.len(), 1);
    let access = FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace);
    let batch = readers[0]
        .retrieve(&access, &RetrievalRequest::new("orbital", 150))
        .await
        .expect("federated retrieval");
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.coverage.requested_sources, 1);
    assert_eq!(batch.coverage.completed_sources, 1);
    assert_eq!(batch.coverage.failed_sources, 0);
    assert_eq!(batch.admission_expires_unix_ms, Some(152_000));
    assert_eq!(batch.candidates[0].source_agent_id, owner_id);
    assert_eq!(
        batch.candidates[0].candidate.memory.content,
        "The orbital period is forty two days."
    );
    assert_eq!(
        batch.candidates[0].candidate.revalidation.citations[0].id,
        batch.candidates[0].revalidation.memory.citations[0].id
    );
    assert!(matches!(
        readers[0]
            .retrieve(
                &FederationConsumerAccess::new(consumer_id, workspace("wrong-workspace")),
                &RetrievalRequest::new("orbital", 150),
            )
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
}

#[tokio::test]
async fn revoke_is_observed_by_the_next_physical_send_revalidation() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(40);
    let consumer_id = agent_id(41);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "send-source",
                "A fact prepared before a physical send.",
            ),
        )
        .await
        .expect("source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "send-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "A fact prepared before a physical send.",
                    citation,
                ),
            },
        )
        .await
        .expect("memory");
    let consumer_workspace = workspace("consumer-send");
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
    let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    let prepared = reader
        .retrieve(&access, &RetrievalRequest::new("physical send", 150))
        .await
        .expect("prepare")
        .candidates
        .pop()
        .expect("candidate")
        .revalidation;
    assert!(matches!(
        reader.revalidate(&access, &prepared, 150).await,
        Ok(FederatedRevalidationStatus::Current(_))
    ));

    let revocation = owner
        .revoke_federated_recall(&owner_access, &capability, 151)
        .await
        .expect("revoke");
    assert_eq!(revocation.generation, 1);
    assert_eq!(revocation.revision, 2);
    assert_eq!(
        owner
            .federation_capability_status(capability.id())
            .await
            .expect("revoked status")
            .expect("capability exists")
            .state,
        FederationCapabilityState::Revoked
    );
    assert_eq!(
        reader
            .revalidate(&access, &prepared, 152)
            .await
            .expect("physical-send revalidation"),
        FederatedRevalidationStatus::Stale(FederationRevalidationDrift::Revoked)
    );
}

#[tokio::test]
async fn expired_and_corrupt_capabilities_fail_closed_without_cross_agent_fallback() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(50);
    let consumer_id = agent_id(51);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_access = CognitiveAccess::agent_private(owner_id);
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "expiry-source",
                "Expiring federated memory.",
            ),
        )
        .await
        .expect("source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "expiry-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Expiring federated memory.",
                    citation,
                ),
            },
        )
        .await
        .expect("memory");
    let consumer_workspace = workspace("expiry-consumer");
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
                expires_at_unix_seconds: 200,
            },
        )
        .await
        .expect("grant");
    let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    let access = FederationConsumerAccess::new(consumer_id, consumer_workspace);
    assert!(matches!(
        reader
            .retrieve(&access, &RetrievalRequest::new("Expiring", 200))
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));

    sqlx::query("DROP TRIGGER memory_federation_events_no_update")
        .execute(&owner.pool)
        .await
        .expect("drop trigger only to simulate corruption");
    sqlx::query(
        "UPDATE memory_federation_events SET consumer_workspace_sha256 = ? WHERE action = 'grant'",
    )
    .bind(workspace("corrupt-binding").as_str())
    .execute(&owner.pool)
    .await
    .expect("corrupt event");
    assert!(matches!(
        reader
            .retrieve(&access, &RetrievalRequest::new("Expiring", 150))
            .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn five_agents_keep_private_stores_and_only_explicit_consumers_federate() {
    let temp = TempDir::new().expect("temp dir");
    let ids = (60..65).map(agent_id).collect::<Vec<_>>();
    let layouts = ids
        .iter()
        .map(|agent_id| layout(&temp, agent_id))
        .collect::<Vec<_>>();
    let mut stores = Vec::new();
    for (index, agent_layout) in layouts.iter().enumerate() {
        let store = CognitiveStore::open(agent_layout).await.expect("store");
        let access = CognitiveAccess::agent_private(ids[index].clone());
        let citation = store
            .append_source(
                &access,
                &source(
                    CognitiveScope::AgentPrivate,
                    &format!("source-{index}"),
                    &format!("private-agent-{index}-constellation"),
                ),
            )
            .await
            .expect("source");
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("memory-{index}"),
                    revision: memory_revision(
                        CognitiveScope::AgentPrivate,
                        &format!("private-agent-{index}-constellation"),
                        citation,
                    ),
                },
            )
            .await
            .expect("memory");
        stores.push(store);
    }
    for left in 0..stores.len() {
        for right in (left + 1)..stores.len() {
            assert_ne!(stores[left].path(), stores[right].path());
        }
    }
    let shared_workspace = workspace("five-agent-consumer");
    for consumer_index in [1usize, 3usize] {
        stores[0]
            .grant_federated_recall(
                &CognitiveAccess::agent_private(ids[0].clone()),
                &FederationGrantRequest {
                    consumer_agent_id: ids[consumer_index].clone(),
                    scope: FederationGrantScope::new(
                        CognitiveScope::AgentPrivate,
                        shared_workspace.clone(),
                    ),
                    effective_at_unix_seconds: 100,
                    expires_at_unix_seconds: 1_000,
                },
            )
            .await
            .expect("grant");
    }

    for consumer_index in 1..5 {
        let set =
            FederatedRecallSet::discover(ids[consumer_index].clone(), layouts.clone(), 150).await;
        let access =
            FederationConsumerAccess::new(ids[consumer_index].clone(), shared_workspace.clone());
        let batch = set
            .retrieve(&access, &RetrievalRequest::new("constellation", 150))
            .await
            .expect("set retrieval");
        if [1usize, 3usize].contains(&consumer_index) {
            assert_eq!(batch.coverage.requested_sources, 1);
            assert_eq!(batch.coverage.completed_sources, 1);
            assert_eq!(batch.coverage.failed_sources, 0);
            assert_eq!(batch.candidates.len(), 1);
            assert_eq!(batch.candidates[0].source_agent_id, ids[0]);
            assert_eq!(
                batch.candidates[0].candidate.memory.content,
                "private-agent-0-constellation"
            );
        } else {
            assert_eq!(batch.coverage.requested_sources, 0);
            assert_eq!(batch.coverage.completed_sources, 0);
            assert_eq!(batch.coverage.failed_sources, 0);
            assert!(batch.candidates.is_empty());
        }
    }
}

#[tokio::test]
async fn same_second_same_query_allocates_fresh_v2_attempt_identity() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(88);
    let consumer_id = agent_id(89);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_access = CognitiveAccess::agent_private(owner_id.clone());
    let consumer_workspace = workspace("attempt-identity");
    owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace,
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");
    let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover")
        .pop()
        .expect("reader");
    let request = RetrievalRequest::new("same-second-query", 150);
    let first = reader
        .product_attempt_binding_for_test(&request)
        .expect("first binding");
    let second = reader
        .product_attempt_binding_for_test(&request)
        .expect("second binding");
    assert_ne!(first.0, second.0);
    assert_ne!(first.1, second.1);
}

#[tokio::test]
async fn revoked_peer_is_explicit_partial_coverage_not_silent_empty() {
    let temp = TempDir::new().expect("temp dir");
    let consumer_id = agent_id(90);
    let consumer_workspace = workspace("partial-consumer");
    let mut readers = Vec::new();
    let mut owners = Vec::new();

    for offset in 0..2_u8 {
        let owner_id = agent_id(91 + offset);
        let owner_layout = layout(&temp, &owner_id);
        let owner = CognitiveStore::open(&owner_layout)
            .await
            .expect("owner store");
        let owner_access = CognitiveAccess::agent_private(owner_id.clone());
        let citation = owner
            .append_source(
                &owner_access,
                &source(
                    CognitiveScope::AgentPrivate,
                    &format!("partial-source-{offset}"),
                    &format!("partial federation evidence {offset}"),
                ),
            )
            .await
            .expect("source");
        owner
            .remember_memory(
                &owner_access,
                &MemoryDraft {
                    stable_key: format!("partial-memory-{offset}"),
                    revision: memory_revision(
                        CognitiveScope::AgentPrivate,
                        &format!("partial federation evidence {offset}"),
                        citation,
                    ),
                },
            )
            .await
            .expect("memory");
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
        let reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
            .await
            .expect("discover")
            .pop()
            .expect("reader");
        readers.push(reader);
        owners.push((owner, owner_access, capability));
    }

    let set = FederatedRecallSet::new(consumer_id.clone(), readers).expect("recall set");
    owners[1]
        .0
        .revoke_federated_recall(&owners[1].1, &owners[1].2, 151)
        .await
        .expect("revoke second peer");

    let batch = set
        .retrieve(
            &FederationConsumerAccess::new(consumer_id, consumer_workspace),
            &RetrievalRequest::new("partial federation", 152),
        )
        .await
        .expect("partial retrieval");
    assert_eq!(batch.coverage.requested_sources, 2);
    assert_eq!(batch.coverage.completed_sources, 1);
    assert_eq!(batch.coverage.failed_sources, 1);
    assert_eq!(batch.admission_expires_unix_ms, Some(154_000));
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, agent_id(91));
}
