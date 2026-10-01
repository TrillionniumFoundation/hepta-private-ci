//! Genuine final-use fit, two durable ledgers and signed file-owner fixtures.
use super::ledger::LearningFixture;
use super::paired;
use super::qualification::paired_selection;
use crate::learning_operator_artifact_owner::*;
use crate::learning_operator_context::LearningOperatorRunContextV2;
use crate::learning_operator_shadow_loader::EvaluatedTabularLoadBindingV4;
use codex_hepta_agent_components::bellman_operator::*;
use codex_hepta_agent_components::intelligence_eval::VerifiedSelfEvolutionSelectionV2;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn now() -> u64 {
    paired::now_millis()
}
fn expiry() -> u64 {
    now() + 90_000
}

pub(crate) struct Fixture {
    pub training: LearningFixture,
    pub evaluation: LearningFixture,
    pub candidate: FinalUseTabularCandidateV1,
    pub selection: VerifiedSelfEvolutionSelectionV2,
    pub artifacts: LearningOperatorArtifactOwnerV2,
    pub publication: LearningArtifactPublishRequestV1,
    pub run: LearningOperatorRunContextV2,
    pub control: WorkControlV1,
    pub directory: tempfile::TempDir,
    pub config: LearningArtifactOwnerServiceConfigV1,
    profile: TrainingProfileV1,
    signing: paired::SigningFixture,
}

impl Fixture {
    pub(crate) fn new() -> Self {
        Self::new_with_head_actor_window(expiry(), /*revoked_at*/ None)
    }

    pub(crate) fn new_with_head_actor_window(expires_at: u64, revoked_at: Option<u64>) -> Self {
        let mut signing = paired::SigningFixture::new(digest("read-ranking-task"));
        let training = LearningFixture::new("training", &signing);
        let profile = TrainingProfileV1::new(
            training.owner.verifier().objective_digest(),
            digest("sensors"),
            training.receipt.snapshot.eligible_frontier,
            1,
            FixedQ32::from_raw(100),
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap();
        let control = WorkControlV1::new();
        let candidate = fit_candidate(&training, &profile, &control, &signing);
        let evaluation = LearningFixture::new("evaluation", &signing);
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
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: signing.now - 1_000,
            expires_at: expiry(),
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
            minimum_authority_epoch: 1,
            writer_signers: vec![signer],
            head_signers: vec![head_signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("writer"),
            producer_id: signing.principals[0].principal_id.clone(),
            registry_id: id("registry"),
            withdrawal_scope_digest: scope,
            signer_id: id("artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: signing.now - 1_000,
            expires_at: expiry(),
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
            now: now(),
        };
        let mut service = LearningArtifactOwnerService::open(config.clone()).unwrap();
        let mut baseline = manifest(&candidate, &training, &evaluation);
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
        let target = manifest(&candidate, &training, &evaluation);
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
        signing.now = now();
        let selection = paired_selection(&signing, &evaluation, &predecessor, selected_manifest);
        let run = LearningOperatorRunContextV2 {
            run_id: id("operator-run"),
            owner_id: training.receipt.producer.principal_id.clone(),
            producer_id: signing.principals[0].principal_id.clone(),
            objective_digest: view.objective_digest(),
            training_source_digest: training.receipt.snapshot.dataset_digest,
            evaluation_source_digest: evaluation.receipt.snapshot.dataset_digest,
            predecessor_artifact_digest: predecessor.content_digest,
            predecessor_generation: predecessor.generation,
            expected_authority_epoch: 1,
            expected_stop_epoch: 1,
            now_unix_micros: now() * 1_000,
            deadline_unix_micros: (now() + 60_000) * 1_000,
        };
        let artifacts =
            LearningOperatorArtifactOwnerV2::new(service, profile.runtime_profile_digest())
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
            signing,
        }
    }

    pub(crate) fn late_candidate(&self) -> FinalUseTabularCandidateV1 {
        fit_candidate(&self.training, &self.profile, &self.control, &self.signing)
    }

    pub(crate) fn load_inputs(
        &self,
        storage: LearningOperatorStorageReceiptV2,
    ) -> (
        File,
        File,
        VerifiedArtifactSelectionV1,
        EvaluatedTabularLoadBindingV4,
        ArtifactSelectionVerifierV1,
    ) {
        self.load_inputs_with_selection_expiry(expiry(), storage)
    }

    pub(crate) fn load_inputs_with_selection_expiry(
        &self,
        expires: u64,
        storage: LearningOperatorStorageReceiptV2,
    ) -> (
        File,
        File,
        VerifiedArtifactSelectionV1,
        EvaluatedTabularLoadBindingV4,
        ArtifactSelectionVerifierV1,
    ) {
        let service = self.artifacts.service();
        let current = service.current_registry_view(now()).unwrap();
        let receipt = current.receipt();
        let selected_manifest = service.registry().manifest(&id("candidate")).unwrap();
        let key = SigningKey::from_bytes(&[22; 32]);
        let trust = ArtifactSelectionTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: self.config.trust.withdrawal_scope_digest,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("storage-selector"),
                verifying_key: key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: self.signing.now - 1_000,
                expires_at: expiry(),
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
            authority_epoch: 1,
            issued_at: now(),
            expires_at: expires,
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        let selected = verifier.verify(&signed, &current, now()).unwrap();
        let view = self.candidate.publication_view();
        let pin = TabularPayloadPinV2 {
            artifact_id: id("candidate"),
            producer_id: self.signing.principals[0].principal_id.clone(),
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
            authority_epoch: 1,
            generation: Generation::new(2).unwrap(),
        };
        let binding = EvaluatedTabularLoadBindingV4 {
            admission: self.publication.admission.clone(),
            storage,
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
    evaluation: &LearningFixture,
) -> LearningArtifactManifestV2 {
    let view = candidate.publication_view();
    LearningArtifactManifestV2 {
        artifact_id: view.artifact_id().clone(),
        kind: ArtifactKind::Model,
        generation: view.generation(),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![
            training.receipt.snapshot.dataset_digest,
            evaluation.receipt.snapshot.dataset_digest,
        ],
        lineage_digests: vec![candidate.fit_receipt_digest()],
        predecessor_ids: vec![id("baseline")],
        rollback_predecessor: Some(id("baseline")),
        bytes_digest: view.payload_digest(),
        encoded_size_bytes: view.payload().len() as u64,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device"),
        objective_class_digest: view.objective_digest(),
        compatibility_digest: view.runtime_profile_digest(),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: view.producer_id().clone(),
        created_at: view.published_at_unix_micros() / 1_000,
        expires_at: expiry(),
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
        now(),
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
        now(),
    )
    .unwrap();
    let predecessor = service.registry().snapshot().head_digest;
    let mut request = LearningArtifactPublishRequestV1 {
        operation_id,
        admission,
        payload,
        expected_registry_predecessor_head: predecessor,
        now: now(),
        signed_current_head: SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: service.withdrawal_registry().scope_digest().unwrap(),
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("registry"),
                generation: Generation::new(service.registry().records().len() as u64 + 1).unwrap(),
                head_digest: digest("preview-placeholder"),
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: now(),
                expires_at: expiry(),
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
    signing: &paired::SigningFixture,
) -> FinalUseTabularCandidateV1 {
    let plan = TabularOperatorPlanV1 {
        artifact_id: id("candidate"),
        producer_id: signing.principals[0].principal_id.clone(),
        generation: Generation::new(2).unwrap(),
        objective_digest: training.owner.verifier().objective_digest(),
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
    let rows = signing.sign(
        1,
        &tabular_training_signing_payload_v2(&plan, &training.receipt, &training.owner).unwrap(),
        now(),
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
    // Sign before sampling the true use boundary: a millisecond tick during
    // construction must never make the evidence newer than its use witness.
    let used_at = wall_clock_micros().unwrap();
    let fence = FinalUseFenceV1::new(
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        1,
        1,
        used_at + 30_000_000,
    )
    .unwrap();
    let witness = FinalUseWitnessV1::new(
        used_at,
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        1,
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
        wall_clock_micros().unwrap(),
        training.receipt.snapshot.ledger_head_digest,
        training.receipt.snapshot.eligible_frontier,
        Generation::new(2).unwrap(),
        1,
        1,
        false,
    )
    .unwrap();
    fit_tabular_final_use_v1(capability, &witness, &publication_witness).unwrap()
}
