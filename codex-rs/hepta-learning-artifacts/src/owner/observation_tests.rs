//! Real owner service calls; fixtures do not assert production acceptance.
use super::*;

use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ArtifactKind;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::TrustedArtifactSignerV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

static NEXT: AtomicU64 = AtomicU64::new(1);

struct Directory(PathBuf);
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

// Fields drop in declaration order: release the owner before removing its root.
struct Fixture {
    service: LearningArtifactOwnerService,
    request: LearningArtifactPublishRequestV1,
    config: LearningArtifactOwnerServiceConfigV1,
    directory: Directory,
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("id")
}

fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture() -> Fixture {
    let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
    let root = std::env::temp_dir().join(format!(
        "artifact-observation-{}-{sequence}",
        std::process::id()
    ));
    fs::create_dir(&root).fixture("new fixture root");
    let directory = Directory(root.clone());
    let key = SigningKey::from_bytes(&[73; 32]);
    let scope = DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("observation-scope"),
    };
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("owner-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 10_000,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope.digest(),
        minimum_registry_generation: Generation::new(1).fixture("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("lease"),
        producer_id: id("trainer"),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope.digest(),
        signer_id: id("owner-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let config = LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: hash("binding"),
        now: 20,
    };
    let service = LearningArtifactOwnerService::open(config.clone()).fixture("owner open");
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id("candidate"),
        kind: ArtifactKind::Model,
        generation: Generation::new(1).fixture("generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![hash("dataset")],
        lineage_digests: vec![hash("lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: hash("payload"),
        encoded_size_bytes: 7,
        training_code_digest: hash("code"),
        runtime_tuple_digest: hash("runtime"),
        device_profile_digest: hash("device"),
        objective_class_digest: hash("objective"),
        compatibility_digest: hash("compatibility"),
        schema_profile_digest: hash("schema"),
        normalization_digest: hash("normalization"),
        producer_id: id("trainer"),
        created_at: 10,
        expires_at: 1000,
    };
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest,
        /*now*/ 20,
    )
    .fixture("admission");
    let mut staged = ArtifactRegistry::new();
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission.clone(),
        &withdrawals,
        &staged,
        Digest32::ZERO,
        /*now*/ 20,
    )
    .fixture("preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage preview");
    let mut signed_current_head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope.digest(),
        binding: hash("binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"),
            generation: Generation::new(1).fixture("generation"),
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20,
            expires_at: 1000,
        },
        signature: [0; 64],
    };
    signed_current_head.signature = key.sign(&signed_current_head.signing_bytes()).to_bytes();
    let request = LearningArtifactPublishRequestV1 {
        operation_id: id("operation"),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head,
        expected_registry_predecessor_head: Digest32::ZERO,
        now: 20,
    };
    Fixture {
        service,
        request,
        config,
        directory,
    }
}

#[test]
fn artifact_diagnostics_observe_real_publication_and_historical_retry() {
    let mut fixture = fixture();
    let first = fixture
        .service
        .publish(fixture.request.clone())
        .fixture("publish");
    let measured = fixture.service.diagnostics();
    assert_eq!(measured.publication_calls, 1);
    assert_eq!(measured.publication_failures, 0);
    assert_eq!(measured.payload_and_checkpoint.calls, 1);
    assert_eq!(measured.registry_and_checkpoint.calls, 1);
    assert_eq!(measured.witness_and_checkpoint.calls, 1);
    assert_eq!(measured.acknowledgement_checkpoint.calls, 1);
    assert_eq!(measured.pinned_bytes, None);
    assert_eq!(measured.pending_physical_erasure_bytes, None);
    fixture.request.now = 21;
    let replay = fixture
        .service
        .publish(fixture.request.clone())
        .fixture("historical replay");
    assert_eq!(first, replay);
    let retried = fixture.service.diagnostics();
    assert_eq!(retried.publication_calls, 2);
    assert_eq!(
        retried.last_verified_request_digest,
        measured.last_verified_request_digest
    );
    assert_eq!(
        retried.payload_and_checkpoint,
        measured.payload_and_checkpoint
    );
    assert_eq!(
        retried.registry_and_checkpoint,
        measured.registry_and_checkpoint
    );
    assert_eq!(
        retried.witness_and_checkpoint,
        measured.witness_and_checkpoint
    );
    assert_eq!(
        retried.acknowledgement_checkpoint,
        measured.acknowledgement_checkpoint
    );
}

#[test]
fn artifact_request_diagnostic_identity_binds_semantics_not_retry_time() {
    let fixture = fixture();
    let verifier = &fixture.service.request_identity;
    let expected = verifier.verify(&fixture.request).fixture("identity");
    let mut next = fixture.request.clone();
    next.now = 21;
    assert_eq!(verifier.verify(&next).fixture("retry identity"), expected);
    next.operation_id = id("different-operation");
    assert_ne!(
        verifier.verify(&next).fixture("different operation"),
        expected
    );
    next = fixture.request.clone();
    next.signed_current_head.witness.expires_at = 900;
    let key = SigningKey::from_bytes(&[73; 32]);
    next.signed_current_head.signature = key
        .sign(&next.signed_current_head.signing_bytes())
        .to_bytes();
    assert_ne!(
        verifier.verify(&next).fixture("resigned envelope"),
        expected
    );
    next.payload[0] ^= 1;
    assert!(verifier.verify(&next).is_err());
}

#[test]
fn artifact_diagnostics_count_preflight_failure_without_publication() {
    let mut fixture = fixture();
    fixture.request.payload[0] ^= 1;
    let error = fixture
        .service
        .publish(fixture.request.clone())
        .fixture_error("tampered bytes");
    assert_eq!(error.code(), "artifact.identity_conflict");
    let measured = fixture.service.diagnostics();
    assert_eq!(measured.publication_calls, 1);
    assert_eq!(measured.publication_failures, 1);
    assert_eq!(measured.identity_conflicts, 1);
    assert_eq!(measured.payload_and_checkpoint.calls, 0);
    assert!(!measured.recovery_required);
}

#[test]
fn artifact_diagnostics_keep_drain_and_withdrawal_conflict_distinct() {
    let mut fixture = fixture();
    let foreign = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("foreign"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    let error = fixture
        .service
        .install_withdrawal_frontier(foreign)
        .fixture_error("scope conflict");
    assert_eq!(error.code(), "artifact.withdrawal_conflict");
    fixture
        .service
        .begin_drain_durable()
        .fixture("durable drain");
    let measured = fixture.service.diagnostics();
    assert_eq!(measured.withdrawal_conflicts, 1);
    assert_eq!(measured.withdrawal_persistence.failures, 1);
    assert_eq!(measured.drain_persistence.calls, 1);
    assert!(measured.draining);
    assert!(!measured.drain_durability_unknown);
    assert!(fixture.service.is_drained());
    let Fixture {
        service,
        config,
        request: _,
        directory,
    } = fixture;
    drop(service);
    let reopened = LearningArtifactOwnerService::open(config).fixture("reopen durable stop");
    assert!(reopened.diagnostics().drain_predates_process);
    assert!(reopened.is_drained());
    drop(reopened);
    drop(directory);
}

#[test]
fn artifact_owner_phase_measurement_smoke() {
    // Four tiny deterministic publications exercise the measurement producer.
    // This is a hosted-fixture baseline, not maximum-capacity or production SLO.
    let mut csv = String::from("sample,phase,payload_bytes,microseconds\n");
    for sample in 0..4 {
        let mut fixture = fixture();
        fixture
            .service
            .publish(fixture.request.clone())
            .fixture("measured publication");
        let diagnostics = fixture.service.diagnostics();
        for (phase, timing) in [
            ("open", diagnostics.open),
            ("identity", diagnostics.identity),
            ("payload_and_checkpoint", diagnostics.payload_and_checkpoint),
            (
                "registry_and_checkpoint",
                diagnostics.registry_and_checkpoint,
            ),
            ("witness_and_checkpoint", diagnostics.witness_and_checkpoint),
            (
                "acknowledgement_checkpoint",
                diagnostics.acknowledgement_checkpoint,
            ),
            ("publish", diagnostics.publish),
        ] {
            assert_eq!(timing.calls, 1);
            assert_eq!(timing.failures, 0);
            csv.push_str(&format!(
                "{sample},{phase},7,{}\n",
                timing.total_microseconds
            ));
        }
    }
    if let Some(root) = std::env::var_os("HEPTA_ARTIFACT_PHASE_OUTPUT") {
        let root = PathBuf::from(root);
        fs::create_dir_all(&root).fixture("measurement output");
        let path = root.join(format!("artifact-phases-{}.csv", std::process::id()));
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .fixture("create-only measurement file");
        file.write_all(csv.as_bytes()).fixture("write measurements");
        file.sync_all().fixture("sync measurements");
    }
}
