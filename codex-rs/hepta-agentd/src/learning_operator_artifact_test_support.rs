//! Genuine final-use fit, two durable ledgers and signed file-owner fixtures.
use crate::learning_operator_artifact_owner::*;
use crate::learning_operator_coordinator::LearningOperatorShadowRequestV1;
use crate::learning_operator_shadow_loader::EvaluatedTabularLoadBindingV3;
use crate::learning_operator_test_support::LearningFixture;
use codex_hepta_bellman_operator::*;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
const NOW: u64 = 50_000_000;
const EXPIRY: u64 = 100_000_000;

pub(crate) struct Fixture {
    pub training: LearningFixture,
    pub evaluation: LearningFixture,
    pub candidate: FinalUseTabularCandidateV1,
    pub selection: VerifiedSelfEvolutionSelectionV1,
    pub artifacts: LearningOperatorArtifactOwnerV1,
    pub publication: LearningArtifactPublishRequestV1,
    pub run: LearningOperatorShadowRequestV1,
    pub control: WorkControlV1,
    pub directory: tempfile::TempDir,
    pub config: LearningArtifactOwnerServiceConfigV1,
    profile: TrainingProfileV1,
}

impl Fixture {
    pub(crate) fn new() -> Self {
        Self::new_with_head_actor_window(EXPIRY, /*revoked_at*/ None)
    }

    pub(crate) fn new_with_head_actor_window(expires_at: u64, revoked_at: Option<u64>) -> Self {
        let training = LearningFixture::new_with_prefix("training-");
        let evaluation = LearningFixture::new_with_prefix("evaluation-");
        let profile = TrainingProfileV1::new(
            training.trust.objective_digest,
            digest("sensors"),
            training.receipt.snapshot.eligible_frontier,
            1,
            FixedQ32::from_raw(100),
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap();
        let control = WorkControlV1::new();
        let candidate = fit_candidate(&training, &profile, &control, 6_000_000, 7_000_000);
        let directory = tempfile::tempdir().unwrap();
        let key = SigningKey::from_bytes(&[9; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-owner"),
            registry_id: id("withdrawals"),
            scope_id: id("scope"),
        });
        let scope = withdrawals.scope_digest().unwrap();
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("artifact-owner"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 7,
            maximum_authority_epoch: 7,
            valid_from: 1,
            expires_at: EXPIRY,
            revoked_at: None,
        };
        let mut head_signer = signer.clone();
        head_signer.expires_at = expires_at;
        head_signer.revoked_at = revoked_at;
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: scope,
            minimum_registry_generation: Generation::new(1).unwrap(),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 7,
            writer_signers: vec![signer],
            head_signers: vec![head_signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("writer"),
            producer_id: id("generator"),
            registry_id: id("registry"),
            withdrawal_scope_digest: scope,
            signer_id: id("artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 7,
            lease_generation: 1,
            issued_at: 1,
            expires_at: EXPIRY,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.path().to_path_buf(),
            trust,
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: NOW,
        };
        let mut service = LearningArtifactOwnerService::open(config.clone()).unwrap();
        let mut baseline = manifest(&candidate, &training);
        baseline.artifact_id = id("baseline");
        baseline.generation = Generation::new(1).unwrap();
        baseline.predecessor_ids.clear();
        baseline.rollback_predecessor = None;
        baseline.bytes_digest = Digest32::of_bytes(b"baseline");
        baseline.encoded_size_bytes = 8;
        let baseline_request = make_publication(
            &service,
            baseline,
            b"baseline".to_vec(),
            id("baseline-operation"),
            &key,
        );
        service.publish(baseline_request).unwrap();
        let predecessor = service
            .registry()
            .manifest(&id("baseline"))
            .unwrap()
            .clone();
        let view = candidate.publication_view();
        let target = manifest(&candidate, &training);
        let publication = make_publication(
            &service,
            target,
            view.payload().to_vec(),
            id("operator-run"),
            &key,
        );
        let mut staged = service.registry().clone();
        stage(&mut staged, &publication);
        let selected_manifest = staged.manifest(view.artifact_id()).unwrap();
        let selection = evaluation.selection(&predecessor, selected_manifest);
        let run = LearningOperatorShadowRequestV1 {
            run_id: id("operator-run"),
            owner_id: training.receipt.producer.principal_id.clone(),
            producer_id: id("generator"),
            objective_digest: view.objective_digest(),
            training_source_digest: training.receipt.snapshot.dataset_digest,
            evaluation_source_digest: evaluation.receipt.snapshot.dataset_digest,
            predecessor_artifact_digest: predecessor.content_digest,
            predecessor_generation: predecessor.generation,
            expected_authority_epoch: 7,
            expected_stop_epoch: 1,
            now_unix_micros: NOW,
            deadline_unix_micros: 90_000_000,
        };
        let artifacts =
            LearningOperatorArtifactOwnerV1::new(service, profile.runtime_profile_digest())
                .unwrap();
        Self {
            training,
            evaluation,
            candidate,
            selection,
            artifacts,
            publication,
            run,
            control,
            directory,
            config,
            profile,
        }
    }

    pub(crate) fn late_candidate(&self) -> FinalUseTabularCandidateV1 {
        fit_candidate(
            &self.training,
            &self.profile,
            &self.control,
            51_000_000,
            52_000_000,
        )
    }

    pub(crate) fn load_inputs(
        &self,
    ) -> (
        File,
        File,
        VerifiedArtifactSelectionV1,
        EvaluatedTabularLoadBindingV3,
        ArtifactSelectionVerifierV1,
    ) {
        self.load_inputs_with_selection_expiry(EXPIRY)
    }

    pub(crate) fn load_inputs_with_selection_expiry(
        &self,
        expires: u64,
    ) -> (
        File,
        File,
        VerifiedArtifactSelectionV1,
        EvaluatedTabularLoadBindingV3,
        ArtifactSelectionVerifierV1,
    ) {
        let service = self.artifacts.service();
        let current = service.current_registry_view(NOW).unwrap();
        let receipt = current.receipt();
        let selected_manifest = service.registry().manifest(&id("candidate")).unwrap();
        let key = SigningKey::from_bytes(&[22; 32]);
        let trust = ArtifactSelectionTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
            minimum_authority_epoch: 7,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("storage-selector"),
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 7,
                maximum_authority_epoch: 7,
                valid_from: 1,
                expires_at: EXPIRY,
                revoked_at: None,
            }],
        };
        let verifier = ArtifactSelectionVerifierV1::new(trust, &self.config.trust).unwrap();
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("storage-selection"),
            artifact_id: id("candidate"),
            registry_id: id("registry"),
            withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
            registry_head_digest: receipt.head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: selected_manifest.kind,
            artifact_generation: selected_manifest.generation,
            predecessor_id: selected_manifest.predecessor_id.clone(),
            content_digest: selected_manifest.content_digest,
            objective_digest: selected_manifest.objective_digest,
            support_digest: selected_manifest.support_digest,
            compatibility_digest: selected_manifest.compatibility_digest,
            encoded_size_bytes: selected_manifest.encoded_size_bytes,
            selector_id: id("storage-selector"),
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 7,
            issued_at: NOW,
            expires_at: expires,
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        let selected = verifier.verify(&signed, &current, NOW).unwrap();
        let view = self.candidate.publication_view();
        let pin = TabularPayloadPinV2 {
            artifact_id: id("candidate"),
            producer_id: id("generator"),
            artifact_schema_version: 1,
            payload_schema_version: 1,
            payload_digest: view.payload_digest(),
            artifact_digest: view.artifact_digest(),
            objective_digest: view.objective_digest(),
            dataset_digest: view.dataset_digest(),
            sensor_core_digest: self.profile.sensor_core_digest(),
            training_profile_digest: self.profile.digest(),
            runtime_profile_digest: view.runtime_profile_digest(),
            trust_digest: view.trust_digest(),
            registry_head_digest: receipt.head_digest,
            authority_epoch: 7,
            generation: Generation::new(2).unwrap(),
        };
        let binding = EvaluatedTabularLoadBindingV3 {
            admission: self.publication.admission.clone(),
            training: self.training.receipt.clone(),
            evaluation: self.evaluation.receipt.clone(),
            selection: self.selection.clone(),
            model_pin: pin,
            expected_runtime_profile_digest: view.runtime_profile_digest(),
            deadline_unix_micros: self.run.deadline_unix_micros,
            control: self.control.clone(),
        };
        let snapshot = File::open(self.directory.path().join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        )))
        .unwrap();
        let payload = File::open(
            self.directory
                .path()
                .join("payloads")
                .join(format!("candidate-{}.bin", view.payload_digest())),
        )
        .unwrap();
        (snapshot, payload, selected, binding, verifier)
    }
}

fn manifest(
    candidate: &FinalUseTabularCandidateV1,
    training: &LearningFixture,
) -> LearningArtifactManifestV2 {
    let view = candidate.publication_view();
    LearningArtifactManifestV2 {
        artifact_id: view.artifact_id().clone(),
        kind: ArtifactKind::Model,
        generation: view.generation(),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![training.receipt.snapshot.dataset_digest],
        lineage_digests: vec![candidate.fit_receipt_digest()],
        predecessor_ids: vec![id("baseline")],
        rollback_predecessor: Some(id("baseline")),
        bytes_digest: view.payload_digest(),
        encoded_size_bytes: view.payload().len() as u64,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device"),
        objective_class_digest: view.objective_digest(),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: view.producer_id().clone(),
        created_at: view.published_at_unix_micros(),
        expires_at: EXPIRY,
    }
}

fn stage(registry: &mut ArtifactRegistry, request: &LearningArtifactPublishRequestV1) {
    let admission = &request.admission;
    let transaction = ArtifactPublicationTransactionV1::begin(
        request.operation_id.clone(),
        admission.clone(),
        &DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-owner"),
            registry_id: id("withdrawals"),
            scope_id: id("scope"),
        }),
        registry,
        request.expected_registry_predecessor_head,
        NOW,
    )
    .unwrap();
    let v2 = &admission.validated_manifest.manifest;
    registry
        .append(ArtifactEvent::Register {
            event_id: id(&format!(
                "artifact-publication:{}",
                transaction.intent().intent_digest
            )),
            manifest: ArtifactManifest {
                artifact_id: v2.artifact_id.clone(),
                kind: v2.kind,
                generation: v2.generation,
                predecessor_id: v2.predecessor_ids.first().cloned(),
                content_digest: v2.bytes_digest,
                objective_digest: v2.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: v2.producer_id.clone(),
                compatibility_digest: v2.compatibility_digest,
                encoded_size_bytes: v2.encoded_size_bytes,
            },
        })
        .unwrap();
}

fn make_publication(
    service: &LearningArtifactOwnerService,
    manifest: LearningArtifactManifestV2,
    payload: Vec<u8>,
    operation_id: StableId,
    key: &SigningKey,
) -> LearningArtifactPublishRequestV1 {
    let admission = admit_manifest_at_withdrawal_head_v3(
        service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(),
        manifest,
        NOW,
    )
    .unwrap();
    let predecessor = service.registry().snapshot().head_digest;
    let mut request = LearningArtifactPublishRequestV1 {
        operation_id,
        admission,
        payload,
        expected_registry_predecessor_head: predecessor,
        now: NOW,
        signed_current_head: SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: service.withdrawal_registry().scope_digest().unwrap(),
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("registry"),
                generation: Generation::new(service.registry().records().len() as u64 + 1).unwrap(),
                head_digest: digest("preview-placeholder"),
                predecessor_head_digest: predecessor,
                authority_epoch: 7,
                signer_id: id("artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: NOW,
                expires_at: EXPIRY,
            },
            signature: [0; 64],
        },
    };
    let mut staged = service.registry().clone();
    stage(&mut staged, &request);
    request.signed_current_head.witness.head_digest = staged.snapshot().head_digest;
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes())
        .to_bytes();
    request
}

fn fit_candidate(
    training: &LearningFixture,
    profile: &TrainingProfileV1,
    control: &WorkControlV1,
    used_at: u64,
    published_at: u64,
) -> FinalUseTabularCandidateV1 {
    let plan = TabularOperatorPlanV1 {
        artifact_id: id("candidate"),
        producer_id: id("generator"),
        generation: Generation::new(2).unwrap(),
        objective_digest: training.trust.objective_digest,
        dataset_digest: training.receipt.snapshot.dataset_digest,
        sensor_core_digest: profile.sensor_core_digest(),
        training_profile_digest: profile.digest(),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("action")],
        samples: training
            .receipt
            .snapshot
            .source_record_digests
            .iter()
            .enumerate()
            .map(|(index, evidence)| TabularOperatorSampleV1 {
                sample_id: id(&format!("row-{index}")),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(20),
                evidence_digest: *evidence,
            })
            .collect(),
    };
    let rows = LearningFixture::sign_with_expiry(
        training.owner.verifier(),
        1,
        &tabular_training_signing_payload_v2(&plan, &training.receipt, &training.owner).unwrap(),
        used_at,
        EXPIRY,
    );
    let request = TabularTrainingRequestV1::new(
        plan.artifact_id,
        plan.producer_id,
        plan.generation,
        profile.clone(),
        plan.sensor_ids,
        plan.action_ids,
        plan.samples,
    )
    .unwrap();
    let fence = FinalUseFenceV1::new(
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        7,
        1,
        published_at + 2_000_000,
    )
    .unwrap();
    let witness = FinalUseWitnessV1::new(
        used_at,
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        7,
        1,
        false,
    )
    .unwrap();
    let capability = issue_tabular_final_use_capability_v1(
        &training.owner,
        &training.receipt,
        &training.freeze,
        &rows,
        request,
        fence,
        control.clone(),
        &witness,
    )
    .unwrap();
    let publication_witness = FinalUseWitnessV1::new(
        published_at,
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        7,
        1,
        false,
    )
    .unwrap();
    fit_tabular_final_use_v1(capability, &witness, &publication_witness).unwrap()
}
