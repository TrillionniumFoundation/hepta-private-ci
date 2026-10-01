use super::*;

use codex_hepta_agent_components::learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_agent_components::learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_agent_components::learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_agent_components::learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_agent_components::learning_artifacts::ProvenanceModeV1;
use codex_hepta_agent_components::learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_agent_components::learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_agent_components::learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_agent_components::learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_agent_components::learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) struct OwnerView(Mutex<(LearningArtifactOwnerService, u64)>);

impl CurrentCognitiveRegistry for OwnerView {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let (service, now) = &*self.0.lock().unwrap();
        service
            .current_registry_view(*now)
            .map_err(|error| error.to_string())
    }
}

/// Publish through the actual owner protocol and recover its complete admission
/// in the current-view service. No test-only provenance injection is involved.
fn published_owner_view(
    fixture: &Fixture,
    source_dataset: Digest32,
) -> (Arc<OwnerView>, PathBuf, PathBuf, PinnedCandidateSpec) {
    published_owner_view_with_sources(fixture, vec![source_dataset])
}

pub(super) fn published_owner_view_with_sources(
    fixture: &Fixture,
    source_datasets: Vec<Digest32>,
) -> (Arc<OwnerView>, PathBuf, PathBuf, PinnedCandidateSpec) {
    published_owner_view_at(fixture, source_datasets, 20, 1_000)
}

pub(super) struct WallClockOwnerView(Arc<OwnerView>);
impl CurrentCognitiveRegistry for WallClockOwnerView {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let (service, _) = &*self.0.0.lock().unwrap();
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_millis()
            .try_into()
            .map_err(|error: std::num::TryFromIntError| error.to_string())?;
        service
            .current_registry_view(now)
            .map_err(|error| error.to_string())
    }
}

pub(super) fn published_wall_clock_owner_view(
    fixture: &Fixture,
    source_datasets: Vec<Digest32>,
) -> (
    Arc<WallClockOwnerView>,
    PathBuf,
    PathBuf,
    PinnedCandidateSpec,
) {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
        .try_into()
        .unwrap();
    let (view, snapshot, payload, selected) =
        published_owner_view_at(fixture, source_datasets, now, now + 120_000);
    (
        Arc::new(WallClockOwnerView(view)),
        snapshot,
        payload,
        selected,
    )
}

pub(super) fn published_wall_clock_owner_view_expiring_at(
    fixture: &Fixture,
    source_datasets: Vec<Digest32>,
    expires_at: u64,
) -> (
    Arc<WallClockOwnerView>,
    PathBuf,
    PathBuf,
    PinnedCandidateSpec,
) {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
        .try_into()
        .unwrap();
    let (view, snapshot, payload, selected) =
        published_owner_view_at(fixture, source_datasets, now, expires_at);
    (
        Arc::new(WallClockOwnerView(view)),
        snapshot,
        payload,
        selected,
    )
}

fn published_owner_view_at(
    fixture: &Fixture,
    source_datasets: Vec<Digest32>,
    now: u64,
    expires_at: u64,
) -> (Arc<OwnerView>, PathBuf, PathBuf, PinnedCandidateSpec) {
    let root = fixture.directory.path().join("artifact-owner");
    let key = SigningKey::from_bytes(&[64; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("dataset-registry"),
        scope_id: id("ranking-scope"),
    };
    let scope_digest = scope.digest();
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("artifact-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: now - 19,
        expires_at,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("ranking-artifacts"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("ranker-writer"),
        producer_id: id("fixture-trainer"),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("artifact-authority"),
        signing_key_digest: hash_key(&key),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: now - 10,
        expires_at,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let owner_host =
        LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now).unwrap();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let bytes = std::fs::read(fixture.directory.path().join("payload")).unwrap();
    let legacy = fixture.registry.manifest(&id("read-ranker")).unwrap();
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        LearningArtifactManifestV2 {
            artifact_id: legacy.artifact_id.clone(),
            kind: legacy.kind,
            generation: legacy.generation,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: source_datasets,
            lineage_digests: vec![hash("ranking-training-lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: legacy.content_digest,
            encoded_size_bytes: legacy.encoded_size_bytes,
            training_code_digest: hash("ranking-code"),
            runtime_tuple_digest: hash("ranking-runtime"),
            device_profile_digest: hash("ranking-device"),
            objective_class_digest: legacy.objective_digest,
            compatibility_digest: legacy.compatibility_digest,
            schema_profile_digest: hash("ranking-schema"),
            normalization_digest: hash("ranking-normalization"),
            producer_id: legacy.producer_id.clone(),
            created_at: now - 10,
            expires_at,
        },
        now,
    )
    .unwrap();
    let mut registry = ArtifactRegistry::new();
    let mut transaction = owner_host
        .begin_publication(
            id("ranker-publication"),
            admission,
            &withdrawals,
            &registry,
            Digest32::ZERO,
            now,
        )
        .unwrap();
    owner_host
        .stage_compatibility_registration(&transaction, &mut registry, now)
        .unwrap();
    let payload = owner_host
        .ensure_payload_durable(&mut transaction, &registry, &bytes, now)
        .unwrap();
    let binding = hash("owner-ranking-store");
    owner_host
        .ensure_registry_durable(&mut transaction, &registry, &withdrawals, binding, now)
        .unwrap();
    let receipt = transaction.snapshot().registry_receipt.unwrap();
    let snapshot = root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).unwrap(),
            head_digest: receipt.head_digest,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("artifact-authority"),
            signing_key_digest: hash_key(&key),
            issued_at: now,
            expires_at,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    owner_host
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, now)
        .unwrap();
    owner_host
        .acknowledge(&mut transaction, &withdrawals, now)
        .unwrap();
    let selected = PinnedCandidateSpec {
        registry_receipt: receipt,
        manifest: registry.manifest(&legacy.artifact_id).unwrap().clone(),
    };
    let payload = root.join(payload);
    drop(owner_host);
    let service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease: lease,
        required_current_head: Some(signed),
        withdrawal_registry: withdrawals,
        storage_binding: binding,
        now,
    })
    .unwrap();
    (
        Arc::new(OwnerView(Mutex::new((service, now)))),
        snapshot,
        payload,
        selected,
    )
}

fn hash_key(key: &SigningKey) -> Digest32 {
    Digest32::of_bytes(&key.verifying_key().to_bytes())
}

#[test]
fn owner_published_ranker_binds_full_dataset_provenance_and_closes_on_withdrawal() {
    let original = vec![item("one"), item("two")];
    let fixture = fixture(&original, &[0, 10]);
    let dataset = fixture.model_pin.dataset_digest;
    let (view, snapshot, payload, selected) = published_owner_view(&fixture, dataset);
    assert_ne!(selected.manifest.support_digest, dataset);
    let ranker = PinnedCognitiveRanker::load(
        owner(),
        1,
        File::open(&snapshot).unwrap(),
        File::open(&payload).unwrap(),
        selected,
        fixture.model_pin,
        view.clone(),
    )
    .unwrap();
    let mut ranked = original.clone();
    ranker.rank(&owner(), 1, "lemon", &mut ranked).unwrap();
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
    let mut guard = view.0.lock().unwrap();
    let (service, now) = &mut *guard;
    let mut withdrawals = service.withdrawal_registry().clone();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("ranking-dataset-withdrawal"),
            dataset_digest: dataset,
            source_tombstone_digest: hash("source-tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: hash("dataset-credential"),
            signing_key_digest: hash("dataset-key"),
            authority_epoch: 1,
            issued_at: 25,
        })
        .unwrap();
    service.install_withdrawal_frontier(withdrawals).unwrap();
    *now = 26;
    drop(guard);
    assert!(ranker.rank(&owner(), 1, "lemon", &mut ranked).is_err());
    assert!(ranker.rank(&owner(), 1, "lemon", &mut ranked).is_err());
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
}

#[test]
fn owner_published_ranker_rejects_payload_dataset_outside_full_provenance() {
    let original = vec![item("one"), item("two")];
    let fixture = fixture(&original, &[0, 10]);
    let (view, snapshot, payload, selected) =
        published_owner_view(&fixture, hash("unrelated-source-dataset"));
    let result = PinnedCognitiveRanker::load(
        owner(),
        1,
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        selected,
        fixture.model_pin,
        view,
    );
    assert!(matches!(result, Err(error) if error.contains("current artifact provenance")));
}
