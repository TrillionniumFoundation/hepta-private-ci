//! Real SQLite + Agentd read/final-use regressions with test-only signing keys.
//! These are not daemon-process, live signer, or target-host SLO qualifications.

use super::*;
use codex_hepta_agent_components::cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_agent_components::memory::CognitiveAccess;
use codex_hepta_agent_components::memory::CognitiveScope;
use codex_hepta_agent_components::memory::CognitiveStore;
use codex_hepta_agent_components::memory::LedgerSourceKind;
use codex_hepta_agent_components::memory::MemoryDraft;
use codex_hepta_agent_components::memory::MemoryLifecycleState;
use codex_hepta_agent_components::memory::MemoryRevisionDraft;
use codex_hepta_agent_components::memory::MemoryVerification;
use codex_hepta_agent_components::memory::SourceDraft;
use codex_hepta_agent_components::memory::sqlite_owner_cue_profile_digest;
use codex_hepta_agent_components::memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_agent_components::memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_agent_components::memory_retrieval::EngramNodeV1;
use codex_hepta_agent_components::memory_retrieval::EngramPopulationV1;
use codex_hepta_agent_components::memory_retrieval::EngramSnapshotV1;
use codex_hepta_agent_components::memory_retrieval::EngramSupportV1;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::ProbabilityQ32;
use codex_hepta_agent_components::types::Revision;
use codex_hepta_agent_components::types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::CognitiveRetrievalMode;
use crate::cognitive_context::read_with_retrieval_context;
use crate::cognitive_context::revalidate_with_retrieval_context;
use crate::retrieval_product_mode::route;

struct TestFrontier(Mutex<MemoryRetrievalFrontierV1>);

impl MemoryRetrievalFrontierOwnerV1 for TestFrontier {
    fn observe(
        &self,
        _: &AgentId,
        _: u64,
        challenge: [u8; 32],
    ) -> Result<MemoryRetrievalFrontierV1, String> {
        let mut response = self.0.lock().expect("fixture frontier").clone();
        response.challenge = challenge;
        response.expires_unix_ms = now_ms()? + 10_000;
        response.signature = SigningKey::from_bytes(&[3; 32])
            .sign(&response.signing_bytes())
            .to_bytes();
        Ok(response)
    }
}

struct Fixture {
    store: CognitiveStore,
    owner: AgentId,
    publication: SignedMemoryRetrievalContextV1,
    frontier: Arc<TestFrontier>,
    provider: Arc<LeasedMemoryRetrievalProviderV1>,
    _temp: tempfile::TempDir,
}

fn sign(publication: &mut SignedMemoryRetrievalContextV1) {
    publication.signature = SigningKey::from_bytes(&[2; 32])
        .sign(&publication.signing_bytes())
        .to_bytes();
}

async fn fixture() -> Fixture {
    let temp = tempfile::tempdir().expect("temp");
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet).expect("fleet");
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000831").expect("owner");
    let layout = HeptaFleetRoot::parse(fleet)
        .expect("root")
        .layout()
        .agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("SQLite owner");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "signed-lifecycle-fixture".to_string(),
                content: b"lemon evidence".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .expect("source");
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "signed-lifecycle-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "lemon verified memory".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .expect("memory");
    let now = now_ms().expect("clock");
    let seconds = i64::try_from(now / 1000).expect("epoch seconds");
    let cut = store
        .lane_c_snapshot(&access, &scope, seconds)
        .await
        .expect("cut");
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let external = Digest32::of_bytes(b"signed-lifecycle-test-only-profile");
    let vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: StableId::new("purpose:signed-lifecycle-test").expect("purpose"),
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let node = EngramNodeV1 {
        node_id: StableId::new("node:signed-lifecycle-test").expect("node"),
        population: EngramPopulationV1::SemanticConcept,
        support: vec![EngramSupportV1 {
            record_id: StableId::new(memory.id.memory_id.as_str()).expect("record"),
            record_revision: Revision::new(memory.id.revision).expect("revision"),
        }],
        threshold: FixedQ32::ZERO,
        confidence: ProbabilityQ32::ONE,
        generation_vector_digest: vector.digest(),
    };
    let graph =
        EngramSnapshotV1::new(vector.digest(), external, vec![node], Vec::new()).expect("graph");
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: external,
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: graph,
        dynamics_policy: EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    };
    let mut publication = SignedMemoryRetrievalContextV1 {
        owner: owner.clone(),
        body_generation: 1,
        sequence: 1,
        not_before_unix_ms: now.saturating_sub(1),
        expires_unix_ms: now + 120_000,
        context,
        signature: [0; 64],
    };
    sign(&mut publication);
    let frontier = Arc::new(TestFrontier(Mutex::new(MemoryRetrievalFrontierV1 {
        owner: owner.clone(),
        body_generation: 1,
        authority_epoch: 1,
        sequence: 1,
        publication_digest: Some(publication.publication_digest()),
        expires_unix_ms: 0,
        challenge: [0; 32],
        signature: [0; 64],
    })));
    let frontier_port: Arc<dyn MemoryRetrievalFrontierOwnerV1> = frontier.clone();
    let provider = Arc::new(
        LeasedMemoryRetrievalProviderV1::new(
            owner.clone(),
            /*body_generation*/ 1,
            SigningKey::from_bytes(&[2; 32]).verifying_key().to_bytes(),
            SigningKey::from_bytes(&[3; 32]).verifying_key().to_bytes(),
            frontier_port,
            /*maximum_lease_ms*/ 300_000,
        )
        .expect("provider"),
    );
    Fixture {
        store,
        owner,
        publication,
        frontier,
        provider,
        _temp: temp,
    }
}

#[tokio::test]
async fn signed_same_payload_renewal_invalidates_real_agentd_final_use() {
    let mut f = fixture().await;
    f.provider.install(f.publication.clone()).expect("install");
    let reader: Arc<dyn CurrentMemoryRetrievalContext> = f.provider.clone();
    let reader = route(CognitiveRetrievalMode::HnmfRequired, reader);
    let before = reader.acquire_context(&f.owner, 1).expect("acquire");
    let response = read_with_retrieval_context(
        &f.store,
        &f.owner,
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
        Some(&reader),
    )
    .await
    .expect("real Agentd read");
    assert!(!response.items.is_empty());
    revalidate_with_retrieval_context(
        &f.store,
        &f.owner,
        &response.snapshot_digest,
        &response.read_digest,
        response.omitted_records,
        &response.items,
        response.plan.as_ref(),
        /*ranker*/ None,
        /*body_generation*/ 1,
        Some(&reader),
    )
    .await
    .expect("fresh final use");
    f.publication.sequence += 1;
    f.publication.expires_unix_ms += 1;
    sign(&mut f.publication);
    {
        let mut frontier = f.frontier.0.lock().expect("frontier");
        frontier.sequence = f.publication.sequence;
        frontier.publication_digest = Some(f.publication.publication_digest());
    }
    f.provider.install(f.publication.clone()).expect("renew");
    let after = reader
        .acquire_context(&f.owner, 1)
        .expect("renewed acquire");
    assert_eq!(before.0, after.0);
    assert_ne!(before.1, after.1);
    assert_ne!(before.2, after.2);
    assert!(
        revalidate_with_retrieval_context(
            &f.store,
            &f.owner,
            &response.snapshot_digest,
            &response.read_digest,
            response.omitted_records,
            &response.items,
            response.plan.as_ref(),
            /*ranker*/ None,
            /*body_generation*/ 1,
            Some(&reader),
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn signed_revocation_closes_real_agentd_final_use() {
    let f = fixture().await;
    f.provider.install(f.publication.clone()).expect("install");
    let reader: Arc<dyn CurrentMemoryRetrievalContext> = f.provider.clone();
    let reader = route(CognitiveRetrievalMode::HnmfRequired, reader);
    let response = read_with_retrieval_context(
        &f.store,
        &f.owner,
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
        Some(&reader),
    )
    .await
    .expect("read");
    assert!(!response.items.is_empty());
    {
        let mut frontier = f.frontier.0.lock().expect("frontier");
        frontier.sequence += 1;
        frontier.publication_digest = None;
    }
    assert!(
        revalidate_with_retrieval_context(
            &f.store,
            &f.owner,
            &response.snapshot_digest,
            &response.read_digest,
            response.omitted_records,
            &response.items,
            response.plan.as_ref(),
            /*ranker*/ None,
            /*body_generation*/ 1,
            Some(&reader),
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn missing_signed_publication_is_shadow_only_not_required_fallback() {
    let f = fixture().await;
    let reader: Arc<dyn CurrentMemoryRetrievalContext> = f.provider.clone();
    let shadow = route(CognitiveRetrievalMode::HnmfShadow, reader.clone());
    let required = route(CognitiveRetrievalMode::HnmfRequired, reader);
    let baseline = read_with_retrieval_context(
        &f.store, &f.owner, /*body_generation*/ 1, "lemon", /*limit*/ 4,
        /*ranker*/ None, /*current_retrieval*/ None,
    )
    .await
    .expect("compatibility");
    let observed = read_with_retrieval_context(
        &f.store,
        &f.owner,
        /*body_generation*/ 1,
        "lemon",
        /*limit*/ 4,
        /*ranker*/ None,
        Some(&shadow),
    )
    .await
    .expect("shadow cannot poison delivery");
    assert!(!baseline.items.is_empty());
    assert_eq!(baseline.items, observed.items);
    assert_eq!(baseline.read_digest, observed.read_digest);
    assert!(
        read_with_retrieval_context(
            &f.store,
            &f.owner,
            /*body_generation*/ 1,
            "lemon",
            /*limit*/ 4,
            /*ranker*/ None,
            Some(&required),
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn mode_binding_preserves_one_atomic_signed_publication() {
    let f = fixture().await;
    f.provider.install(f.publication.clone()).expect("install");
    let reader: Arc<dyn CurrentMemoryRetrievalContext> = f.provider.clone();
    let expected = f
        .provider
        .acquire_context(&f.owner, 1)
        .expect("atomic publication");
    assert_eq!(expected.1, f.publication.publication_digest());
    assert_eq!(expected.2, Some(f.publication.expires_unix_ms));
    let mut bindings = std::collections::BTreeSet::new();
    for mode in [
        CognitiveRetrievalMode::HnmfShadow,
        CognitiveRetrievalMode::HnmfCanary,
        CognitiveRetrievalMode::HnmfRequired,
    ] {
        let routed = route(mode, reader.clone());
        let first = routed
            .acquire_context(&f.owner, 1)
            .expect("mode acquisition");
        let second = routed
            .acquire_context(&f.owner, 1)
            .expect("stable mode acquisition");
        assert_eq!(first, second);
        assert_eq!(first.0, expected.0);
        assert_eq!(first.2, expected.2);
        assert!(bindings.insert(first.1));
    }
}
