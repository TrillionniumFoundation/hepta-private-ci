use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::sync::Barrier;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MAX_RETRIEVAL_CHANNEL_CANDIDATES;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalChannel;
use crate::RetrievalRequest;
use crate::RevalidationDrift;
use crate::RevalidationStatus;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

fn revision(scope: CognitiveScope, content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

#[tokio::test]
async fn retrieval_rrf_is_deterministic_explainable_and_revalidated() {
    let temp = TempDir::new().expect("temp dir");
    let agent_id = agent_id(5);
    let store = CognitiveStore::open(&layout(&temp, &agent_id))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(agent_id);
    let ada_content = "Ada studied the analytical engine.";
    let ada_memory = store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "ada-source", ada_content),
            &MemoryDraft {
                stable_key: "ada-engine".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, ada_content),
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada Lovelace".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "analytical-engine".to_string(),
                        entity_type: "machine".to_string(),
                        label: "Analytical Engine".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "studied".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "analytical-engine".to_string(),
                    relation: "studied".to_string(),
                }],
            },
        )
        .await
        .expect("Ada memory")
        .memory;
    let charles_content = "Charles designed the difference engine.";
    store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "charles-source",
                charles_content,
            ),
            &MemoryDraft {
                stable_key: "charles-engine".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, charles_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("Charles memory");

    let request = RetrievalRequest::new("Ada", 200);
    let first = store
        .retrieve_memory_candidates(&access, &request)
        .await
        .expect("first retrieval");
    let second = store
        .retrieve_memory_candidates(&access, &request)
        .await
        .expect("second retrieval");
    assert_eq!(second, first);
    assert_eq!(first.candidates[0].memory.id, ada_memory.id);
    assert_eq!(
        first.candidates[0].channels,
        vec![
            RetrievalChannel::MemoryFts,
            RetrievalChannel::EntityFts,
            RetrievalChannel::GraphOneHop,
            RetrievalChannel::Recency,
        ]
    );
    let explanation = store
        .explain_memory_head(&access, &ada_memory.id.memory_id)
        .await
        .expect("explanation");
    assert_eq!(
        explanation.citations[0].content,
        b"Ada studied the analytical engine."
    );
    assert!(matches!(
        store
            .revalidate_memory_candidate(&access, &first.candidates[0].revalidation, 200,)
            .await
            .expect("revalidation"),
        RevalidationStatus::Current(_)
    ));

    let mut source_drift = first.candidates[0].revalidation.clone();
    source_drift.citations[0].content_sha256 = Sha256Digest::for_bytes(b"different source");
    assert_eq!(
        store
            .revalidate_memory_candidate(&access, &source_drift, 200)
            .await
            .expect("source drift"),
        RevalidationStatus::Stale(RevalidationDrift::SourceHash)
    );

    let generation_content = "A new scoped memory advances the projection.";
    store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "generation-source",
                generation_content,
            ),
            &MemoryDraft {
                stable_key: "generation-memory".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, generation_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("generation advance");
    assert_eq!(
        store
            .revalidate_memory_candidate(&access, &first.candidates[0].revalidation, 200,)
            .await
            .expect("generation drift"),
        RevalidationStatus::Stale(RevalidationDrift::KgProjectionGeneration)
    );

    let corrected_content = "Ada wrote the first published algorithm.";
    store
        .correct_with_kg(
            &access,
            &ada_memory.id.memory_id,
            1,
            &source(
                CognitiveScope::AgentPrivate,
                "ada-correction",
                corrected_content,
            ),
            &revision(CognitiveScope::AgentPrivate, corrected_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("correction");
    assert_eq!(
        store
            .revalidate_memory_candidate(&access, &first.candidates[0].revalidation, 200,)
            .await
            .expect("head drift"),
        RevalidationStatus::Stale(RevalidationDrift::HeadRevision)
    );
}

#[tokio::test]
async fn retrieval_fails_closed_across_agent_and_workspace_scope() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(6);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let allowed_workspace = workspace("allowed");
    let denied_workspace = workspace("denied");
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: allowed_workspace.clone(),
    };
    let allowed = CognitiveAccess::workspace_private(owner.clone(), allowed_workspace);
    let private_content = "Private astronomy notes.";
    let memory = store
        .remember_with_kg(
            &allowed,
            &source(scope.clone(), "private-source", private_content),
            &MemoryDraft {
                stable_key: "private-notes".to_string(),
                revision: revision(scope, private_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("memory")
        .memory;

    let denied = CognitiveAccess::workspace_private(owner, denied_workspace);
    assert!(
        store
            .retrieve_memory_candidates(&denied, &RetrievalRequest::new("astronomy", 200))
            .await
            .expect("scoped retrieval")
            .candidates
            .is_empty()
    );
    assert!(matches!(
        store.read_memory_head(&denied, &memory.id.memory_id).await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    let other_agent = CognitiveAccess::agent_private(agent_id(7));
    assert!(matches!(
        store
            .retrieve_memory_candidates(&other_agent, &RetrievalRequest::new("astronomy", 200),)
            .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
}

#[tokio::test]
async fn batch_revalidation_is_ordered_and_uses_one_read_snapshot_across_generation_drift() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(8);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace_sha256 = workspace("batch-snapshot-workspace");
    let access = CognitiveAccess::workspace_private(owner, workspace_sha256.clone());
    for (stable_key, event_key, content, scope) in [
        (
            "snapshot-alpha",
            "snapshot-alpha-source",
            "Snapshot beacon alpha remains durable.",
            CognitiveScope::AgentPrivate,
        ),
        (
            "snapshot-beta",
            "snapshot-beta-source",
            "Snapshot beacon beta remains durable.",
            CognitiveScope::WorkspacePrivate { workspace_sha256 },
        ),
    ] {
        store
            .remember_with_kg(
                &access,
                &source(scope.clone(), event_key, content),
                &MemoryDraft {
                    stable_key: stable_key.to_string(),
                    revision: revision(scope, content),
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("seed snapshot memory");
    }
    let retrieved = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Snapshot beacon", 200))
        .await
        .expect("retrieve both memories");
    assert_eq!(retrieved.candidates.len(), 2);
    let bindings = retrieved
        .candidates
        .iter()
        .map(|candidate| candidate.revalidation.clone())
        .collect::<Vec<_>>();

    let after_first = Arc::new(Barrier::new(2));
    let after_write = Arc::new(Barrier::new(2));
    let batch_store = store.clone();
    let batch_access = access.clone();
    let batch_bindings = bindings.clone();
    let batch_after_first = Arc::clone(&after_first);
    let batch_after_write = Arc::clone(&after_write);
    let batch = tokio::spawn(async move {
        batch_store
            .revalidate_memory_candidates_with_test_hook(
                &batch_access,
                &batch_bindings,
                200,
                move |index| {
                    let after_first = Arc::clone(&batch_after_first);
                    let after_write = Arc::clone(&batch_after_write);
                    async move {
                        if index == 0 {
                            after_first.wait().await;
                            after_write.wait().await;
                        }
                    }
                },
            )
            .await
    });

    after_first.wait().await;
    let drift_content = "A concurrent writer advances the projection generation.";
    store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "snapshot-generation-drift",
                drift_content,
            ),
            &MemoryDraft {
                stable_key: "snapshot-generation-drift".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, drift_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("concurrent generation advance");
    let workspace_drift_content = "A concurrent writer also advances the workspace projection.";
    let workspace_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace("batch-snapshot-workspace"),
    };
    store
        .remember_with_kg(
            &access,
            &source(
                workspace_scope.clone(),
                "snapshot-workspace-generation-drift",
                workspace_drift_content,
            ),
            &MemoryDraft {
                stable_key: "snapshot-workspace-generation-drift".to_string(),
                revision: revision(workspace_scope, workspace_drift_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("concurrent workspace generation advance");
    after_write.wait().await;

    let statuses = batch
        .await
        .expect("batch task")
        .expect("batch revalidation");
    assert_eq!(statuses.len(), bindings.len());
    for (status, binding) in statuses.iter().zip(&bindings) {
        let RevalidationStatus::Current(explanation) = status else {
            panic!("one read snapshot must keep every original binding current");
        };
        assert_eq!(explanation.memory.id, binding.memory);
        assert_eq!(
            explanation.kg_projection_generation,
            binding.kg_projection_generation
        );
    }

    assert!(
        store
            .revalidate_memory_candidates(&access, &bindings, 200)
            .await
            .expect("fresh revalidation")
            .iter()
            .all(|status| {
                *status == RevalidationStatus::Stale(RevalidationDrift::KgProjectionGeneration)
            })
    );
}

#[tokio::test]
async fn shared_canonical_entity_keeps_surviving_support_after_peer_correction_and_forget() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(9);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let shared_facts = |project_key: &str, project_label: &str| KgFactSetDraft {
        entities: vec![
            KgEntityFactDraft {
                key: "shared-beacon".to_string(),
                entity_type: "concept".to_string(),
                label: "Shared Beacon".to_string(),
            },
            KgEntityFactDraft {
                key: project_key.to_string(),
                entity_type: "project".to_string(),
                label: project_label.to_string(),
            },
        ],
        relations: vec![KgRelationFactDraft {
            key: "supports".to_string(),
            from_entity_key: "shared-beacon".to_string(),
            to_entity_key: project_key.to_string(),
            relation: "supports".to_string(),
        }],
    };
    let first_content = "The first independent fact support.";
    let first = store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "shared-first", first_content),
            &MemoryDraft {
                stable_key: "shared-first".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, first_content),
            },
            &shared_facts("project-alpha", "Project Alpha"),
        )
        .await
        .expect("first shared support")
        .memory;
    let second_content = "The second independent fact support.";
    let second = store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "shared-second",
                second_content,
            ),
            &MemoryDraft {
                stable_key: "shared-second".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, second_content),
            },
            &shared_facts("project-beta", "Project Beta"),
        )
        .await
        .expect("second shared support")
        .memory;

    let initial = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Shared Beacon", 200))
        .await
        .expect("initial shared retrieval");
    for memory in [&first, &second] {
        let candidate = initial
            .candidates
            .iter()
            .find(|candidate| candidate.memory.id == memory.id)
            .expect("each provenance occurrence is retrieved");
        assert!(candidate.channels.contains(&RetrievalChannel::EntityFts));
        assert!(candidate.channels.contains(&RetrievalChannel::GraphOneHop));
    }

    let corrected_content = "The first support no longer asserts graph facts.";
    store
        .correct_with_kg(
            &access,
            &first.id.memory_id,
            1,
            &source(
                CognitiveScope::AgentPrivate,
                "shared-first-correction",
                corrected_content,
            ),
            &revision(CognitiveScope::AgentPrivate, corrected_content),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("correct first support");
    let after_correction = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Shared Beacon", 200))
        .await
        .expect("shared retrieval after correction");
    let surviving = after_correction
        .candidates
        .iter()
        .find(|candidate| candidate.memory.id == second.id)
        .expect("second support survives peer correction");
    assert!(surviving.channels.contains(&RetrievalChannel::EntityFts));
    assert!(surviving.channels.contains(&RetrievalChannel::GraphOneHop));
    if let Some(corrected) = after_correction
        .candidates
        .iter()
        .find(|candidate| candidate.memory.id.memory_id == first.id.memory_id)
    {
        assert_eq!(corrected.memory.id.revision, 2);
        assert!(!corrected.channels.contains(&RetrievalChannel::EntityFts));
        assert!(!corrected.channels.contains(&RetrievalChannel::GraphOneHop));
    }

    store
        .forget_with_kg(
            &access,
            &first.id.memory_id,
            2,
            &source(
                CognitiveScope::AgentPrivate,
                "shared-first-forget",
                "explicitly withdraw first support",
            ),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicitly withdraw first support".to_string(),
                valid_from_unix_seconds: 200,
                citations: Vec::new(),
            },
        )
        .await
        .expect("forget first support");
    let after_forget = store
        .retrieve_memory_candidates(&access, &RetrievalRequest::new("Shared Beacon", 200))
        .await
        .expect("shared retrieval after forget");
    let surviving = after_forget
        .candidates
        .iter()
        .find(|candidate| candidate.memory.id == second.id)
        .expect("second support survives peer forget");
    assert!(surviving.channels.contains(&RetrievalChannel::EntityFts));
    assert!(surviving.channels.contains(&RetrievalChannel::GraphOneHop));
    assert!(
        after_forget
            .candidates
            .iter()
            .all(|candidate| candidate.memory.id.memory_id != first.id.memory_id)
    );
}

#[tokio::test]
async fn graph_channel_has_one_global_bound_across_deduplicated_canonical_seeds() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(10);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let mut alpha = Vec::new();
    let mut beta = Vec::new();
    let mut generation = None;
    for (group, shared_key, shared_label, memories) in [
        ("alpha", "global-alpha", "Global Alpha", &mut alpha),
        ("beta", "global-beta", "Global Beta", &mut beta),
    ] {
        for index in 0..20 {
            let content = format!("Graph bound evidence {group} {index}.");
            let neighbor_key = format!("{group}-neighbor-{index:02}");
            let written = store
                .remember_with_kg(
                    &access,
                    &source(
                        scope.clone(),
                        &format!("graph-bound-{group}-{index:02}"),
                        &content,
                    ),
                    &MemoryDraft {
                        stable_key: format!("graph-bound-{group}-{index:02}"),
                        revision: revision(scope.clone(), &content),
                    },
                    &KgFactSetDraft {
                        entities: vec![
                            KgEntityFactDraft {
                                key: shared_key.to_string(),
                                entity_type: "concept".to_string(),
                                label: shared_label.to_string(),
                            },
                            KgEntityFactDraft {
                                key: neighbor_key.clone(),
                                entity_type: "evidence".to_string(),
                                label: format!("{group} Neighbor {index:02}"),
                            },
                        ],
                        relations: vec![KgRelationFactDraft {
                            key: "links".to_string(),
                            from_entity_key: shared_key.to_string(),
                            to_entity_key: neighbor_key,
                            relation: "links_to".to_string(),
                        }],
                    },
                )
                .await
                .expect("bounded graph support");
            generation = Some(written.projection.generation);
            memories.push(written.memory.id);
        }
    }
    let generation = generation.expect("projection generation");
    let alpha_entity = canonical_entity_id(&owner, &scope, "global-alpha");
    let beta_entity = canonical_entity_id(&owner, &scope, "global-beta");

    let forward = store
        .graph_channel_for_test(
            &[
                (
                    scope.clone(),
                    generation,
                    alpha_entity.clone(),
                    alpha[0].clone(),
                ),
                (
                    scope.clone(),
                    generation,
                    alpha_entity.clone(),
                    alpha[1].clone(),
                ),
                (
                    scope.clone(),
                    generation,
                    beta_entity.clone(),
                    beta[0].clone(),
                ),
            ],
            200,
        )
        .await
        .expect("forward bounded graph channel");
    assert_graph_bound_distribution(&forward, &alpha, &beta, 20, 12);

    let reverse = store
        .graph_channel_for_test(
            &[
                (
                    scope.clone(),
                    generation,
                    beta_entity.clone(),
                    beta[0].clone(),
                ),
                (scope.clone(), generation, beta_entity, beta[1].clone()),
                (scope, generation, alpha_entity, alpha[0].clone()),
            ],
            200,
        )
        .await
        .expect("reverse bounded graph channel");
    assert_graph_bound_distribution(&reverse, &beta, &alpha, 20, 12);
}

fn assert_graph_bound_distribution(
    actual: &[crate::MemoryRevisionId],
    first_group: &[crate::MemoryRevisionId],
    second_group: &[crate::MemoryRevisionId],
    expected_first: usize,
    expected_second: usize,
) {
    let identity = |memory: &crate::MemoryRevisionId| {
        format!("{}:{}", memory.memory_id.as_str(), memory.revision)
    };
    let first = first_group.iter().map(identity).collect::<BTreeSet<_>>();
    let second = second_group.iter().map(identity).collect::<BTreeSet<_>>();
    let actual = actual.iter().map(identity).collect::<Vec<_>>();
    assert_eq!(actual.len(), MAX_RETRIEVAL_CHANNEL_CANDIDATES);
    assert_eq!(actual.iter().collect::<BTreeSet<_>>().len(), actual.len());
    assert_eq!(
        actual
            .iter()
            .filter(|memory| first.contains(*memory))
            .count(),
        expected_first
    );
    assert_eq!(
        actual
            .iter()
            .filter(|memory| second.contains(*memory))
            .count(),
        expected_second
    );
}
