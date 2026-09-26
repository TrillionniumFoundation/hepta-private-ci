use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::RwLock;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyAdmissionEvidenceV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::no_change_disposition_signing_payload_v1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::IterationCandidateStateV1;
use codex_hepta_learning_artifacts::IterationCandidateV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::IterationEvidenceKindV1;
use codex_hepta_learning_artifacts::IterationEvidenceV1;
use codex_hepta_learning_artifacts::IterationLedgerSnapshotV1;
use codex_hepta_learning_artifacts::IterationLedgerV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseJournal;
use codex_hepta_neuron::SparseTick;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_plasticity::AppendDisposition;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterGeneratorProfileV3;
use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ParameterPlasticitySignalV3;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::TopologyChangeV2;
use codex_hepta_plasticity::TopologyOperationV2;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::build_writer_handoff_plan_v1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

use crate::AgentdIdentity;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdState;
use crate::ConcretePlasticityOwnerEvidenceResolverV1;
use crate::PlasticityArtifactOwnerBindingV1;
use crate::PlasticityDynamicOwnerEvidenceResolverV1;
use crate::PlasticityDynamicSignalBindingV1;
use crate::PlasticityOwnerEvidenceKindV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityRuntimeBootstrapV1;
use crate::bootstrap_agentd_plasticity_writer_v1;
use crate::bootstrap_agentd_topology_writer_v1;
use crate::plasticity_eligibility_digest_v1;
use crate::plasticity_modulator_broadcast_digest_v1;
use crate::plasticity_modulator_digest_v1;
use crate::plasticity_parameter_signal_digest_v1;
use crate::reopen_agentd_plasticity_writer_v1;
use crate::reopen_agentd_topology_writer_v1;
use crate::resolve_agentd_plasticity_admission_v1;
use crate::resolve_agentd_topology_admission_v1;
use crate::self_iteration_coordinator::compose_self_iteration_coordinator_v1;
use crate::self_iteration_coordinator::self_iteration_coordinator_channel_at_v1;
use crate::self_iteration_parameter_evaluation_digest_v1;
use crate::self_iteration_parameter_submission_digest_v1;
use crate::self_iteration_topology_evaluation_digest_v1;
use crate::self_iteration_topology_submission_digest_v1;

const Q24: i64 = 1_i64 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("generation {value}: {error}"))
}

fn new_file(path: &Path) -> File {
    OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("create {}: {error}", path.display()))
}

fn existing_file(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("open {}: {error}", path.display()))
}

fn policy_manifest(
    artifact_id: &str,
    producer: &str,
    content_digest: Digest32,
    objective_digest: Digest32,
) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(artifact_id),
        kind: ArtifactKind::Policy,
        generation: generation(1),
        predecessor_id: None,
        content_digest,
        objective_digest,
        support_digest: digest(&format!("{artifact_id}:support")),
        producer_id: id(producer),
        compatibility_digest: digest(&format!("{artifact_id}:compatibility")),
        encoded_size_bytes: 64,
    }
}

fn sparse_config(selected_artifact_digest: Digest32) -> SparseConfig {
    SparseConfig {
        model_digest: selected_artifact_digest,
        normalization_digest: digest("normalization"),
        generation: generation(1),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: Q24 / 2,
        target_activity_q24: Q24 / 5,
        threshold_rate_q24: Q24 / 10,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    }
}

fn sparse_scope(objective_digest: Digest32) -> JournalScope {
    JournalScope {
        scope_digest: digest("plasticity-neuron-scope"),
        objective_digest,
    }
}

fn sparse_tick(objective_digest: Digest32) -> SparseTick {
    SparseTick {
        scope_digest: digest("plasticity-neuron-scope"),
        objective_digest,
        ndu_digest: digest("ndu-input"),
        body_digest: digest("body"),
        input_digest: digest("approved-input"),
        sequence: 1,
        monotonic_micros: 1,
        drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

fn ledger_decision(objective_digest: Digest32) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision:plasticity-owner"),
        episode_id: id("episode:plasticity-owner"),
        objective_digest,
        policy_id: id("policy:learning"),
        candidate_ids: vec![id("candidate:update"), id("abstain")],
        selected_candidate_id: id("candidate:update"),
        selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).expect("propensity"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("decision-support"),
    })
}

struct AgentdFixture {
    _temp: TempDir,
    registry: FleetRegistry,
    identity: AgentdIdentity,
}

impl AgentdFixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp");
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).expect("workspace");
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let record = registry.register(manifest).expect("register");
        registry
            .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
            .expect("starting");
        registry
            .compare_and_transition(&agent_id, 1, AgentLifecycle::Running)
            .expect("running");
        let identity = AgentdIdentity {
            agent_id,
            layout: record.layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources: record.manifest.resources,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: record.layout.app_server_socket().to_path_buf(),
        };
        Self {
            _temp: temp,
            registry,
            identity,
        }
    }

    fn state(&self) -> Arc<AgentdState> {
        let state =
            AgentdState::new(self.identity.clone(), self.registry.clone(), 16).expect("state");
        state.refresh_generation().expect("refresh running");
        state.mark_app_server_ready().expect("app ready");
        Arc::new(state)
    }
}

struct SigningFixture {
    keys: [SigningKey; 3],
    principals: Vec<AuthenticatedPrincipalV1>,
}

impl SigningFixture {
    fn new() -> Self {
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
            SigningKey::from_bytes(&[33; 32]),
        ];
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("plasticity-signer-{index}")),
                credential_chain_digest: digest(&format!("plasticity-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("plasticity-scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect();
        Self { keys, principals }
    }

    fn verifier(&self, objective_digest: Digest32) -> LearningEvidenceVerifierV1 {
        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("plasticity-scope"),
            objective_digest,
            authority_epoch: 7,
            signers: self
                .principals
                .iter()
                .zip(&self.keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("plasticity-controller-{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![match index {
                        0 => LearningEvidenceRoleV1::Generator,
                        1 => LearningEvidenceRoleV1::Observer,
                        _ => LearningEvidenceRoleV1::Evaluator,
                    }],
                    revoked_at: None,
                })
                .collect(),
        })
        .expect("verifier")
    }

    fn sign(
        &self,
        verifier: &LearningEvidenceVerifierV1,
        objective_digest: Digest32,
        signer: usize,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let principal = &self.principals[signer];
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("runtime-attestation-{signer}-{role:?}")),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest,
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[signer].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
}

struct OwnerSources {
    artifacts: ArtifactRegistry,
    dataset: codex_hepta_learning_ledger::DatasetSnapshotReceiptV3,
    ndu: Arc<RwLock<NduProjectionJournalV1>>,
    neuron: Arc<Mutex<SparseJournal>>,
    neuron_anchor: codex_hepta_neuron::JournalAnchor,
    binding: PlasticityDynamicSignalBindingV1,
    modulator_values: Vec<FixedQ32>,
    profile: ParameterGeneratorProfileV3,
    generated: codex_hepta_plasticity::GeneratedParameterCandidateSetV3,
    owner_policy: PlasticityOwnerEvidencePolicyV1,
    objective_digest: Digest32,
    dataset_digest: Digest32,
    update_rule_digest: Digest32,
    modulator_digest: Digest32,
    broadcast_digest: Digest32,
    eligibility_digest: Digest32,
}

fn build_owner_sources(
    root: &Path,
    ledger: &DurableLedger,
    objective_digest: Digest32,
    selected_artifact_digest: Digest32,
) -> OwnerSources {
    let window = ProposalWindowV2 {
        window_id: id("window:lifetime"),
        window_digest: digest("window:lifetime"),
    };
    let update_rule_digest = digest("update-rule:lifetime");

    let modulator_values = vec![FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)];
    let ndu_subject_digest = digest("agent:plasticity-subject");
    let modulator_digest =
        plasticity_modulator_digest_v1(objective_digest, ndu_subject_digest, &modulator_values)
            .expect("modulator digest");
    let mut ndu_journal = NduProjectionJournalV1::new();
    ndu_journal
        .append_projection(
            NduProjectionKindV1::Utility,
            digest("ndu:modulator-projection"),
            objective_digest,
            ndu_subject_digest,
            modulator_digest,
        )
        .expect("append NDU projection");
    ndu_journal
        .select_projection(
            digest("ndu:modulator-selection"),
            objective_digest,
            ndu_subject_digest,
            modulator_digest,
        )
        .expect("select NDU projection");
    let ndu = Arc::new(RwLock::new(ndu_journal));

    let neuron_path = root.join("neuron.journal");
    let mut neuron_journal = SparseJournal::open(
        new_file(&neuron_path),
        sparse_config(selected_artifact_digest),
        sparse_scope(objective_digest),
        16,
    )
    .expect("neuron journal");
    neuron_journal
        .commit(Digest32::ZERO, &sparse_tick(objective_digest))
        .expect("neuron commit");
    let neuron_anchor = neuron_journal
        .current_anchor()
        .expect("neuron anchor")
        .expect("neuron checkpoint");
    let checkpoint = neuron_journal
        .current()
        .expect("current neuron")
        .expect("checkpoint");
    let eligibility_digest =
        plasticity_eligibility_digest_v1(checkpoint).expect("eligibility digest");
    let eligibility_raw = checkpoint.eligibility_q24()[0]
        .checked_mul(1_i64 << 8)
        .expect("Q24 to Q32");
    let eligibility = FixedQ32::from_raw(eligibility_raw);
    let neuron = Arc::new(Mutex::new(neuron_journal));

    let binding = PlasticityDynamicSignalBindingV1 {
        layer_id: id("layer:lifetime"),
        parameter_id: id("parameter:lifetime"),
        eligibility_index: 0,
        modulator_weights: vec![FixedQ32::ONE],
    };
    let broadcast_digest = plasticity_modulator_broadcast_digest_v1(std::iter::once(&binding))
        .expect("broadcast digest");
    let modulator = modulator_values[0];
    let learning_rate = FixedQ32::ONE;
    let lower_bound = FixedQ32::from_raw(-FixedQ32::ONE.raw());
    let upper_bound = FixedQ32::ONE;
    let signal_digest = plasticity_parameter_signal_digest_v1(
        &binding.layer_id,
        &binding.parameter_id,
        eligibility,
        modulator,
        learning_rate,
        lower_bound,
        upper_bound,
        eligibility_digest,
        modulator_digest,
        broadcast_digest,
    )
    .expect("signal digest");

    let mutation_policy = build_parameter_mutation_policy_v1(
        id("policy:mutation:lifetime"),
        digest("mutation-grammar:lifetime"),
        selected_artifact_digest,
        window.clone(),
        vec![ParameterMutationRuleV1 {
            parameter_id: binding.parameter_id.clone(),
            layer_id: binding.layer_id.clone(),
            surface: ParameterMutationSurfaceV1::LearnableParameter,
            minimum_delta: lower_bound,
            maximum_delta: upper_bound,
        }],
    )
    .expect("mutation policy");

    let mut artifacts = ArtifactRegistry::new();
    for (event_id, manifest) in [
        (
            "event:baseline",
            ArtifactManifest {
                artifact_id: id("artifact:baseline"),
                kind: ArtifactKind::Model,
                generation: generation(1),
                predecessor_id: None,
                content_digest: selected_artifact_digest,
                objective_digest,
                support_digest: digest("baseline:support"),
                producer_id: id("owner:model"),
                compatibility_digest: digest("baseline:compatibility"),
                encoded_size_bytes: 128,
            },
        ),
        (
            "event:update-rule",
            policy_manifest(
                "policy:update-rule",
                "owner:update-rule",
                update_rule_digest,
                objective_digest,
            ),
        ),
        (
            "event:mutation-policy",
            policy_manifest(
                "policy:mutation",
                "owner:mutation-policy",
                mutation_policy.policy_digest,
                objective_digest,
            ),
        ),
        (
            "event:broadcast",
            policy_manifest(
                "policy:broadcast",
                "owner:broadcast",
                broadcast_digest,
                objective_digest,
            ),
        ),
    ] {
        artifacts
            .append(ArtifactEvent::Register {
                event_id: id(event_id),
                manifest,
            })
            .expect("artifact append");
    }

    let ledger_snapshot = ledger.snapshot().expect("ledger snapshot");
    let dataset = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset:lifetime"),
            producer: AuthenticatedPrincipalV1 {
                principal_id: id("owner:dataset"),
                credential_chain_digest: digest("dataset:credential"),
                signing_key_digest: digest("dataset:key"),
                scope_digest: digest("dataset:scope"),
                authority_epoch: 1,
                authenticated_at: 10,
                expires_at: 100,
            },
            ledger_head_digest: ledger_snapshot.head_digest,
            objective_digest,
            eligible_frontier: 1,
            outcome_watermark: 1,
            correction_cut_digest: digest("dataset:correction"),
            revocation_cut_digest: digest("dataset:revocation"),
            inclusion_policy_digest: digest("dataset:policy"),
            source_record_digests: vec![ledger_snapshot.head_digest],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .expect("dataset freeze");
    let dataset_digest = dataset.snapshot.dataset_digest;

    let profile = ParameterGeneratorProfileV3 {
        selected_artifact_digest,
        window,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: binding.layer_id.clone(),
            baseline_squared_l2_raw_q64: 1_u128 << 64,
        }],
        mutation_policy,
        update_scales: vec![FixedQ32::ONE],
        signals: vec![ParameterPlasticitySignalV3 {
            layer_id: binding.layer_id.clone(),
            parameter_id: binding.parameter_id.clone(),
            eligibility,
            modulator,
            learning_rate,
            lower_bound,
            upper_bound,
            evidence_digest: signal_digest,
        }],
    };
    let generated = generate_parameter_candidates_v3(profile.clone()).expect("generate");
    assert_eq!(
        generated
            .candidates
            .iter()
            .filter(|candidate| {
                candidate.kind == codex_hepta_plasticity::ParameterCandidateKindV2::Update
            })
            .count(),
        0,
        "fixture must exercise independently attested no-update terminal path"
    );

    let owner_policy = PlasticityOwnerEvidencePolicyV1::from_rules(vec![
        (PlasticityOwnerEvidenceKindV1::Dataset, id("owner:dataset")),
        (
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            id("owner:update-rule"),
        ),
        (
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
            id("owner:mutation-policy"),
        ),
        (
            PlasticityOwnerEvidenceKindV1::Modulator,
            id("owner:utility.ndu"),
        ),
        (
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            id("owner:broadcast"),
        ),
        (
            PlasticityOwnerEvidenceKindV1::Eligibility,
            id("owner:neuron.runtime"),
        ),
        (
            PlasticityOwnerEvidenceKindV1::ParameterSignal,
            id("owner:neuron.runtime"),
        ),
    ])
    .expect("owner policy");

    OwnerSources {
        artifacts,
        dataset,
        ndu,
        neuron,
        neuron_anchor,
        binding,
        modulator_values,
        profile,
        generated,
        owner_policy,
        objective_digest,
        dataset_digest,
        update_rule_digest,
        modulator_digest,
        broadcast_digest,
        eligibility_digest,
    }
}

fn resolver(sources: &OwnerSources) -> ConcretePlasticityOwnerEvidenceResolverV1 {
    let dynamic = PlasticityDynamicOwnerEvidenceResolverV1::new(
        sources.objective_digest,
        digest("agent:plasticity-subject"),
        id("owner:utility.ndu"),
        id("owner:neuron.runtime"),
        Arc::clone(&sources.ndu),
        sources.modulator_values.clone(),
        Arc::clone(&sources.neuron),
        sources.neuron_anchor,
        sources.artifacts.clone(),
        id("policy:broadcast"),
        vec![sources.binding.clone()],
        40,
        60,
    )
    .expect("dynamic resolver");
    ConcretePlasticityOwnerEvidenceResolverV1::new(
        sources.dataset.clone(),
        sources.artifacts.clone(),
        40,
        60,
        vec![
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
                artifact_id: id("policy:update-rule"),
            },
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::MutationPolicy,
                artifact_id: id("policy:mutation"),
            },
        ],
        Box::new(dynamic),
    )
    .expect("composed owner resolver")
}

fn signed_request(
    sources: &OwnerSources,
    ledger: &DurableLedger,
    signing: &SigningFixture,
    verifier: &LearningEvidenceVerifierV1,
) -> ParameterPlasticityProductRequestV1 {
    let admission = resolve_agentd_plasticity_admission_v1(
        &crate::AgentdPlasticityAdmissionInputV1 {
            baseline_id: id("artifact:baseline"),
            objective_digest: sources.objective_digest,
            generator_profile: sources.profile.clone(),
            generated: sources.generated.clone(),
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            dataset_digest: sources.dataset_digest,
            update_rule_digest: sources.update_rule_digest,
            modulator_digest: sources.modulator_digest,
            modulator_broadcast_digest: sources.broadcast_digest,
            eligibility_digest: sources.eligibility_digest,
        },
        &sources.artifacts,
        ledger,
        &resolver(sources),
        &sources.owner_policy,
        50,
    )
    .expect("resolve admission");

    let generator_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        0,
        LearningEvidenceRoleV1::Generator,
        &parameter_generator_signing_payload_v3(&sources.generated),
    );
    let admission_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        1,
        LearningEvidenceRoleV1::Observer,
        &plasticity_admission_signing_payload_v1(&admission),
    );
    let no_change_payload =
        no_change_disposition_signing_payload_v1(&sources.generated, &admission)
            .expect("no-change payload");
    let no_change_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        2,
        LearningEvidenceRoleV1::Evaluator,
        &no_change_payload,
    );

    ParameterPlasticityProductRequestV1 {
        proposal_id: id("proposal:agentd-lifetime"),
        generator_profile: sources.profile.clone(),
        generated: sources.generated.clone(),
        generator_attestation,
        admission,
        admission_attestation,
        no_change_attestation: Some(no_change_attestation),
        evaluations: Vec::new(),
        expected_registry_predecessor: Digest32::ZERO,
    }
}

fn signed_topology_request(
    sources: &OwnerSources,
    ledger: &DurableLedger,
    signing: &SigningFixture,
    verifier: &LearningEvidenceVerifierV1,
) -> TopologyPlasticityProductRequestV1 {
    let selected_artifact_digest = sources.profile.selected_artifact_digest;
    let window = ProposalWindowV2 {
        window_id: id("window:topology:lifetime"),
        window_digest: digest("window:topology:lifetime"),
    };
    let handoff = build_writer_handoff_plan_v1(
        id("module:topology:lifetime"),
        id("owner:topology:current"),
        id("owner:topology:next"),
        1,
        2,
        digest("topology:source-store:lifetime"),
        digest("topology:migration:lifetime"),
        digest("topology:rollback:lifetime"),
        digest("topology:ack:lifetime"),
    )
    .expect("topology handoff");
    let change = TopologyChangeV2 {
        module_id: id("module:topology:lifetime"),
        operation: TopologyOperationV2::Replace,
        predecessor_digest: Some(digest("topology:predecessor:lifetime")),
        candidate_digest: Some(digest("topology:candidate:lifetime")),
        capability_typing_digest: digest("topology:capability:lifetime"),
        compatibility_plan_digest: digest("topology:compatibility:lifetime"),
        lesion_ablation_digest: digest("topology:lesion:lifetime"),
        resource_review_digest: digest("topology:resource:lifetime"),
        security_review_digest: digest("topology:security:lifetime"),
        migration_digest: handoff.migration_digest,
        rollback_digest: handoff.rollback_digest,
        writer_handoff_digest: handoff.plan_digest,
        evidence_digest: digest("topology:evidence:lifetime"),
    };
    let mut request = TopologyPlasticityProductRequestV1 {
        proposal_id: id("proposal:topology:agentd-lifetime"),
        proposer_generation_id: signing.principals[0].principal_id.clone(),
        selected_artifact_digest,
        window: window.clone(),
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        rollback_predecessor_digest: selected_artifact_digest,
        changes: vec![change],
        handoffs: vec![handoff],
        admission: TopologyAdmissionEvidenceV1 {
            baseline_id: id("artifact:baseline"),
            objective_digest: sources.objective_digest,
            selected_artifact_digest,
            artifact_registry_head_digest: Digest32::ZERO,
            qualification_evidence_head_digest: Digest32::ZERO,
            window: window.clone(),
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            generation_digest: Digest32::ZERO,
            evaluation_receipt_digest: digest("topology:evaluation:lifetime"),
        },
        generator_attestation: signing.sign(
            verifier,
            sources.objective_digest,
            0,
            LearningEvidenceRoleV1::Generator,
            b"topology-placeholder",
        ),
        observer_attestation: signing.sign(
            verifier,
            sources.objective_digest,
            1,
            LearningEvidenceRoleV1::Observer,
            b"topology-placeholder",
        ),
        evaluator_attestation: signing.sign(
            verifier,
            sources.objective_digest,
            2,
            LearningEvidenceRoleV1::Evaluator,
            b"topology-placeholder",
        ),
        expected_registry_predecessor: Digest32::ZERO,
    };

    let generation_payload =
        topology_generation_signing_payload_v1(&request).expect("topology generation payload");
    let generation_digest = Digest32::of_bytes(&generation_payload);
    request.admission = resolve_agentd_topology_admission_v1(
        &crate::AgentdTopologyAdmissionInputV1 {
            baseline_id: id("artifact:baseline"),
            objective_digest: sources.objective_digest,
            selected_artifact_digest,
            window,
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            generation_digest,
            evaluation_receipt_digest: request.admission.evaluation_receipt_digest,
        },
        &sources.artifacts,
        ledger,
    )
    .expect("resolve topology admission");
    request.generator_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        0,
        LearningEvidenceRoleV1::Generator,
        &generation_payload,
    );
    request.observer_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        1,
        LearningEvidenceRoleV1::Observer,
        &topology_admission_signing_payload_v1(&request.admission),
    );
    request.evaluator_attestation = signing.sign(
        verifier,
        sources.objective_digest,
        2,
        LearningEvidenceRoleV1::Evaluator,
        &topology_evaluation_signing_payload_v1(&request.admission),
    );
    request
}

fn iteration_evidence(
    candidate_id: &StableId,
    actor_id: StableId,
    kind: IterationEvidenceKindV1,
    label: &str,
) -> IterationEvidenceV1 {
    IterationEvidenceV1 {
        evidence_id: id(&format!("iteration-evidence:{label}")),
        candidate_id: candidate_id.clone(),
        actor_id,
        kind,
        evidence_digest: digest(&format!("iteration-evidence:{label}:digest")),
        observed_unix_seconds: 45,
    }
}

fn evaluated_iteration_snapshot(
    envelope: IterationEnvelopeV1,
    candidate: IterationCandidateV1,
    evaluator_identity: StableId,
    evaluation_digest: Digest32,
) -> IterationLedgerSnapshotV1 {
    let candidate_id = candidate.candidate_id.clone();
    let generator = candidate.generator_identity.clone();
    let mut ledger = IterationLedgerV1::new(envelope).expect("iteration ledger");
    ledger
        .append_candidate(candidate)
        .expect("iteration candidate");
    ledger
        .transition(
            &candidate_id,
            IterationCandidateStateV1::StaticallyValidated,
            iteration_evidence(
                &candidate_id,
                generator.clone(),
                IterationEvidenceKindV1::StaticValidation,
                "static",
            ),
        )
        .expect("static validation");
    ledger
        .transition(
            &candidate_id,
            IterationCandidateStateV1::SandboxTested,
            iteration_evidence(
                &candidate_id,
                generator,
                IterationEvidenceKindV1::Sandbox,
                "sandbox",
            ),
        )
        .expect("sandbox validation");
    let mut evaluation = iteration_evidence(
        &candidate_id,
        evaluator_identity,
        IterationEvidenceKindV1::Evaluation,
        "evaluation",
    );
    evaluation.evidence_digest = evaluation_digest;
    ledger
        .transition(
            &candidate_id,
            IterationCandidateStateV1::IndependentlyEvaluated,
            evaluation,
        )
        .expect("independent evaluation");
    ledger.snapshot()
}

fn parameter_iteration_snapshot(
    request: &ParameterPlasticityProductRequestV1,
) -> IterationLedgerSnapshotV1 {
    let envelope = IterationEnvelopeV1 {
        envelope_id: id("iteration-envelope:parameter:lifetime"),
        base_commit: digest("iteration-base-commit:parameter"),
        base_tree: digest("iteration-base-tree:parameter"),
        objective_digest: request.admission.objective_digest,
        grammar_digest: request
            .generator_profile
            .mutation_policy
            .mutation_grammar_digest,
        maximum_files: 4,
        maximum_diff_bytes: 4_096,
        maximum_candidates: 4,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 90,
    };
    let evaluation_digest = self_iteration_parameter_evaluation_digest_v1(request)
        .expect("parameter evaluation digest");
    let evaluator_identity = request
        .no_change_attestation
        .as_ref()
        .map(|attestation| attestation.principal_id.clone())
        .or_else(|| {
            request
                .evaluations
                .first()
                .map(|evaluation| evaluation.bundle.evaluator.principal_id.clone())
        })
        .expect("parameter evaluator identity");
    let candidate = IterationCandidateV1 {
        candidate_id: request.proposal_id.clone(),
        envelope_id: envelope.envelope_id.clone(),
        generator_identity: request.generator_attestation.principal_id.clone(),
        semantic_diff_digest: self_iteration_parameter_submission_digest_v1(&envelope, request)
            .expect("parameter iteration digest"),
        test_plan_digest: evaluation_digest,
        rollback_digest: request.admission.selected_artifact_digest,
        predecessor: Some(request.admission.baseline_id.clone()),
        state: IterationCandidateStateV1::Drafted,
    };
    evaluated_iteration_snapshot(envelope, candidate, evaluator_identity, evaluation_digest)
}

fn topology_iteration_snapshot(
    request: &TopologyPlasticityProductRequestV1,
) -> IterationLedgerSnapshotV1 {
    let envelope = IterationEnvelopeV1 {
        envelope_id: id("iteration-envelope:topology:lifetime"),
        base_commit: digest("iteration-base-commit:topology"),
        base_tree: digest("iteration-base-tree:topology"),
        objective_digest: request.admission.objective_digest,
        grammar_digest: digest("iteration-topology-grammar:lifetime"),
        maximum_files: 8,
        maximum_diff_bytes: 8_192,
        maximum_candidates: 4,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: 90,
    };
    let evaluation_digest = self_iteration_topology_evaluation_digest_v1(request);
    let candidate = IterationCandidateV1 {
        candidate_id: request.proposal_id.clone(),
        envelope_id: envelope.envelope_id.clone(),
        generator_identity: request.proposer_generation_id.clone(),
        semantic_diff_digest: self_iteration_topology_submission_digest_v1(&envelope, request)
            .expect("topology iteration digest"),
        test_plan_digest: evaluation_digest,
        rollback_digest: request.selected_artifact_digest,
        predecessor: Some(request.admission.baseline_id.clone()),
        state: IterationCandidateStateV1::Drafted,
    };
    evaluated_iteration_snapshot(
        envelope,
        candidate,
        request.evaluator_attestation.principal_id.clone(),
        evaluation_digest,
    )
}

struct RuntimeFiles {
    ledger: PathBuf,
    parameter_registry: PathBuf,
    parameter_anchor: PathBuf,
    topology_registry: PathBuf,
    topology_anchor: PathBuf,
}

fn runtime_files(root: &Path) -> RuntimeFiles {
    RuntimeFiles {
        ledger: root.join("learning-ledger"),
        parameter_registry: root.join("parameter-registry"),
        parameter_anchor: root.join("parameter-anchor"),
        topology_registry: root.join("topology-registry"),
        topology_anchor: root.join("topology-anchor"),
    }
}

#[tokio::test]
async fn agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently() {
    let daemon = AgentdFixture::new();
    let runtime_root = tempfile::tempdir().expect("runtime root");
    let files = runtime_files(runtime_root.path());
    let ledger_binding = digest("ledger:binding");

    let mut ledger =
        DurableLedger::create(new_file(&files.ledger), ledger_binding, 32).expect("ledger create");
    ledger
        .append_qualification(
            Digest32::ZERO,
            ledger_decision(digest("plasticity-objective")),
        )
        .expect("ledger append");
    let ledger_snapshot = ledger.snapshot().expect("ledger snapshot");
    let ledger_anchor = LedgerAnchor {
        sequence: u64::try_from(ledger_snapshot.records().len()).expect("ledger sequence"),
        chain_digest: ledger_snapshot.head_digest,
    };

    let selected_artifact_digest = digest("selected-artifact:lifetime");
    let sources = build_owner_sources(
        runtime_root.path(),
        &ledger,
        digest("plasticity-objective"),
        selected_artifact_digest,
    );
    let signing = SigningFixture::new();
    let verifier = signing.verifier(sources.objective_digest);
    let request = signed_request(&sources, &ledger, &signing, &verifier);
    let topology_request = signed_topology_request(&sources, &ledger, &signing, &verifier);
    let parameter_iteration = parameter_iteration_snapshot(&request);
    let topology_iteration = topology_iteration_snapshot(&topology_request);

    let parameter_scope = digest("parameter-registry:scope");
    let topology_scope = digest("topology-registry:scope");
    let (parameter_writer, parameter_anchor_store) = bootstrap_agentd_plasticity_writer_v1(
        new_file(&files.parameter_registry),
        new_file(&files.parameter_anchor),
        parameter_scope,
        32,
    )
    .expect("parameter writer");
    let (topology_writer, topology_anchor_store) = bootstrap_agentd_topology_writer_v1(
        new_file(&files.topology_registry),
        new_file(&files.topology_anchor),
        topology_scope,
        32,
    )
    .expect("topology writer");

    let bootstrap = PlasticityRuntimeBootstrapV1::new(
        8,
        sources.artifacts.clone(),
        ledger,
        Box::new(resolver(&sources)),
        sources.owner_policy.clone(),
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )
    .expect("runtime bootstrap");
    let state = daemon.state();
    let owner = crate::plasticity_runtime::compose_plasticity_runtime_v1(&state, Some(bootstrap))
        .expect("compose daemon plasticity owner");
    let (coordinator, coordinator_bootstrap) =
        self_iteration_coordinator_channel_at_v1(8, 50).expect("coordinator channel");
    let coordinator_owner = compose_self_iteration_coordinator_v1(Some(coordinator_bootstrap))
        .expect("coordinator owner");
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&state),
        owner,
        cancellation.clone(),
    );
    let coordinator_task =
        tokio::spawn(coordinator_owner.run(Arc::clone(&state), cancellation.clone()));

    let mut forged_evaluator = parameter_iteration.clone();
    forged_evaluator
        .events
        .last_mut()
        .expect("evaluation event")
        .evidence
        .actor_id = id("forged-independent-evaluator");
    assert!(matches!(
        coordinator
            .submit_parameter(forged_evaluator, request.clone())
            .await,
        Err(crate::SelfIterationCoordinatorErrorV1::CandidateBinding(
            "independent evaluation evidence"
        ))
    ));

    let mut forged_evidence = parameter_iteration.clone();
    forged_evidence
        .events
        .last_mut()
        .expect("evaluation event")
        .evidence
        .evidence_digest = digest("forged-independent-evaluation");
    assert!(matches!(
        coordinator
            .submit_parameter(forged_evidence, request.clone())
            .await,
        Err(crate::SelfIterationCoordinatorErrorV1::CandidateBinding(
            "independent evaluation evidence"
        ))
    ));

    let mut future_evaluation = parameter_iteration.clone();
    future_evaluation
        .events
        .last_mut()
        .expect("evaluation event")
        .evidence
        .observed_unix_seconds = 51;
    assert!(matches!(
        coordinator
            .submit_parameter(future_evaluation, request.clone())
            .await,
        Err(crate::SelfIterationCoordinatorErrorV1::CandidateBinding(
            "independent evaluation evidence"
        ))
    ));

    let mut unevaluated = parameter_iteration.clone();
    unevaluated.events.pop();
    unevaluated
        .candidates
        .first_mut()
        .expect("iteration candidate")
        .state = IterationCandidateStateV1::SandboxTested;
    assert!(matches!(
        coordinator
            .submit_parameter(unevaluated, request.clone())
            .await,
        Err(crate::SelfIterationCoordinatorErrorV1::CandidateState)
    ));

    let mut expired = parameter_iteration.clone();
    expired.envelope.expiry_unix_seconds = 49;
    assert!(matches!(
        coordinator.submit_parameter(expired, request.clone()).await,
        Err(crate::SelfIterationCoordinatorErrorV1::EnvelopeExpired)
    ));

    let mut drifted = request.clone();
    drifted.expected_registry_predecessor = digest("drifted-predecessor");
    assert!(
        coordinator
            .submit_parameter(parameter_iteration.clone(), drifted)
            .await
            .is_err(),
        "request drift must reject before the plasticity writer"
    );

    let (parameter_coordination, first) = coordinator
        .submit_parameter(parameter_iteration.clone(), request.clone())
        .await
        .expect("first coordinated product proposal");
    assert_eq!(parameter_coordination.candidate_id, request.proposal_id);
    assert_eq!(
        parameter_coordination.product_composition_digest,
        first.composition_digest
    );
    assert_eq!(
        first.disposition,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate
    );
    assert_eq!(first.registry.sequence, 1);
    assert_eq!(first.registry.disposition, AppendDisposition::Inserted);

    let (topology_coordination, first_topology) = coordinator
        .submit_topology(topology_iteration.clone(), topology_request.clone())
        .await
        .expect("first coordinated topology product proposal");
    assert_eq!(
        topology_coordination.candidate_id,
        topology_request.proposal_id
    );
    assert_eq!(
        topology_coordination.product_composition_digest,
        first_topology.composition_digest
    );
    assert_eq!(first_topology.durable.sequence, 1);
    assert_eq!(
        first_topology.durable.disposition,
        AppendDisposition::Inserted
    );

    cancellation.cancel();
    owner_task
        .await
        .expect("owner task join")
        .expect("owner task shutdown");
    coordinator_task
        .await
        .expect("coordinator task join")
        .expect("coordinator task shutdown");
    drop(state);

    let recovered_ledger = DurableLedger::recover(
        existing_file(&files.ledger),
        ledger_binding,
        32,
        LedgerRecovery::Acknowledged(ledger_anchor),
    )
    .expect("recover ledger");
    let (parameter_writer, parameter_anchor_store) = reopen_agentd_plasticity_writer_v1(
        existing_file(&files.parameter_registry),
        existing_file(&files.parameter_anchor),
        parameter_scope,
        32,
    )
    .expect("reopen parameter writer");
    let (topology_writer, topology_anchor_store) = reopen_agentd_topology_writer_v1(
        existing_file(&files.topology_registry),
        existing_file(&files.topology_anchor),
        topology_scope,
        32,
    )
    .expect("reopen acknowledged topology writer");

    let restarted_state = daemon.state();
    let restarted_bootstrap = PlasticityRuntimeBootstrapV1::new(
        8,
        sources.artifacts.clone(),
        recovered_ledger,
        Box::new(resolver(&sources)),
        sources.owner_policy.clone(),
        signing.verifier(sources.objective_digest),
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )
    .expect("restart bootstrap");
    let restarted_owner = crate::plasticity_runtime::compose_plasticity_runtime_v1(
        &restarted_state,
        Some(restarted_bootstrap),
    )
    .expect("compose restarted daemon plasticity owner");
    let (restarted_coordinator, restarted_coordinator_bootstrap) =
        self_iteration_coordinator_channel_at_v1(8, 50).expect("restart coordinator channel");
    let restarted_coordinator_owner =
        compose_self_iteration_coordinator_v1(Some(restarted_coordinator_bootstrap))
            .expect("restart coordinator owner");
    let restarted_cancellation = CancellationToken::new();
    let restarted_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&restarted_state),
        restarted_owner,
        restarted_cancellation.clone(),
    );
    let restarted_coordinator_task = tokio::spawn(
        restarted_coordinator_owner
            .run(Arc::clone(&restarted_state), restarted_cancellation.clone()),
    );

    let (second_coordination, second) = restarted_coordinator
        .submit_parameter(parameter_iteration, request)
        .await
        .expect("coordinated idempotent replay after restart");
    assert_eq!(
        second_coordination.coordination_digest,
        parameter_coordination.coordination_digest
    );
    assert_eq!(second.registry.sequence, 1);
    assert_eq!(second.registry.disposition, AppendDisposition::Unchanged);
    assert_eq!(
        second.committed_registry_anchor,
        first.committed_registry_anchor
    );

    let (second_topology_coordination, second_topology) = restarted_coordinator
        .submit_topology(topology_iteration, topology_request)
        .await
        .expect("coordinated idempotent topology replay after restart");
    assert_eq!(
        second_topology_coordination.coordination_digest,
        topology_coordination.coordination_digest
    );
    assert_eq!(second_topology.durable.sequence, 1);
    assert_eq!(
        second_topology.durable.disposition,
        AppendDisposition::Unchanged
    );
    assert_eq!(
        second_topology.next_registry_anchor,
        first_topology.next_registry_anchor
    );

    restarted_cancellation.cancel();
    restarted_task
        .await
        .expect("restart task join")
        .expect("restart task shutdown");
    restarted_coordinator_task
        .await
        .expect("restart coordinator task join")
        .expect("restart coordinator task shutdown");
    drop(restarted_state);

    let (reconciled, _anchor_store): (
        codex_hepta_intelligence::AnchoredPlasticityWriterV1,
        AgentdPlasticityAnchorStoreV1,
    ) = reopen_agentd_plasticity_writer_v1(
        existing_file(&files.parameter_registry),
        existing_file(&files.parameter_anchor),
        parameter_scope,
        32,
    )
    .expect("final reconcile");
    assert_eq!(reconciled.record_count().expect("record count"), 1);
    assert_eq!(
        reconciled.current_anchor().expect("current anchor"),
        Some(first.committed_registry_anchor)
    );
}
