//! Ordinary configuration rejects a controlled neural qualification. Neither
//! the doubles nor the test signers establish independent product eligibility.

#![cfg(any(target_os = "linux", target_os = "macos"))]

use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::CurrentCognitiveRegistry;
use codex_hepta_agentd::EvaluatedCognitiveBootstrapV1;
use codex_hepta_agentd::NeuralCognitiveBootstrapModelV1;
use codex_hepta_agentd::NeuralCognitiveInferencePortV1;
use codex_hepta_agentd::NeuralCognitiveObservationV1;
use codex_hepta_agentd::NeuralCognitiveRequestV1;
use codex_hepta_agentd::NeuralFinalHoldoutProviderV1;
use codex_hepta_agentd::NeuralHoldoutRuntimeV1;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_artifacts as artifacts;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[path = "support/neural_bootstrap_descriptor.rs"]
mod descriptor_fixture;
#[path = "support/neural_holdout_ledger.rs"]
mod ledger_fixture;
#[path = "support/neural_holdout_plan.rs"]
mod plan_fixture;

use ledger_fixture::ControlledRoles;
use ledger_fixture::hash;
use ledger_fixture::id;
use ledger_fixture::micros;
use ledger_fixture::owner;

struct EqualScorePort;
impl NeuralCognitiveInferencePortV1 for EqualScorePort {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        bytes: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String> {
        assert_eq!(Digest32::of_bytes(bytes), request.pin.payload_digest);
        Ok(NeuralCognitiveObservationV1 {
            request: request.clone(),
            scores_q32: Some(vec![2, 1]),
            execution_receipt_digest: hash("controlled-bootstrap-comparison"),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Default)]
struct UnadmittedOwners {
    current_calls: AtomicUsize,
    inference_calls: AtomicUsize,
}
impl CurrentCognitiveRegistry for UnadmittedOwners {
    fn current(&self) -> Result<artifacts::VerifiedCurrentRegistryViewV1, String> {
        self.current_calls.fetch_add(1, Ordering::SeqCst);
        Err("unqualified bootstrap reached CURRENT".to_owned())
    }
}
impl NeuralCognitiveInferencePortV1 for UnadmittedOwners {
    fn execute(
        &self,
        _: &NeuralCognitiveRequestV1,
        _: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String> {
        self.inference_calls.fetch_add(1, Ordering::SeqCst);
        Err("unqualified bootstrap reached inference".to_owned())
    }
}

fn config(root: &Path) -> AgentdConfig {
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
    let registry = FleetRegistry::initialize(fleet_root.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let record = registry
        .register(
            AgentManifest::new(
                owner(),
                WorkspaceBinding::new(&workspace, &fleet_root).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    registry
        .compare_and_transition(&owner(), 0, AgentLifecycle::Starting)
        .unwrap();
    AgentdConfig::load(
        fleet_path,
        owner(),
        1,
        record.layout.home_root().into(),
        record.layout.run_root().into(),
        record.layout.home_root().into(),
        workspace,
    )
    .unwrap()
}

#[test]
fn ordinary_neural_config_rejects_original_controlled_qualification_before_current_or_runtime() {
    let root = tempfile::tempdir().unwrap();
    let root = root.path().canonicalize().unwrap();
    let config = config(&root);
    let mut roles = ControlledRoles::new();
    let (dataset, ledger) = roles.dataset(&root.join("ledger-owner"));
    let candidate_bytes = b"CONTROLLED NEURAL PORT DOUBLE: CANDIDATE";
    let baseline_bytes = b"CONTROLLED NEURAL PORT DOUBLE: BASELINE";
    let material = plan_fixture::material(&dataset, candidate_bytes, baseline_bytes);
    let (plan, candidate_plan, baseline_plan) = plan_fixture::plans(&material, &dataset);
    let mut provider = NeuralFinalHoldoutProviderV1::new(
        material.clone(),
        &plan,
        dataset.clone(),
        ledger.clone(),
        NeuralHoldoutRuntimeV1 {
            pin: material.candidate.clone(),
            parameters: candidate_bytes.to_vec(),
            inference: Arc::new(EqualScorePort),
        },
        NeuralHoldoutRuntimeV1 {
            pin: material.baseline.clone(),
            parameters: baseline_bytes.to_vec(),
            inference: Arc::new(EqualScorePort),
        },
    )
    .unwrap();
    let mut runner = plan_fixture::runner(&root.join("holdout-owner"));
    let temporal = runner
        .evaluate_temporal_comparison(&plan, &candidate_plan, &baseline_plan, &mut provider)
        .unwrap();
    let context = roles.context();
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let signed = roles.comparison_evidence(&bundle, &plan.metric_roles);
    let mut sink =
        eval::FileProductQualificationEvidenceSinkV1::new(root.join("controlled-qualification"))
            .unwrap();
    let qualification = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &signed,
            eval::ProductTimingEvidenceV1::Qualification,
            &roles.verifier,
            micros(),
            &mut sink,
        )
        .unwrap();
    assert_eq!(
        qualification.claim_scope,
        eval::EvaluationClaimScopeV1::Qualification
    );
    assert_eq!(
        qualification.decision.decision.disposition,
        eval::IndependentEvaluationDispositionV1::Ineligible
    );
    let request = eval::SelfEvolutionSelectionRequestV1 {
        selection_id: id("controlled-neural-bootstrap-denial"),
        predecessor_id: plan.frozen_plan.baseline_id.clone(),
        predecessor_generation: material.baseline.generation,
        predecessor_artifact_digest: material.baseline.payload_digest,
        candidate_id: qualification.candidate_id.clone(),
        candidate_generation: material.candidate.generation,
        candidate_artifact_digest: material.candidate.payload_digest,
    };
    let candidate_binding = roles.sign(
        /*index*/ 1,
        &eval::product_candidate_binding_payload_v1(&request, &qualification).unwrap(),
    );
    // No future observations or selector grant exist. These plain fields must
    // never be promoted by changing the scope of the original sealed receipt.
    let timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: micros(),
        windows: Vec::new(),
        observer: roles.sign(/*index*/ 2, b"explicitly-no-prospective-observation"),
    };
    let selector = roles.sign(/*index*/ 0, b"explicitly-no-selector-authority");
    let pin = material.candidate;
    let manifest = artifacts::ArtifactManifest {
        artifact_id: request.candidate_id.clone(),
        kind: artifacts::ArtifactKind::Parameters,
        generation: pin.generation,
        predecessor_id: Some(request.predecessor_id.clone()),
        content_digest: pin.payload_digest,
        objective_digest: pin.objective_digest,
        support_digest: pin.dataset_digest,
        producer_id: context.generator.principal_id.clone(),
        compatibility_digest: pin.compatibility_digest(),
        encoded_size_bytes: candidate_bytes.len() as u64,
    };
    let now = micros() / 1_000_000;
    let source = artifacts::LearningArtifactManifestV2 {
        artifact_id: manifest.artifact_id.clone(),
        kind: manifest.kind,
        generation: pin.generation,
        provenance_mode: artifacts::ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![pin.dataset_digest],
        lineage_digests: vec![material.baseline.payload_digest],
        predecessor_ids: vec![request.predecessor_id.clone()],
        rollback_predecessor: Some(request.predecessor_id.clone()),
        bytes_digest: pin.payload_digest,
        encoded_size_bytes: candidate_bytes.len() as u64,
        training_code_digest: hash("controlled-not-training"),
        runtime_tuple_digest: pin.execution_profile_digest,
        device_profile_digest: hash("controlled-not-hardware"),
        objective_class_digest: pin.objective_digest,
        compatibility_digest: pin.compatibility_digest(),
        schema_profile_digest: hash("controlled-raw-bytes"),
        normalization_digest: hash("controlled-none"),
        producer_id: manifest.producer_id.clone(),
        created_at: now,
        expires_at: now + 60,
    };
    // Intentionally invalid material cannot be opened before qualification.
    let snapshot_path = root.join("unadmitted-snapshot");
    let payload_path = root.join("unadmitted-payload");
    std::fs::write(&snapshot_path, b"not an admitted registry").unwrap();
    std::fs::write(&payload_path, candidate_bytes).unwrap();
    let owners = Arc::new(UnadmittedOwners::default());
    let input = EvaluatedCognitiveBootstrapV1 {
        snapshot: File::open(snapshot_path).unwrap(),
        payload: File::open(payload_path).unwrap(),
        selected: artifacts::PinnedCandidateSpec {
            manifest,
            registry_receipt: artifacts::RegistrySnapshotReceipt {
                binding: hash("not-admitted"),
                head_digest: hash("not-admitted"),
                file_digest: hash("not-admitted"),
                records: 0,
                encoded_bytes: 0,
            },
        },
        model_pin: NeuralCognitiveBootstrapModelV1 {
            pin,
            inference: owners.clone(),
        },
        source_manifest: source,
        current: owners.clone(),
        policy: eval::SelfEvolutionSelectionPolicyV1 {
            no_change_baseline_id: request.predecessor_id.clone(),
            no_change_baseline_digest: request.predecessor_artifact_digest,
            minimum_dataset_records: 1,
            minimum_future_window_micros: 1,
        },
        selection_request: request,
        evaluation_bundle: bundle,
        metric_roles: plan.metric_roles,
        evaluation_evidence: signed,
        longitudinal_time: timing,
        dataset_receipt: dataset,
        ledger_snapshot: ledger,
        verifier: roles.verifier,
        selector_evidence: selector,
        product_qualification: qualification,
        product_candidate_binding_evidence: candidate_binding,
    };
    let error = match config.with_evaluated_neural_cognitive_bootstrap(input) {
        Err(error) => error,
        Ok(_) => panic!("controlled Qualification must not install a neural product"),
    };
    assert!(
        matches!(error, AgentdError::Invalid(ref message) if message == "BindingMismatch"),
        "{error}"
    );
    assert_eq!(
        (
            owners.current_calls.load(Ordering::SeqCst),
            owners.inference_calls.load(Ordering::SeqCst)
        ),
        (0, 0)
    );
}

#[test]
fn neural_descriptor_schema_identity_and_authority_fields_fail_before_material_use() {
    let root = tempfile::tempdir().unwrap();
    let root = root.path().canonicalize().unwrap();
    let config = config(&root);
    let original = descriptor_fixture::untrusted_descriptor(&root, config.identity());
    let port = Arc::new(UnadmittedOwners::default());
    for (field, value, expected) in [
        (
            "schema",
            serde_json::json!("hepta.agentd.cognitive-bootstrap.v2"),
            "unsupported cognitive bootstrap schema/profile",
        ),
        (
            "profile",
            serde_json::json!("published_product_qualification_v1"),
            "unsupported cognitive bootstrap schema/profile",
        ),
        (
            "agent_id",
            serde_json::json!("00000000-0000-4000-8000-000000000220"),
            "cognitive bootstrap identity/generation mismatch",
        ),
        (
            "spawn_generation",
            serde_json::json!(2),
            "cognitive bootstrap identity/generation mismatch",
        ),
        (
            "final_use",
            serde_json::json!({"grant": "caller-selected"}),
            "unknown field",
        ),
        (
            "schema",
            serde_json::json!("hepta.agentd.cognitive-bootstrap.v3"),
            "cognitive bootstrap requires independent nonempty journal anchors",
        ),
    ] {
        let mut descriptor = original.clone();
        descriptor[field] = value;
        let path = root.join(format!("descriptor-{field}.json"));
        let bytes = serde_json::to_vec(&descriptor).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        let error = match codex_hepta_agentd::load_neural_cognitive_process_bootstrap_v1(
            &path,
            Digest32::of_bytes(&bytes),
            config.identity(),
            port.clone(),
        ) {
            Err(error) => error,
            Ok(_) => panic!("untrusted neural descriptor admitted"),
        };
        assert!(error.to_string().contains(expected), "{field}: {error}");
    }
    assert_eq!(port.inference_calls.load(Ordering::SeqCst), 0);
}
