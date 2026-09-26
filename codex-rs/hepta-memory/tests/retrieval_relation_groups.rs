use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::KgEntityFactDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::KgRelationFactDraft;
use codex_hepta_memory::KgRelationSemanticV1;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::execute_owner_observation;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
type StoreFixture = (
    TempDir,
    AgentId,
    CognitiveStore,
    CognitiveAccess,
    CognitiveScope,
);

async fn store(suffix: &str) -> TestResult<StoreFixture> {
    let temp = TempDir::new()?;
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet)?;
    let fleet = std::fs::canonicalize(&fleet)?;
    let owner = AgentId::parse(format!("00000000-0000-4000-8000-{suffix}"))?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let access = CognitiveAccess::agent_private(owner.clone());
    Ok((temp, owner, store, access, CognitiveScope::AgentPrivate))
}

async fn remember_relations(
    store: &CognitiveStore,
    access: &CognitiveAccess,
    scope: &CognitiveScope,
    stable_key: &str,
    targets: &[&str],
) -> TestResult {
    let content = format!("Beacon contradicts {}.", targets.join(" and "));
    let mut entities = vec![KgEntityFactDraft {
        key: "beacon".to_string(),
        entity_type: "topic".to_string(),
        label: "Beacon".to_string(),
    }];
    entities.extend(targets.iter().map(|target| KgEntityFactDraft {
        key: (*target).to_string(),
        entity_type: "topic".to_string(),
        label: (*target).to_string(),
    }));
    let relations = targets
        .iter()
        .enumerate()
        .map(|(index, target)| KgRelationFactDraft {
            key: format!("contradiction-{index}"),
            from_entity_key: "beacon".to_string(),
            to_entity_key: (*target).to_string(),
            relation: KgRelationSemanticV1::Contradicts.relation().to_string(),
        })
        .collect();
    store
        .remember_with_kg(
            access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: format!("source-{stable_key}"),
                content: content.as_bytes().to_vec(),
                observed_at_unix_seconds: 100,
            },
            &MemoryDraft {
                stable_key: stable_key.to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content,
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft {
                entities,
                relations,
            },
        )
        .await?;
    Ok(())
}

fn execution_context(
    cut: &codex_hepta_memory::DurableCognitiveSnapshot,
) -> TestResult<RetrievalExecutionContextV1> {
    let policy = sqlite_owner_retrieval_policy_v1()?;
    let common = Digest32::of_bytes(b"relation-group-integration-test");
    let generation_vector = codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("purpose:relation-group-integration-test")?,
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1)?,
        prompt_registry_revision: Revision::new(1)?,
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: common,
        authority_epoch: 1,
        model_digest: common,
        tokenizer_digest: common,
        template_digest: common,
        tool_schema_digest: common,
    };
    let vector_digest = generation_vector.digest();
    Ok(RetrievalExecutionContextV1 {
        generation_vector,
        objective_digest: Digest32::of_bytes(b"objective"),
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: EngramSnapshotV1::new(
            vector_digest,
            Digest32::of_bytes(b"empty-test-engram"),
            Vec::new(),
            Vec::new(),
        )?,
        dynamics_policy: EngramDynamicsPolicyV1::product_default()?,
    })
}

#[tokio::test]
async fn one_canonical_relation_group_is_stable_and_admitted() -> TestResult {
    let (_temp, _owner, store, access, scope) = store("000000000201").await?;
    remember_relations(&store, &access, &scope, "one-group", &["TargetA"]).await?;
    let request = RetrievalRequest::new("Beacon", 200);
    let observation = store.observe_memory_retrieval(&access, &request).await?;
    let candidate = observation
        .candidates()
        .iter()
        .find(|candidate| {
            candidate
                .channels
                .contains(&codex_hepta_memory::RetrievalChannel::ContradictionSupport)
        })
        .ok_or("contradiction candidate")?;
    assert!(candidate.contradiction_groups_complete);
    assert_eq!(candidate.contradiction_group_sha256s.len(), 1);
    let repeated = store.observe_memory_retrieval(&access, &request).await?;
    let repeated_candidate = repeated
        .candidates()
        .iter()
        .find(|candidate| {
            candidate
                .channels
                .contains(&codex_hepta_memory::RetrievalChannel::ContradictionSupport)
        })
        .ok_or("repeat contradiction candidate")?;
    assert_eq!(
        repeated_candidate.contradiction_group_sha256s,
        candidate.contradiction_group_sha256s
    );

    let cut = store.lane_c_snapshot(&access, &scope, 200).await?;
    let context = execution_context(&cut)?;
    let authoritative = cut.bind_context(context.generation_vector.clone(), 200_000, 205_000)?;
    execute_owner_observation(
        &observation,
        &authoritative,
        &context,
        Digest32::of_bytes(b"Beacon"),
    )?;
    Ok(())
}

#[tokio::test]
async fn distinct_relations_do_not_collapse_into_one_observation_group() -> TestResult {
    let (_temp, _owner, store, access, scope) = store("000000000202").await?;
    remember_relations(
        &store,
        &access,
        &scope,
        "two-groups",
        &["TargetA", "TargetB"],
    )
    .await?;
    let observation = store
        .observe_memory_retrieval(&access, &RetrievalRequest::new("Beacon", 200))
        .await?;
    let candidate = observation
        .candidates()
        .iter()
        .find(|candidate| {
            candidate
                .channels
                .contains(&codex_hepta_memory::RetrievalChannel::ContradictionSupport)
        })
        .ok_or("contradiction candidate")?;
    assert!(candidate.contradiction_groups_complete);
    assert_eq!(candidate.contradiction_group_sha256s.len(), 2);
    assert_ne!(
        candidate.contradiction_group_sha256s[0],
        candidate.contradiction_group_sha256s[1]
    );

    let cut = store.lane_c_snapshot(&access, &scope, 200).await?;
    let context = execution_context(&cut)?;
    let authoritative = cut.bind_context(context.generation_vector.clone(), 200_000, 205_000)?;
    assert!(matches!(
        execute_owner_observation(
            &observation,
            &authoritative,
            &context,
            Digest32::of_bytes(b"Beacon"),
        ),
        Err(CognitiveStoreError::Conflict(_))
    ));
    Ok(())
}
