use super::*;
use crate::ForgetMemoryDraft;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
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
            RetrievalChannelObservation {
                channel: RetrievalChannel::Causal,
                candidate_count: 0,
                limit: RetrievalLimitObservation::Exhausted
            },
            RetrievalChannelObservation {
                channel: RetrievalChannel::Procedural,
                candidate_count: 0,
                limit: RetrievalLimitObservation::Exhausted
            },
            RetrievalChannelObservation {
                channel: RetrievalChannel::ContradictionSupport,
                candidate_count: 0,
                limit: RetrievalLimitObservation::Exhausted
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
async fn typed_kg_relations_feed_only_their_declared_retrieval_channels() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(/*suffix*/ 91);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    let content = "Beacon cause procedure contradiction.";
    store
        .remember_with_kg(
            &access,
            &source(CognitiveScope::AgentPrivate, "typed-relations", content),
            &MemoryDraft {
                stable_key: "typed-relations".to_string(),
                revision: revision(CognitiveScope::AgentPrivate, content),
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "beacon".to_string(),
                        entity_type: "topic".to_string(),
                        label: "Beacon".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "target".to_string(),
                        entity_type: "topic".to_string(),
                        label: "Target".to_string(),
                    },
                ],
                relations: vec![
                    KgRelationFactDraft {
                        key: "cause".to_string(),
                        from_entity_key: "beacon".to_string(),
                        to_entity_key: "target".to_string(),
                        relation: KgRelationSemanticV1::Causes.relation().to_string(),
                    },
                    KgRelationFactDraft {
                        key: "procedure".to_string(),
                        from_entity_key: "beacon".to_string(),
                        to_entity_key: "target".to_string(),
                        relation: KgRelationSemanticV1::ProcedureStep.relation().to_string(),
                    },
                    KgRelationFactDraft {
                        key: "contradiction".to_string(),
                        from_entity_key: "beacon".to_string(),
                        to_entity_key: "target".to_string(),
                        relation: KgRelationSemanticV1::Contradicts.relation().to_string(),
                    },
                ],
            },
        )
        .await
        .expect("typed KG memory");

    let request = RetrievalRequest::new("Beacon", 200);
    let fts = store
        .validate_retrieval_request(&access, &request)
        .expect("query");
    let mut transaction = store.pool.begin().await.expect("read transaction");
    let mut seeds = store
        .entity_fts_channel_tx(&mut transaction, &access, &fts, 200)
        .await
        .expect("seeds")
        .values;
    assert!(!seeds.is_empty());
    let mut generations = RetrievalGenerations::new();
    for kind in [
        KgRelationSemanticV1::Causes,
        KgRelationSemanticV1::ProcedureStep,
        KgRelationSemanticV1::Contradicts,
    ] {
        let channel = store
            .typed_relation_channel_tx(&mut transaction, &seeds, &mut generations, 200, kind)
            .await
            .expect("canonical relation channel");
        assert!(!channel.values.is_empty());
        assert_eq!(
            generations.len(),
            1,
            "all channels reuse one exact generation"
        );
    }
    seeds[0].generation_sha256 = Some(Sha256Digest::for_bytes(b"wrong-seed-generation"));
    assert!(
        matches!(
            store
                .graph_channel_tx(&mut transaction, &seeds, &mut generations, 200,)
                .await,
            Err(CognitiveStoreError::Corrupt(_))
        ),
        "a materialized generation must not waive the next seed's digest check"
    );
    transaction
        .rollback()
        .await
        .expect("close read transaction");

    let observation = store
        .observe_memory_retrieval(
            &access,
            &RetrievalRequest::new("Beacon", /*now_unix_seconds*/ 200),
        )
        .await
        .expect("observation");
    let count = |channel| {
        observation
            .channels()
            .iter()
            .find(|row| row.channel == channel)
            .map(|row| row.candidate_count)
            .expect("declared channel")
    };

    assert_eq!(
        count(RetrievalChannel::GraphOneHop),
        0,
        "generic graph retrieval must exclude typed semantic edges"
    );
    assert!(count(RetrievalChannel::Causal) > 0);
    assert!(count(RetrievalChannel::Procedural) > 0);
    assert!(count(RetrievalChannel::ContradictionSupport) > 0);
    assert!(observation.candidates().iter().any(|candidate| {
        candidate
            .channel_ranks
            .iter()
            .any(|rank| rank.channel == RetrievalChannel::Causal)
    }));
    assert!(observation.candidates().iter().any(|candidate| {
        candidate
            .channel_ranks
            .iter()
            .any(|rank| rank.channel == RetrievalChannel::Procedural)
    }));
    assert!(observation.candidates().iter().any(|candidate| {
        candidate
            .channel_ranks
            .iter()
            .any(|rank| rank.channel == RetrievalChannel::ContradictionSupport)
    }));
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

#[tokio::test]
#[ignore = "target-host qualification probe; run explicitly with --ignored --nocapture"]
async fn target_host_owner_retrieval_reports_latency_percentiles() {
    fn percentile(values: &[u128], numerator: usize, denominator: usize) -> u128 {
        assert!(!values.is_empty());
        let rank = values
            .len()
            .saturating_mul(numerator)
            .saturating_add(denominator.saturating_sub(1))
            / denominator;
        values[rank.saturating_sub(1).min(values.len() - 1)]
    }

    let temp = TempDir::new().expect("temp");
    let owner = agent_id(/*suffix*/ 90);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner);
    for index in 0..1024 {
        remember(
            &store,
            &access,
            &format!("qualification-beacon-{index:04}"),
            revision(
                CognitiveScope::AgentPrivate,
                &format!("Qualification Beacon supported fact {index:04}."),
            ),
        )
        .await;
    }
    let request = RetrievalRequest::new("Qualification Beacon", 200);
    let mut retrieval_micros = Vec::with_capacity(200);
    let mut revalidation_micros = Vec::with_capacity(200);
    for _ in 0..200 {
        let started = std::time::Instant::now();
        let observation = store
            .observe_memory_retrieval(&access, &request)
            .await
            .expect("owner retrieval");
        retrieval_micros.push(started.elapsed().as_micros());

        let bindings = observation
            .candidates()
            .iter()
            .map(|candidate| candidate.revalidation.clone())
            .collect::<Vec<_>>();
        let started = std::time::Instant::now();
        let statuses = store
            .revalidate_memory_candidates(&access, &bindings, 200)
            .await
            .expect("revalidation");
        assert!(
            statuses
                .iter()
                .all(|status| matches!(status, RevalidationStatus::Current(_)))
        );
        revalidation_micros.push(started.elapsed().as_micros());
    }
    retrieval_micros.sort_unstable();
    revalidation_micros.sort_unstable();
    eprintln!(
        "{{\"schema\":\"hepta.memory-retrieval.target-host.v1\",\"phase\":\"sqlite-owner\",\"records\":1024,\"iterations\":200,\"retrieval_p50_us\":{},\"retrieval_p95_us\":{},\"retrieval_p99_us\":{},\"revalidation_p50_us\":{},\"revalidation_p95_us\":{},\"revalidation_p99_us\":{}}}",
        percentile(&retrieval_micros, 50, 100),
        percentile(&retrieval_micros, 95, 100),
        percentile(&retrieval_micros, 99, 100),
        percentile(&revalidation_micros, 50, 100),
        percentile(&revalidation_micros, 95, 100),
        percentile(&revalidation_micros, 99, 100),
    );
}
