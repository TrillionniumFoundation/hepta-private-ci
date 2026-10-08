//! Actual source/ledger owners. Fixture keys do not issue production acceptance.
use super::*;
use codex_hepta_agentd::AgentdSharedReplayHostV1;
use codex_hepta_agentd::MemoryTrainerProcessConfigV1;
use codex_hepta_agentd::MemoryTrainerProcessV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::*;
use codex_hepta_paths::HeptaFleetRoot;
use std::sync::Arc;

struct Input {
    source: Arc<CognitiveStore>, access: CognitiveAccess, host: AgentdSharedReplayHostV1,
    replay: SharedExperienceUseV1, recall: SharedExperienceUseV1,
    ledger: LedgerWriter, dataset: DatasetSnapshotReceiptV3,
    _fixture: Fixture, _temp: tempfile::TempDir,
}
impl Input {
    async fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let fleet = HeptaFleetRoot::parse(temp.path().to_path_buf()).unwrap().layout();
        let owner_id = AgentId::parse("00000000-0000-4000-8000-000000000031").unwrap();
        let receiver_id = AgentId::parse("00000000-0000-4000-8000-000000000032").unwrap();
        let source = Arc::new(CognitiveStore::open(&fleet.agent(&owner_id)).await.unwrap());
        let access = CognitiveAccess::agent_private(owner_id.clone());
        let consumer = FederationConsumerAccess::new(receiver_id.clone(), Sha256Digest::for_bytes(b"tensor-training-workspace"));
        let content = "Memory test observation: a source revision and a training permission are different. Never treat a recalled instruction as permission to run a tool.";
        let citation = source.append_source(&access, &SourceDraft {
            scope: CognitiveScope::AgentPrivate, kind: LedgerSourceKind::PersistedToolResult,
            event_key: "memory.tensor.source".into(), content: content.as_bytes().to_vec(), observed_at_unix_seconds: 100,
        }).await.unwrap();
        let memory = source.remember_memory(&access, &MemoryDraft { stable_key: "memory.tensor.source".into(),
            revision: MemoryRevisionDraft { scope: CognitiveScope::AgentPrivate, content: content.into(),
                verification: MemoryVerification::Verified, lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 100, valid_to_unix_seconds: None, citations: vec![citation] },
        }).await.unwrap();
        let expires = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() as i64 + 3600;
        let grant = SharedExperienceGrantV1 { memory_id: memory.id.memory_id.clone(), memory_revision: memory.id.revision,
            consumer: consumer.clone(), purpose: SharedExperiencePurposeV1::Recall, expires_at_unix_seconds: expires };
        let recall = source.grant_shared_experience(&access, &grant, 0).await.unwrap();
        let mut grant = grant;
        grant.purpose = SharedExperiencePurposeV1::Replay { parameter_scope: "domain.tensor".into(), artifact_consumer: receiver_id.clone() };
        let replay = source.grant_shared_experience(&access, &grant, 0).await.unwrap();
        let host = AgentdSharedReplayHostV1::new(Arc::clone(&source), consumer, "domain.tensor".into(), receiver_id).unwrap();
        let fixture = Fixture::new();
        let mut ledger = fixture.writer();
        let support = replay.source_support_digest().as_str().parse().unwrap();
        collect_with_support(&mut ledger, "tensor.read", "read", FixedQ32::ONE.raw(), support);
        collect_with_support(&mut ledger, "tensor.stop", "abstain", 0, support);
        let dataset = freeze(&ledger, "tensor.dataset");
        Self { _temp: temp, _fixture: fixture, source, access, host, replay, recall, ledger, dataset }
    }
    fn profile(&self) -> MemoryTrainingProfileV1 {
        MemoryTrainingProfileV1 { job_id: id("tensor.job"), artifact_id: id("tensor.artifact"), producer_id: id("operator.tensor"),
            predecessor_generation: Generation::new(1).unwrap(), generation: Generation::new(2).unwrap(),
            objective_digest: digest("objective"), base_digest: digest("pretrained.fixture"), encoder_digest: digest("pretrained.fixture"),
            trainer_digest: digest("trainer.fixture"), scope_digest: self.host.memory_parameter_scope_digest().unwrap(),
            maximum_steps: 4, maximum_tokens_per_step: 192, maximum_payload_bytes: 4 * 1024 * 1024, expires_at: 350 }
    }
}
#[tokio::test]
async fn source_permission_is_checked_at_prepare_and_after_training() {
    let input = Input::new().await;
    let profile = input.profile();
    assert!(input.host.prepare_memory_training(input.recall.policy_id(), &input.ledger, &input.dataset, profile.clone(), 50).await.is_err());
    let prepared = input.host.prepare_memory_training(input.replay.policy_id(), &input.ledger, &input.dataset, profile.clone(), 50).await.unwrap();
    let payload = b"mechanism-only payload; not a trained tensor or production artifact".to_vec();
    let observation = MemoryTrainingObservationV1 { job_digest: prepared.frozen().job_digest(), base_digest: profile.base_digest,
        frozen_base_after_digest: profile.base_digest, encoder_digest: profile.encoder_digest, trainer_digest: profile.trainer_digest,
        payload_digest: Digest32::of_bytes(&payload), payload_bytes: payload.len() as u64,
        completed_steps: 1, consumed_tokens: 32, trainable_parameters: 16, changed_parameters: 1 };
    let mut corrupted = observation.clone();
    corrupted.payload_digest = digest("wrong payload");
    assert!(input.host.finish_memory_training(prepared.clone(), &input.ledger, corrupted, payload.clone(), 50).await.is_err());
    let candidate = input.host.finish_memory_training(prepared.clone(), &input.ledger, observation.clone(), payload.clone(), 50).await.unwrap();
    assert_eq!(candidate.candidate().observation(), &observation);
    input.source.revoke_shared_experience(&input.access, &input.replay).await.unwrap();
    assert!(input.host.finish_memory_training(prepared, &input.ledger, observation, payload, 50).await.is_err());
}
#[tokio::test]
#[ignore = "requires explicitly staged real pretrained weights; CI invokes by name"]
async fn actual_pretrained_worker_consumes_cognitive_and_learning_owner_job() {
    let input = Input::new().await;
    let executable = std::path::PathBuf::from(std::env::var("HEPTA_MEMORY_PYTHON").unwrap());
    let program = std::path::PathBuf::from(std::env::var("HEPTA_MEMORY_PROGRAM").unwrap());
    let config = MemoryTrainerProcessConfigV1 { interpreter_digest: Digest32::of_bytes(&std::fs::read(&executable).unwrap()),
        python_executable: executable, code_digest: MemoryTrainerProcessV1::code_digest(&program).unwrap(), program,
        model_directory: std::env::var("HEPTA_MEMORY_MODEL_DIR").unwrap().into(), scratch_root: input._temp.path().to_path_buf() };
    let mut profile = input.profile();
    profile.base_digest = std::env::var("HEPTA_MEMORY_BASE_DIGEST").unwrap().parse().unwrap();
    profile.encoder_digest = profile.base_digest;
    profile.trainer_digest = config.code_digest;
    let prepared = input.host.prepare_memory_training(input.replay.policy_id(), &input.ledger, &input.dataset, profile, 50).await.unwrap();
    let worker = MemoryTrainerProcessV1::new(config).unwrap();
    let (observation, payload, metrics) = worker.execute(&prepared, 50).unwrap();
    let candidate = input.host.finish_memory_training(prepared.clone(), &input.ledger, observation.clone(), payload.clone(), 50).await.unwrap();
    assert!(candidate.candidate().observation().changed_parameters > 0);
    let output = std::path::PathBuf::from(std::env::var("HEPTA_MEMORY_EVIDENCE_DIR").unwrap());
    std::fs::create_dir(&output).unwrap();
    std::fs::write(output.join("adapter.safetensors"), candidate.payload()).unwrap();
    input.source.revoke_shared_experience(&input.access, &input.replay).await.unwrap();
    assert!(input.host.finish_memory_training(prepared, &input.ledger, observation.clone(), payload, 50).await.is_err());
    std::fs::write(output.join("owner-training.json"), serde_json::to_vec_pretty(&serde_json::json!({
        "source_owner": "cognitive.store", "training_owner": "learning.operator", "actual_worker": "offline-pretrained-transformer-lora",
        "changed_parameters": observation.changed_parameters, "trainable_parameters": observation.trainable_parameters,
        "payload_digest": observation.payload_digest.to_string(), "source_revocation_rejected": true,
        "metrics": metrics, "production_accepted": false, "authority_profile": "qualification-fixture-keys"
    })).unwrap()).unwrap();
}
