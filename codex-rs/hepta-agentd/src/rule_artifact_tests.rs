use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("{error:?}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture() -> (tempfile::TempDir, RuleArtifactConsumerV1, RuleUseBindingV1) {
    let directory = tempfile::tempdir().unwrap_or_else(|error| panic!("{error:?}"));
    let payload = b"immutable-rule-checkpoint-bundle";
    let generation = Generation::new(1).unwrap_or_else(|error| panic!("{error:?}"));
    let manifest = ArtifactManifest {
        artifact_id: id("rule-table"),
        kind: ArtifactKind::Policy,
        generation,
        predecessor_id: None,
        content_digest: Digest32::of_bytes(payload),
        objective_digest: digest("rule-objective"),
        support_digest: digest("source-evidence"),
        producer_id: id("rule-producer"),
        compatibility_digest: digest("finite-rule-driver"),
        encoded_size_bytes: payload.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: manifest.clone(),
        })
        .unwrap_or_else(|error| panic!("{error:?}"));
    let payload_path = directory.path().join("payload");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload_path).unwrap_or_else(|error| panic!("{error:?}")),
        &registry,
        &manifest.artifact_id,
        payload,
    )
    .unwrap_or_else(|error| panic!("{error:?}"));
    let snapshot_path = directory.path().join("snapshot");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot_path).unwrap_or_else(|error| panic!("{error:?}")),
        &registry,
        digest("fixture-storage-binding"),
    )
    .unwrap_or_else(|error| panic!("{error:?}"));
    let current = crate::cognitive_ranker::verified_fixture_current_view(
        File::open(&snapshot_path).unwrap_or_else(|error| panic!("{error:?}")),
        receipt,
        Digest32::ZERO,
    )
    .unwrap_or_else(|error| panic!("{error:?}"));
    // Match the existing native signed-CURRENT test helper's trust exactly.
    let owner_key = SigningKey::from_bytes(&[23; 32]);
    let registry_id = id("agentd-current-fixture-registry");
    let scope = digest("agentd-current-fixture-scope");
    let owner_signer = TrustedArtifactSignerV1 {
        signer_id: id("agentd-current-fixture-signer"),
        verifying_key: owner_key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    let owner_trust = ArtifactOwnerTrustV1 {
        registry_id: registry_id.clone(),
        withdrawal_scope_digest: scope,
        minimum_registry_generation: generation,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![owner_signer.clone()],
        head_signers: vec![owner_signer],
    };
    let selector_key = SigningKey::from_bytes(&[24; 32]);
    let selector_id = id("independent-rule-selector");
    let verifier = ArtifactSelectionVerifierV1::new(
        ArtifactSelectionTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest: scope,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: selector_id.clone(),
                verifying_key: selector_key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 10,
                valid_from: 1,
                expires_at: 1_000,
                revoked_at: None,
            }],
        },
        &owner_trust,
    )
    .unwrap_or_else(|error| panic!("{error:?}"));
    let mut selection = SignedArtifactSelectionV1 {
        selection_id: id("rule-selection"),
        artifact_id: manifest.artifact_id.clone(),
        registry_id,
        withdrawal_scope_digest: scope,
        registry_head_digest: receipt.head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: manifest.kind,
        artifact_generation: generation,
        predecessor_id: None,
        content_digest: manifest.content_digest,
        objective_digest: manifest.objective_digest,
        support_digest: manifest.support_digest,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        selector_id,
        selector_credential_digest: digest("separate-selector-credential"),
        signing_key_digest: Digest32::of_bytes(&selector_key.verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: 10,
        expires_at: 100,
        signature: [0; 64],
    };
    selection.signature = selector_key.sign(&selection.signing_bytes()).to_bytes();
    let selected = RevalidatingSelectedCandidateV1::load(
        verifier,
        selection,
        current,
        20,
        File::open(snapshot_path).unwrap_or_else(|error| panic!("{error:?}")),
        File::open(payload_path).unwrap_or_else(|error| panic!("{error:?}")),
    )
    .unwrap_or_else(|error| panic!("{error:?}"));
    let binding = RuleUseBindingV1 {
        checkpoint_digest: manifest.content_digest,
        rule_revision: 3,
        authority_epoch: 1,
        generation,
        scope_digest: scope,
        inference: NeuronFeatureRequestV1 {
            request_id: id("rule-use"),
            generation,
            model_id: manifest.artifact_id,
            encoder_digest: digest("role-normalization"),
            head_digest: digest("six-state-table"),
            weights_digest: manifest.content_digest,
            input_digest: digest("current-source-verification-anchor"),
            feature_vector_q24: vec![0, 1 << 24, 2 << 24],
            expected_output_width: 3,
        },
        expected_prediction_q24: vec![2 << 24, 0, 1 << 24],
        deadline_unix_ms: 50_000,
    };
    (
        directory,
        RuleArtifactConsumerV1::new(id("host-principal"), id("native-rule-worker"), selected),
        binding,
    )
}

#[test]
fn rule_artifact_proposal_cannot_reuse_signature_after_operation_or_worker_changes() {
    let (_directory, mut consumer, binding) = fixture();
    let original = consumer
        .final_use_binding(&binding)
        .unwrap_or_else(|error| panic!("{error:?}"));
    let mut variants = Vec::new();
    let mut changed = binding.clone();
    changed.rule_revision += 1;
    variants.push(changed);
    let mut changed = binding.clone();
    changed.authority_epoch += 1;
    variants.push(changed);
    let mut changed = binding.clone();
    changed.scope_digest = digest("other-scope");
    variants.push(changed);
    let mut changed = binding.clone();
    changed.inference.input_digest = digest("new-checkpoint-anchor");
    variants.push(changed);
    let mut changed = binding.clone();
    changed.expected_prediction_q24.reverse();
    variants.push(changed);
    let mut changed = binding.clone();
    changed.deadline_unix_ms += 1;
    variants.push(changed);
    for changed in variants {
        assert_ne!(
            consumer
                .final_use_binding(&changed)
                .unwrap_or_else(|error| panic!("{error:?}")),
            original
        );
    }
    consumer.worker_id = id("different-native-worker");
    assert_ne!(
        consumer
            .final_use_binding(&binding)
            .unwrap_or_else(|error| panic!("{error:?}")),
        original
    );
}

#[test]
fn rule_artifact_rejects_foreign_generation_payload_and_closed_consumer() {
    let (_directory, mut consumer, binding) = fixture();
    let mut generation = binding.clone();
    generation.generation = Generation::new(2).unwrap_or_else(|error| panic!("{error:?}"));
    let mut payload = binding.clone();
    payload.checkpoint_digest = digest("different-bundle");
    let mut inference = binding.clone();
    inference.inference.model_id = id("other-artifact");
    for changed in [generation, payload, inference] {
        assert!(matches!(
            consumer.final_use_binding(&changed),
            Err(RuleArtifactUseError {
                kind: RuleArtifactUseFailureV1::Binding,
                ..
            })
        ));
    }
    consumer.closed = true;
    assert!(matches!(
        consumer.final_use_binding(&binding),
        Err(RuleArtifactUseError {
            kind: RuleArtifactUseFailureV1::Unavailable,
            ..
        })
    ));
}

#[test]
fn rule_artifact_rechecks_exclusive_milliseconds_and_inclusive_native_seconds() {
    assert!(require_entry_live(1_999, 1_999, 3_000, 2_000, 2, 2).is_ok());
    assert!(require_entry_live(1_999, 2_000, 3_000, 2_000, 2, 2).is_err());
    assert!(require_entry_live(2_000, 1_999, 2_000, 3_000, 2, 2).is_err());
    assert!(require_entry_live(4_999, 5_500, 6_000, 6_000, 4, 4).is_ok());
    assert!(require_entry_live(5_000, 5_500, 6_000, 6_000, 4, 5).is_err());
    assert!(require_entry_live(5_000, 5_500, 6_000, 6_000, 5, 4).is_err());
}
