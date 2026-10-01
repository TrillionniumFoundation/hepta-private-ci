use super::*;

use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_memory_retrieval::RetrievalAssignmentCompletenessV1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000141").expect("owner")
}

fn trusted(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn activated_trust() -> ActivatedLearningTrustV1 {
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                "observer",
                "observer-controller",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            trusted(
                "allocator",
                "allocator-controller",
                3,
                LearningEvidenceRoleV1::CreditAllocator,
            ),
            trusted(
                "evaluator",
                "evaluator-controller",
                4,
                LearningEvidenceRoleV1::Evaluator,
            ),
            trusted(
                "privacy-owner",
                "privacy-controller",
                5,
                LearningEvidenceRoleV1::UnlearningAuthority,
            ),
        ],
    };
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-distribution"),
            generation: 1,
            effective_at: 20,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key
        .sign(&signed.signing_bytes().expect("signing bytes"))
        .to_bytes();
    activate_learning_trust(&root, signed, None, 50).expect("activate trust")
}

fn observation(label: &str) -> RetrievalAssignmentObservationV1 {
    let candidate = RetrievalCandidateIdentityV1 {
        record_id: id("memory:1"),
        record_revision: Revision::new(1).expect("revision"),
        record_digest: digest("record"),
    };
    let mut value = RetrievalAssignmentObservationV1 {
        cue_digest: digest("cue"),
        policy_digest: digest("policy"),
        source_completeness_digest: digest("source-complete"),
        candidate_union_digest: digest("union"),
        recall_packet_digest: digest(label),
        enumerated_candidates: vec![candidate.clone()],
        legal_candidates: vec![candidate.clone()],
        selected_candidates: vec![candidate],
        omitted_by_policy_limits: 0,
        completeness: RetrievalAssignmentCompletenessV1::Complete,
        assignment_propensity: ProbabilityQ32::ONE,
        observation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.observation_digest = value.compute_observation_digest();
    value.validate().expect("observation");
    value
}

fn sink() -> (tempfile::TempDir, CognitiveRetrievalLearningSink) {
    let temp = tempfile::tempdir().expect("temp");
    let binding = digest("agentd-retrieval-learning");
    let ledger_path = temp.path().join("learning.ledger");
    let witness_path = temp.path().join("learning.witness");
    let ledger_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("ledger file");
    let witness_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&witness_path)
        .expect("witness file");
    let ledger = DurableLedger::create(ledger_file, binding, 128).expect("ledger");
    let witness = LedgerWitnessStore::create(witness_file, binding).expect("witness");
    let ledger_directory = File::open(temp.path()).expect("ledger directory");
    let witness_directory = File::open(temp.path()).expect("witness directory");
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        activated_trust(),
        &ledger_directory,
        &witness_directory,
    )
    .expect("product writer");
    (temp, CognitiveRetrievalLearningSink::new(writer))
}

#[test]
fn same_rpc_and_observation_replays_idempotently() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    let first = sink
        .append(&owner(), 1, 77, &observation)
        .expect("first append");
    let second = sink.append(&owner(), 1, 77, &observation).expect("replay");
    assert_eq!(first.disposition, AppendDisposition::Appended);
    assert_eq!(second.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first.event_digest, second.event_digest);
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn same_rpc_with_different_assignment_is_identity_conflict() {
    let (_temp, sink) = sink();
    sink.append(&owner(), 1, 88, &observation("packet-a"))
        .expect("first append");
    assert!(
        sink.append(&owner(), 1, 88, &observation("packet-b"))
            .is_err()
    );
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 1);
}

#[test]
fn different_rpc_ids_create_distinct_assignment_records() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    sink.append(&owner(), 1, 1, &observation).expect("first");
    sink.append(&owner(), 1, 2, &observation).expect("second");
    let snapshot = sink
        .writer
        .lock()
        .expect("lock")
        .snapshot()
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 2);
}

#[test]
fn historical_assignment_retry_keeps_original_predecessor_after_later_appends() {
    let (_temp, sink) = sink();
    let observation = observation("packet");
    let first = sink.append(&owner(), 1, 1, &observation).expect("first");
    for request in 2..=64 {
        sink.append(&owner(), 1, request, &observation)
            .expect("later");
    }
    let before = sink
        .writer
        .lock()
        .expect("lock")
        .witness_frontier()
        .expect("frontier");
    let retry = sink
        .append(&owner(), 1, 1, &observation)
        .expect("historical retry");
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.sequence, first.sequence);
    assert_eq!(retry.event_digest, first.event_digest);
    assert_eq!(retry.chain_digest, first.chain_digest);
    let writer = sink.writer.lock().expect("lock");
    assert_eq!(writer.witness_frontier().expect("frontier"), before);
    assert_eq!(writer.snapshot().expect("snapshot").records().len(), 64);
}

#[test]
fn indexed_historical_identity_does_not_accept_changed_assignment() {
    let (_temp, sink) = sink();
    sink.append(&owner(), 1, 1, &observation("packet-a"))
        .expect("first");
    sink.append(&owner(), 1, 2, &observation("packet-b"))
        .expect("later");
    let before = sink
        .writer
        .lock()
        .expect("lock")
        .witness_frontier()
        .expect("frontier");
    assert!(
        sink.append(&owner(), 1, 1, &observation("replacement"))
            .is_err()
    );
    let writer = sink.writer.lock().expect("lock");
    assert_eq!(writer.witness_frontier().expect("frontier"), before);
    assert_eq!(writer.snapshot().expect("snapshot").records().len(), 2);
}

/// Both clients use their first correlation ID, exactly as a fresh native
/// worker does on every run. The real handler must record distinct preparations.
#[tokio::test]
async fn ordinary_socket_reads_from_new_clients_do_not_reuse_assignment_identity() {
    use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
    use codex_hepta_fleet as fleet;
    use codex_hepta_memory as memory;
    use codex_hepta_memory_retrieval as retrieval;
    use codex_hepta_paths::HeptaFleetRoot;
    use codex_hepta_types::Generation;
    use std::sync::Arc;
    use tokio_util::sync::CancellationToken;

    struct CurrentContext(memory::RetrievalExecutionContextV1);
    impl crate::CurrentMemoryRetrievalContext for CurrentContext {
        fn current(
            &self,
            requested_owner: &AgentId,
            body_generation: u64,
        ) -> Result<memory::RetrievalExecutionContextV1, String> {
            if requested_owner != &owner() || body_generation != 1 {
                return Err("wrong retrieval identity".to_string());
            }
            Ok(self.0.clone())
        }
    }

    let (temp, sink) = sink();
    let sink = Arc::new(sink);
    let root = temp.path().canonicalize().unwrap();
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let registry = fleet::FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = registry
        .register(
            fleet::AgentManifest::new(
                owner(),
                fleet::WorkspaceBinding::new(&workspace, &fleet_root).unwrap(),
                fleet::ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    registry
        .compare_and_transition(
            &owner(),
            /*expected_generation*/ 0,
            fleet::AgentLifecycle::Starting,
        )
        .unwrap();
    let config = crate::AgentdConfig::load(
        root.join("fleet"),
        owner(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .unwrap();
    let store = Arc::new(memory::CognitiveStore::open(&record.layout).await.unwrap());
    let access = memory::CognitiveAccess::agent_private(owner());
    let scope = memory::CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &memory::SourceDraft {
                scope: scope.clone(),
                kind: memory::LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "multi-client-preparation".to_string(),
                content: b"verified lemon orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    let remembered = store
        .remember_memory(
            &access,
            &memory::MemoryDraft {
                stable_key: "orchard".to_string(),
                revision: memory::MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "verified lemon orchard".to_string(),
                    verification: memory::MemoryVerification::Verified,
                    lifecycle: memory::MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await
        .unwrap();
    let now = i64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs(),
    )
    .unwrap();
    let cut = store.lane_c_snapshot(&access, &scope, now).await.unwrap();
    let policy = memory::sqlite_owner_retrieval_policy_v1().unwrap();
    let external = digest("multi-client-external-generations");
    let vector = LaneCGenerationVectorV1 {
        scope_id: cut.scope_id().clone(),
        purpose_id: id("purpose:multi-client-preparation"),
        memory_ledger_frontier: cut.frontiers().memory,
        knowledge_fact_frontier: cut.frontiers().knowledge_facts,
        tombstone_frontier: cut.frontiers().tombstone,
        source_ledger_frontier: cut.frontiers().source,
        knowledge_graph_generation: cut.frontiers().knowledge_graph,
        compact_checkpoint_generation: Generation::new(/*value*/ 1).unwrap(),
        prompt_registry_revision: Revision::new(/*value*/ 1).unwrap(),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let engram = retrieval::EngramSnapshotV1::new(
        vector.digest(),
        external,
        vec![retrieval::EngramNodeV1 {
            node_id: id("node:orchard"),
            population: retrieval::EngramPopulationV1::SemanticConcept,
            support: vec![retrieval::EngramSupportV1 {
                record_id: id(remembered.id.memory_id.as_str()),
                record_revision: Revision::new(remembered.id.revision).unwrap(),
            }],
            threshold: codex_hepta_types::FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: vector.digest(),
        }],
        Vec::new(),
    )
    .unwrap();
    let context = memory::RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: digest("read verified memory"),
        approved_context_digest: cut.snapshot().snapshot_digest,
        cue_profile_digest: memory::sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: engram,
        dynamics_policy: retrieval::EngramDynamicsPolicyV1::product_default().unwrap(),
    };
    let (identity, registry, _writer_lock) = config.into_parts();
    let socket = identity.control_socket.clone();
    let state = Arc::new(
        crate::AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).unwrap(),
    );
    state.attach_cognitive_store(store).unwrap();
    state.mark_runtime_prerequisites_ready().unwrap();
    assert!(
        state
            .cognitive_retrieval_context
            .set(Arc::new(CurrentContext(context)))
            .is_ok()
    );
    assert!(
        state
            .cognitive_retrieval_learning
            .set(Arc::clone(&sink))
            .is_ok()
    );
    registry
        .compare_and_transition(
            &owner(),
            /*expected_generation*/ 1,
            fleet::AgentLifecycle::Running,
        )
        .unwrap();
    state.mark_app_server_ready().unwrap();
    let cancellation = CancellationToken::new();
    let _cancel_on_drop = cancellation.clone().drop_guard();
    let server = crate::AgentdControlServer::bind(socket.clone(), state, cancellation.clone())
        .await
        .unwrap();
    let task = tokio::spawn(server.run());
    let first = crate::AgentdClient::new(socket.clone(), owner(), /*spawn_generation*/ 1)
        .unwrap()
        .prepare_cognitive_context("lemon".to_string(), /*limit*/ 4)
        .await
        .unwrap();
    let second = crate::AgentdClient::new(socket.clone(), owner(), /*spawn_generation*/ 1)
        .unwrap()
        .prepare_cognitive_context("orchard".to_string(), /*limit*/ 4)
        .await
        .unwrap();
    assert_eq!(first.snapshot.items, second.snapshot.items);
    assert_eq!(first.snapshot.items.len(), 1);
    let capabilities = crate::AgentdClient::new(socket.clone(), owner(), /*spawn_generation*/ 1)
        .unwrap().capabilities().await.unwrap();
    assert!(capabilities.capabilities.iter().any(|capability| capability.id == crate::COGNITIVE_CONTEXT_PREPARATION_CAPABILITY && capability.major == 1));
    let snapshot = sink.writer.lock().unwrap().snapshot().unwrap();
    assert_eq!(snapshot.records().len(), 2);
    let assignments = snapshot
        .records()
        .iter()
        .map(|record| match &record.event {
            LedgerEvent::RetrievalAssignment(value) => value,
            _ => panic!("unexpected preparation event"),
        })
        .collect::<Vec<_>>();
    assert_ne!(assignments[0].record_id, assignments[1].record_id);
    assert_ne!(assignments[0].episode_id, assignments[1].episode_id);
    assert_ne!(assignments[0].cue_digest, assignments[1].cue_digest);
    for (assignment, published) in assignments.iter().zip([&first, &second]) {
        assert!(
            assignment
                .record_id
                .as_str()
                .starts_with("retrieval-preparation:")
        );
        assert!(
            assignment
                .episode_id
                .as_str()
                .starts_with("retrieval-preparation-episode:")
        );
        let expected = Digest32::of_bytes(&serde_json::to_vec(&published.snapshot).unwrap());
        assert_eq!(assignment.published_context_digest, Some(expected));
        let receipt = published.preparation.as_ref().unwrap();
        assert_eq!(receipt.read_request_id, 1);
        receipt.validate().unwrap();
        let inspect = |agent: &AgentId, generation, request_id, context_digest| sink.with_owner_preparation(
            agent, generation, request_id, receipt.sequence,
            receipt.event_digest.parse().unwrap(), receipt.chain_digest.parse().unwrap(),
            context_digest, |actual, _| Ok(actual.clone()),
        );
        assert_eq!(inspect(&owner(), 1, 1, expected).unwrap(), **assignment);
        assert!(inspect(&owner(), 2, 1, expected).is_err());
        assert!(inspect(&owner(), 1, 2, expected).is_err());
        let other_owner = AgentId::parse("00000000-0000-4000-8000-000000000142").unwrap();
        assert!(inspect(&other_owner, 1, 1, expected).is_err());
        assert!(inspect(&owner(), 1, 1, digest("wrong-context")).is_err());
        assert!(
            sink.with_prepared_assignment(
                &owner(),
                /*body_generation*/ 1,
                /*read_request_id*/ 1,
                expected,
                |_, _| Ok(())
            )
            .is_err(),
            "explicit-RPC inspection must not select a fresh preparation by correlation ID"
        );
    }
    cancellation.cancel();
    task.await.unwrap().unwrap();
}
