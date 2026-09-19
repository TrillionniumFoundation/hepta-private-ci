use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory::SourceDraft;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramNodeV1;
use codex_hepta_memory_retrieval::EngramPopulationV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::EngramSupportV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CurrentMemoryRetrievalContext;

use super::CognitiveContextError;
use super::read_with_retrieval_context;

#[derive(Clone)]
struct SwitchingContext {
    owner: AgentId,
    generation: u64,
    first: RetrievalExecutionContextV1,
    later: RetrievalExecutionContextV1,
    switch_after_first: bool,
    calls: Arc<AtomicUsize>,
}

impl CurrentMemoryRetrievalContext for SwitchingContext {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        if owner != &self.owner || body_generation != self.generation {
            return Err("wrong retrieval host identity".to_string());
        }
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        if self.switch_after_first && call > 0 {
            Ok(self.later.clone())
        } else {
            Ok(self.first.clone())
        }
    }
}

async fn fixture(
    suffix: u16,
) -> (
    tempfile::TempDir,
    CognitiveStore,
    AgentId,
    RetrievalExecutionContextV1,
    String,
) {
    let temp = tempfile::tempdir().unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).unwrap();
    let owner = AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012}")).unwrap();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "hnmf-context-test".to_string(),
                content: b"lemon evidence".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let first = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "first".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "lemon first".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation.clone()],
                },
            },
        )
        .await
        .unwrap();
    let second = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "second".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "lemon second".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let now = i64::try_from(now).unwrap();
    let cut = store.lane_c_snapshot(&access, &scope, now).await.unwrap();
    let retrieval_policy = sqlite_owner_retrieval_policy_v1().unwrap();
    let profile = retrieval_policy.digest();
    let external = Digest32::of_bytes(b"hnmf-context-external");
    let vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("purpose:agentd-hnmf-context").unwrap(),
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: profile,
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let vector_digest = vector.digest();
    // Deliberately support only the second memory. HNMF recall must narrow the
    // full owner-generated candidate set to this record before learned ranking.
    let node = EngramNodeV1 {
        node_id: StableId::new("node:second").unwrap(),
        population: EngramPopulationV1::SemanticConcept,
        support: vec![EngramSupportV1 {
            record_id: StableId::new(second.id.memory_id.as_str()).unwrap(),
            record_revision: Revision::new(second.id.revision).unwrap(),
        }],
        threshold: codex_hepta_types::FixedQ32::ZERO,
        confidence: ProbabilityQ32::ONE,
        generation_vector_digest: vector_digest,
    };
    let engram_snapshot = EngramSnapshotV1::new(
        vector_digest,
        Digest32::of_bytes(b"agentd-hnmf-engram-generation"),
        vec![node],
        Vec::new(),
    )
    .unwrap();
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: Digest32::of_bytes(b"retrieve relevant verified memory"),
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy,
        engram_snapshot,
        dynamics_policy: EngramDynamicsPolicyV1::product_default().unwrap(),
    };
    context.validate().unwrap();
    (
        temp,
        store,
        owner,
        context,
        first.id.memory_id.as_str().to_string(),
    )
}

#[tokio::test]
async fn current_hnmf_context_filters_owner_candidates_before_delivery() {
    let (_temp, store, owner, context, excluded_id) = fixture(131).await;
    let expected_id = context.engram_snapshot.nodes[0].support[0]
        .record_id
        .as_str()
        .to_string();
    let provider: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(SwitchingContext {
        owner: owner.clone(),
        generation: 1,
        first: context.clone(),
        later: context,
        switch_after_first: false,
        calls: Arc::new(AtomicUsize::new(0)),
    });
    let result = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&provider))
        .await
        .unwrap();
    assert_eq!(result.items.len(), 1);
    assert_eq!(result.items[0].memory_id, expected_id);
    assert_ne!(result.items[0].memory_id, excluded_id);
}

#[tokio::test]
async fn changed_hnmf_context_before_publication_fails_closed() {
    let (_temp, store, owner, first, _excluded_id) = fixture(132).await;
    let mut later = first.clone();
    later.objective_digest = Digest32::of_bytes(b"changed objective");
    later.validate().unwrap();
    let provider: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(SwitchingContext {
        owner: owner.clone(),
        generation: 1,
        first,
        later,
        switch_after_first: true,
        calls: Arc::new(AtomicUsize::new(0)),
    });
    assert!(matches!(
        read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&provider),).await,
        Err(CognitiveContextError::RetrievalContextUnavailable)
    ));
}
