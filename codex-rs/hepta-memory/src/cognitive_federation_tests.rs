use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveRuntime;
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
use crate::ForgetMemoryDraft;
use crate::MemoryDraft;
use crate::RetrievalRequest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

struct FederationRecoveryVerifier;

impl crate::ProductionAuthorityVerifier for FederationRecoveryVerifier {
    fn verify(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &codex_hepta_contracts::AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id == expected_agent {
            Ok(())
        } else {
            Err("federation recovery authority owner mismatch".to_string())
        }
    }
}

fn federation_recovery_authority(
    owner: &codex_hepta_contracts::AgentId,
) -> crate::ProductionAuthorityLease {
    crate::ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        codex_hepta_contracts::Sha256Digest::for_bytes(b"federation-recovery-grant"),
        17,
        23,
        u64::MAX,
        crate::ProductionAuthorityToken::from_verified_bytes(b"federation-recovery-fence".to_vec())
            .expect("valid federation recovery token"),
    )
    .expect("valid federation recovery authority")
}

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
    let (batch, observed_frontier) = readers[0]
        .retrieve_with_frontier(&access, &RetrievalRequest::new("orbital", 150))
        .await
        .expect("federated retrieval");
    assert_eq!(observed_frontier, 1);
    assert_eq!(batch.candidates.len(), 1);
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
            assert_eq!(batch.candidates.len(), 1);
            assert_eq!(batch.candidates[0].source_agent_id, ids[0]);
            assert_eq!(
                batch.candidates[0].candidate.memory.content,
                "private-agent-0-constellation"
            );
        } else {
            assert!(batch.candidates.is_empty());
        }
    }
}

#[tokio::test]
async fn recovered_owner_revocation_fences_predecessor_readers() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(90);
    let consumer_id = agent_id(91);
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
                "recovery-federation-source",
                "Recovered federation evidence.",
            ),
        )
        .await
        .expect("owner source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "recovery-federation-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Recovered federation evidence.",
                    citation,
                ),
            },
        )
        .await
        .expect("owner memory");
    let consumer_workspace = workspace("recovery-federation-consumer");
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
        .expect("grant before recovery");
    let old_reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover predecessor")
        .pop()
        .expect("predecessor reader");
    let consumer_access =
        FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace.clone());
    let old_batch = old_reader
        .retrieve(
            &consumer_access,
            &RetrievalRequest::new("Recovered federation", 150),
        )
        .await
        .expect("predecessor retrieval");
    assert_eq!(old_batch.candidates.len(), 1);
    let old_binding = old_batch.candidates[0].revalidation.clone();
    let retained = owner.recovery_anchor().await.expect("current owner cut");
    let predecessor_path = owner.path().to_path_buf();
    old_reader.close_for_recovery_test().await;
    owner.pool.close().await;
    drop(owner);

    let authority = federation_recovery_authority(&owner_id);
    let recovered = CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &authority,
        &FederationRecoveryVerifier,
    )
    .await
    .expect("recover current owner generation");
    assert_ne!(recovered.path(), predecessor_path.as_path());
    recovered
        .revoke_federated_recall(&owner_access, &capability, 151)
        .await
        .expect("revoke on recovered generation");

    assert!(
        FederatedMemoryReader::discover(&owner_layout, &consumer_id, 152)
            .await
            .expect("discover current generation")
            .is_empty()
    );
    let retired_reader = FederatedMemoryReader::discover_retired_generation_for_test(
        &owner_layout,
        predecessor_path,
        &consumer_id,
        152,
    )
    .await
    .expect("bind retired owner generation")
    .pop()
    .expect("retired reader");
    assert!(matches!(
        retired_reader
            .retrieve(
                &consumer_access,
                &RetrievalRequest::new("Recovered federation", 152),
            )
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    assert!(matches!(
        retired_reader
            .revalidate(&consumer_access, &old_binding, 152)
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    let consumer_store = CognitiveStore::open(&layout(&temp, &consumer_id))
        .await
        .expect("consumer store");
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer_store))
        .with_federation_sources(consumer_id.clone(), vec![owner_layout.clone()]);
    let (batch, coverage) = runtime
        .retrieve_product_federated(
            &consumer_access,
            &RetrievalRequest::new("Recovered federation", 152),
        )
        .await
        .expect("product retrieval after recovered revoke");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 0);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.failed_peers, 0);

    std::fs::remove_file(owner_layout.cognitive_root().join(".cognitive-active-v1"))
        .expect("remove recovered owner pointer for rollback regression");
    assert!(matches!(
        FederatedMemoryReader::discover(&owner_layout, &consumer_id, 153).await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn recovered_owner_revision_and_forget_fence_predecessor_reader() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(92);
    let consumer_id = agent_id(93);
    let owner_layout = layout(&temp, &owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_access = CognitiveAccess::agent_private(owner_id.clone());
    let correction_source = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "recovery-correction-source",
                "Predecessor recovery state needs correction.",
            ),
        )
        .await
        .expect("correction source");
    let forgotten_source = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "recovery-forget-source",
                "Predecessor recovery state must be forgotten.",
            ),
        )
        .await
        .expect("forget source");
    let corrected_memory = owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "recovery-corrected-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Predecessor recovery state needs correction.",
                    correction_source.clone(),
                ),
            },
        )
        .await
        .expect("memory to correct");
    let forgotten_memory = owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "recovery-forgotten-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "Predecessor recovery state must be forgotten.",
                    forgotten_source.clone(),
                ),
            },
        )
        .await
        .expect("memory to forget");
    let consumer_workspace = workspace("recovery-revision-consumer");
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
        .expect("grant before recovery");
    let old_reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 150)
        .await
        .expect("discover predecessor")
        .pop()
        .expect("predecessor reader");
    let consumer_access =
        FederationConsumerAccess::new(consumer_id.clone(), consumer_workspace.clone());
    let old_batch = old_reader
        .retrieve(
            &consumer_access,
            &RetrievalRequest::new("Predecessor recovery state", 150),
        )
        .await
        .expect("predecessor retrieval");
    assert_eq!(old_batch.candidates.len(), 2);
    let old_bindings = old_batch
        .candidates
        .iter()
        .map(|candidate| candidate.revalidation.clone())
        .collect::<Vec<_>>();
    let retained = owner.recovery_anchor().await.expect("current owner cut");
    let predecessor_path = owner.path().to_path_buf();
    old_reader.close_for_recovery_test().await;
    owner.pool.close().await;
    drop(owner);

    let authority = federation_recovery_authority(&owner_id);
    let recovered = CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &authority,
        &FederationRecoveryVerifier,
    )
    .await
    .expect("recover current owner generation");
    let mut corrected = memory_revision(
        CognitiveScope::AgentPrivate,
        "Current corrected recovery state.",
        correction_source,
    );
    corrected.valid_from_unix_seconds = 151;
    recovered
        .correct_memory(&owner_access, &corrected_memory.id.memory_id, 1, &corrected)
        .await
        .expect("correct on recovered generation");
    recovered
        .forget_memory(
            &owner_access,
            &forgotten_memory.id.memory_id,
            1,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "recovery_forget".to_string(),
                valid_from_unix_seconds: 151,
                citations: vec![forgotten_source],
            },
        )
        .await
        .expect("forget on recovered generation");

    let retired_reader = FederatedMemoryReader::discover_retired_generation_for_test(
        &owner_layout,
        predecessor_path,
        &consumer_id,
        152,
    )
    .await
    .expect("bind retired owner generation")
    .pop()
    .expect("retired reader");
    assert!(matches!(
        retired_reader
            .retrieve(
                &consumer_access,
                &RetrievalRequest::new("Predecessor recovery state", 152),
            )
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    for binding in &old_bindings {
        assert!(matches!(
            retired_reader
                .revalidate(&consumer_access, binding, 152)
                .await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
    }
    let fresh_reader = FederatedMemoryReader::discover(&owner_layout, &consumer_id, 152)
        .await
        .expect("discover recovered owner")
        .pop()
        .expect("current reader");
    let fresh_batch = fresh_reader
        .retrieve(
            &consumer_access,
            &RetrievalRequest::new("recovery state", 152),
        )
        .await
        .expect("current retrieval");
    let contents = fresh_batch
        .candidates
        .iter()
        .map(|candidate| candidate.candidate.memory.content.as_str())
        .collect::<Vec<_>>();
    assert_eq!(contents, vec!["Current corrected recovery state."]);
    assert!(contents.iter().all(|content| {
        !content.contains("needs correction") && !content.contains("must be forgotten")
    }));

    let consumer_store = CognitiveStore::open(&layout(&temp, &consumer_id))
        .await
        .expect("consumer store");
    let runtime = CognitiveRuntime::from_open_result(Ok(consumer_store))
        .with_federation_sources(consumer_id, vec![owner_layout]);
    let (product_batch, coverage) = runtime
        .retrieve_product_federated(
            &consumer_access,
            &RetrievalRequest::new("recovery state", 152),
        )
        .await
        .expect("product retrieval from recovered owner");
    assert_eq!(coverage.completed_peers, 1);
    assert_eq!(coverage.failed_peers, 0);
    assert_eq!(product_batch.candidates.len(), 1);
    assert_eq!(
        product_batch.candidates[0].candidate.memory.content,
        "Current corrected recovery state."
    );
}
