use super::*;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryRevisionDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

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

async fn remember(
    store: &CognitiveStore,
    access: &CognitiveAccess,
    key: &str,
    draft: MemoryRevisionDraft,
) {
    store
        .remember_with_kg(
            access,
            &source(draft.scope.clone(), key, &draft.content),
            &MemoryDraft {
                stable_key: key.to_string(),
                revision: draft,
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed memory");
}

#[tokio::test]
async fn saturated_channels_observe_limits_before_dedup_and_preserve_top_four() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(/*suffix*/ 42);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    for index in 0..35 {
        remember(
            &store,
            &access,
            &format!("beacon-{index}"),
            revision(CognitiveScope::AgentPrivate, "Beacon supported fact."),
        )
        .await;
    }
    store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "entity-source",
                "Beacon entity fact.",
            ),
            &MemoryDraft {
                stable_key: "entities".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, "Beacon entity fact."),
            },
            &KgFactSetDraft {
                entities: (0..33)
                    .map(|index| KgEntityFactDraft {
                        key: format!("entity-{index}"),
                        entity_type: "topic".to_string(),
                        label: format!("Beacon entity {index}"),
                    })
                    .collect(),
                relations: Vec::new(),
            },
        )
        .await
        .expect("many entities in one memory");
    let request = RetrievalRequest::new("Beacon", /*now_unix_seconds*/ 200);
    let observation = store
        .observe_memory_retrieval(&access, &request)
        .await
        .expect("observation");
    let legacy = store
        .retrieve_memory_candidates(&access, &request)
        .await
        .expect("legacy");
    assert_eq!(observation.batch(), &legacy);
    assert_eq!(observation.batch().candidates.len(), MAX_RETRIEVAL_RESULTS);
    assert!(observation.candidates().len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES);
    assert_eq!(
        observation.omitted_count(),
        observation.candidates().len() - MAX_RETRIEVAL_RESULTS
    );
    assert_eq!(
        observation.channels(),
        &[
            RetrievalChannelObservation {
                channel: RetrievalChannel::MemoryFts,
                candidate_count: 32,
                limit: RetrievalLimitObservation::LimitReached
            },
            RetrievalChannelObservation {
                channel: RetrievalChannel::EntityFts,
                candidate_count: 1,
                limit: RetrievalLimitObservation::LimitReached
            },
            RetrievalChannelObservation {
                channel: RetrievalChannel::GraphOneHop,
                candidate_count: 0,
                limit: RetrievalLimitObservation::Exhausted
            },
            RetrievalChannelObservation {
                channel: RetrievalChannel::Recency,
                candidate_count: 32,
                limit: RetrievalLimitObservation::LimitReached
            },
        ]
    );
    assert_eq!(
        observation,
        store
            .observe_memory_retrieval(&access, &request)
            .await
            .expect("repeat")
    );
}

#[tokio::test]
async fn observation_excludes_other_scopes_expired_and_withdrawn_memories() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(/*suffix*/ 43);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace_a = workspace("a");
    let access = CognitiveAccess::workspace_private(owner.clone(), workspace_a.clone());
    let scope_a = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_a,
    };
    remember(
        &store,
        &access,
        "a",
        revision(scope_a.clone(), "Beacon in workspace a."),
    )
    .await;
    let scope_b = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace("b"),
    };
    let access_b = CognitiveAccess::workspace_private(owner, workspace("b"));
    remember(
        &store,
        &access_b,
        "b",
        revision(scope_b, "Beacon in workspace b."),
    )
    .await;
    let mut expired = revision(CognitiveScope::AgentPrivate, "Beacon expired.");
    expired.valid_to_unix_seconds = Some(150);
    remember(&store, &access, "expired", expired).await;
    let request = RetrievalRequest::new("Beacon", /*now_unix_seconds*/ 200);
    let before = store
        .observe_memory_retrieval(&access, &request)
        .await
        .expect("before");
    assert_eq!(before.candidates().len(), 1);
    assert_eq!(before.candidates()[0].revalidation.scope, scope_a);
    let binding = &before.candidates()[0].revalidation;
    store
        .forget_with_kg(
            &access,
            &binding.memory.memory_id,
            binding.memory.revision,
            &source(scope_a.clone(), "withdrawal", "withdraw"),
            &ForgetMemoryDraft {
                scope: scope_a,
                reason: "withdraw".to_string(),
                valid_from_unix_seconds: 100,
                citations: Vec::new(),
            },
        )
        .await
        .expect("withdraw");
    let after = store
        .observe_memory_retrieval(&access, &request)
        .await
        .expect("after");
    assert!(after.candidates().is_empty());
    assert!(after.batch().candidates.is_empty());
    assert_eq!(after.omitted_count(), 0);
    assert_ne!(before.observation_sha256(), after.observation_sha256());
    let denied = CognitiveAccess::agent_private(agent_id(/*suffix*/ 44));
    assert!(matches!(
        store.observe_memory_retrieval(&denied, &request).await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
}

#[tokio::test]
async fn omitted_candidate_content_is_bound_even_when_selected_ids_do_not_change() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(/*suffix*/ 45);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    for index in 0..4 {
        remember(
            &store,
            &access,
            &format!("beacon-{index}"),
            revision(CognitiveScope::AgentPrivate, "Beacon fact."),
        )
        .await;
    }
    remember(
        &store,
        &access,
        "tail",
        revision(CognitiveScope::AgentPrivate, "Unmatched old tail."),
    )
    .await;
    let request = RetrievalRequest::new("Beacon", /*now_unix_seconds*/ 200);
    let before = store
        .observe_memory_retrieval(&access, &request)
        .await
        .expect("before");
    let tail = before
        .candidates()
        .iter()
        .find(|candidate| candidate.channels == [RetrievalChannel::Recency])
        .expect("omitted tail");
    assert_eq!(before.omitted_count(), 1);
    store
        .correct_with_kg(
            &access,
            &tail.revalidation.memory.memory_id,
            tail.revalidation.memory.revision,
            &source(
                CognitiveScope::AgentPrivate,
                "tail-correction",
                "Unmatched new tail.",
            ),
            &revision(CognitiveScope::AgentPrivate, "Unmatched new tail."),
            &KgFactSetDraft::default(),
        )
        .await
        .expect("correct omitted tail");
    let after = store
        .observe_memory_retrieval(&access, &request)
        .await
        .expect("after");
    let selected = |observation: &RetrievalObservation| {
        observation
            .batch()
            .candidates
            .iter()
            .map(|candidate| candidate.memory.id.memory_id.clone())
            .collect::<BTreeSet<_>>()
    };
    assert_eq!(selected(&before), selected(&after));
    assert_eq!(after.omitted_count(), 1);
    let corrected = after
        .candidates()
        .iter()
        .find(|candidate| {
            candidate.revalidation.memory.memory_id == tail.revalidation.memory.memory_id
        })
        .expect("corrected tail");
    assert_eq!(
        corrected.revalidation.content_sha256,
        Sha256Digest::for_bytes(b"Unmatched new tail.")
    );
    assert_ne!(before.observation_sha256(), after.observation_sha256());
}
