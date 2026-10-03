use super::*;

use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000120").unwrap()
}
fn item(name: &str) -> CognitiveContextItem {
    CognitiveContextItem {
        memory_id: name.into(),
        revision: 1,
        content: name.into(),
        content_sha256: digest(name).to_string(),
    }
}

struct Current {
    snapshot: PathBuf,
    receipt: RegistrySnapshotReceipt,
    head: SignedCurrentArtifactHeadV1,
    verifier: ArtifactOwnerVerifierV1,
    admissions: Vec<WithdrawalBoundArtifactAdmissionV3>,
    withdrawals: Mutex<DatasetWithdrawalRegistry>,
    now: AtomicU64,
    full_closure: AtomicBool,
}

impl CurrentCognitiveRegistry for Current {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let now = self.now.load(Ordering::Relaxed);
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.head.witness.registry_id.clone(),
            minimum_generation: self.head.witness.generation,
            expected_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            now,
        };
        let file = File::open(&self.snapshot).map_err(|error| error.to_string())?;
        let result = if self.full_closure.load(Ordering::Relaxed) {
            self.verifier
                .verify_current_registry_view_with_admission_closure(
                    file,
                    self.receipt,
                    &self.head,
                    &requirement,
                    self.admissions.clone(),
                    &self.withdrawals.lock().unwrap(),
                )
        } else {
            self.verifier
                .verify_current_registry_view(file, self.receipt, &self.head, &requirement)
        };
        result.map_err(|error| error.to_string())
    }
}

struct Fixture {
    _directory: tempfile::TempDir,
    ranker: PinnedCognitiveRanker,
    current: Arc<Current>,
}

fn fixture() -> Fixture {
    let directory = tempfile::tempdir().unwrap();
    let sensor = cognitive_sensor_id("query").unwrap();
    let items = [item("a"), item("b")];
    let actions: Vec<_> = items
        .iter()
        .map(|item| cognitive_action_id(item).unwrap())
        .collect();
    let model = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id("v2-ranker"),
        producer_id: id("trainer"),
        generation: Generation::new(1).unwrap(),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("sensor"),
        training_profile_digest: digest("training"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![sensor.clone()],
        action_ids: actions.clone(),
        samples: actions
            .iter()
            .enumerate()
            .flat_map(|(index, action)| {
                let sensor = sensor.clone();
                [0, 1].map(move |replicate| TabularOperatorSampleV1 {
                    sample_id: id(&format!("sample-{index}-{replicate}")),
                    sensor_id: sensor.clone(),
                    action_id: action.clone(),
                    target: FixedQ32::from_raw(index as i64 + 1),
                    evidence_digest: digest(&format!("evidence-{index}-{replicate}")),
                })
            })
            .collect(),
    })
    .unwrap();
    let bytes = encode_tabular_payload_v1(&model).unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: model.artifact_digest,
        objective_digest: model.objective_digest,
        dataset_digest: model.dataset_digest,
        sensor_core_digest: model.sensor_core_digest,
        training_profile_digest: model.training_profile_digest,
        generation: model.generation,
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        LearningArtifactManifestV2 {
            artifact_id: model.artifact_id.clone(),
            kind: ArtifactKind::Policy,
            generation: model.generation,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![pin.dataset_digest, digest("second-dataset")],
            lineage_digests: vec![pin.sensor_core_digest],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: pin.payload_digest,
            encoded_size_bytes: bytes.len() as u64,
            training_code_digest: digest("code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: pin.objective_digest,
            compatibility_digest: pin.training_profile_digest,
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: model.producer_id.clone(),
            created_at: 10,
            expires_at: 100,
        },
        20,
    )
    .unwrap();
    let manifest = ArtifactManifest {
        artifact_id: model.artifact_id,
        kind: ArtifactKind::Policy,
        generation: pin.generation,
        predecessor_id: None,
        content_digest: pin.payload_digest,
        objective_digest: pin.objective_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: model.producer_id,
        compatibility_digest: pin.training_profile_digest,
        encoded_size_bytes: bytes.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        })
        .unwrap();
    let payload = directory.path().join("payload");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload).unwrap(),
        &registry,
        &manifest.artifact_id,
        &bytes,
    )
    .unwrap();
    let snapshot = directory.path().join("snapshot");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot).unwrap(),
        &registry,
        digest("binding"),
    )
    .unwrap();
    let key = SigningKey::from_bytes(&[24; 32]);
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("owner"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 2,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    let verifier = ArtifactOwnerVerifierV1::new(ArtifactOwnerTrustV1 {
        registry_id: id("registry"),
        withdrawal_scope_digest: withdrawals.scope_digest().unwrap(),
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    })
    .unwrap();
    let mut head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: withdrawals.scope_digest().unwrap(),
        binding: receipt.binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: id("registry"),
            generation: Generation::new(1).unwrap(),
            head_digest: receipt.head_digest,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("owner"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    let current = Arc::new(Current {
        snapshot: snapshot.clone(),
        receipt,
        head,
        verifier,
        admissions: vec![admission],
        withdrawals: Mutex::new(withdrawals),
        now: AtomicU64::new(20),
        full_closure: AtomicBool::new(true),
    });
    let ranker = PinnedCognitiveRanker::load(
        owner(),
        1,
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest,
        },
        pin,
        current.clone(),
    )
    .unwrap();
    Fixture {
        _directory: directory,
        ranker,
        current,
    }
}

#[test]
fn v2_owner_published_policy_reaches_the_ranker_using_real_dataset_provenance() {
    let fixture = fixture();
    let mut items = vec![item("a"), item("b")];
    fixture
        .ranker
        .rank(&owner(), 1, "query", &mut items)
        .unwrap();
    assert_eq!(items, vec![item("b"), item("a")]);
}

#[test]
fn v2_ranker_rechecks_expiry_and_cannot_strip_the_full_admission() {
    let fixture = fixture();
    fixture.current.full_closure.store(false, Ordering::Relaxed);
    assert!(fixture.ranker.revalidate().is_err());
    fixture.current.full_closure.store(true, Ordering::Relaxed);
    assert!(fixture.ranker.revalidate().is_err());
    let fixture = self::fixture();
    fixture.current.now.store(101, Ordering::Relaxed);
    assert!(fixture.ranker.revalidate().is_err());
}

#[test]
fn withdrawing_a_second_dataset_closes_the_v2_ranking_consumer() {
    let fixture = fixture();
    fixture
        .current
        .withdrawals
        .lock()
        .unwrap()
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawal"),
            dataset_digest: digest("second-dataset"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .unwrap();
    fixture.current.now.store(21, Ordering::Relaxed);
    assert!(fixture.ranker.revalidate().is_err());
}
