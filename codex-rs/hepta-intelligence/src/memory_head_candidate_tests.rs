use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramPopulationV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::CellHeadFeatureIdentityV1;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;

#[path = "memory_head_fixture_tests.rs"]
mod fixture;
use fixture::*;

fn contract(digest: Digest32) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest).expect("nonempty digest")
}

fn manifest(fixture: &PublishedFixture) -> MemoryCellManifestV1 {
    MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: ContractIdV1::new("semantic-news-head").expect("cell id"),
        role: MemoryCellRoleV1::Semantic,
        parent_cell_id: None,
        shared_base_digest: contract(hash("shared base")),
        encoder_digest: contract(identity().feature.encoder_digest),
        adapter_artifact_digest: contract(hash("unchanged external adapter")),
        head_artifact_digest: contract(hash("previous head artifact")),
        state_schema_digest: contract(hash("state schema")),
        source_frontier_digest: contract(identity().source_frontier_digest),
        forget_frontier_digest: contract(fixture.pins.current_withdrawal_head),
        lineage_digest: contract(hash("cell lineage")),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        populations: BTreeSet::from([EngramPopulationV1::SemanticConcept]),
        graph_generation: ContractGenerationV1::new(1).expect("graph generation"),
        model_generation: ContractGenerationV1::new(1).expect("model generation"),
        max_active_cells: 4,
        max_state_bytes: 1024,
    }
}

fn context(fixture: &PublishedFixture) -> MemoryHeadCandidateContextV1 {
    let manifest = manifest(fixture);
    MemoryHeadCandidateContextV1 {
        candidate: MemoryCellNextSnapshotCandidateV1 {
            schema_version: 1,
            cell_id: manifest.cell_id,
            shared_base_digest: manifest.shared_base_digest,
            encoder_digest: manifest.encoder_digest,
            source_frontier_digest: manifest.source_frontier_digest,
            forget_frontier_digest: manifest.forget_frontier_digest,
            predecessor_graph_generation: manifest.graph_generation,
            next_graph_generation: manifest.graph_generation,
            predecessor_model_generation: manifest.model_generation,
            next_model_generation: manifest.model_generation.next().expect("next generation"),
            replay_snapshot_digest: contract(identity().training_dataset_digest),
            replay_receipt_digest: contract(hash("test-only replay receipt")),
            candidate_adapter_artifact_digest: manifest.adapter_artifact_digest,
            candidate_head_artifact_digest: contract(Digest32::of_bytes(BUNDLE)),
            independent_evaluation_digest: contract(hash("test-only evaluator result")),
            topology_proposal_digest: None,
            rollback_plan_digest: contract(hash("test-only parent fallback plan")),
            current_snapshot_immutable: true,
            production_activation_allowed: false,
        },
        artifact_pins: fixture.pins.clone(),
        head_identity: identity(),
    }
}

fn request(
    context: MemoryHeadCandidateContextV1,
    same_controller: bool,
) -> (MemoryHeadCandidateRequestV1, LearningEvidenceVerifierV1) {
    let keys = [
        SigningKey::from_bytes(&[81; 32]),
        SigningKey::from_bytes(&[82; 32]),
    ];
    let names = [
        "test-only-replay-producer",
        "test-only-independent-evaluator",
    ];
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Evaluator,
    ];
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: identity().feature.scope_digest,
        objective_digest: head_manifest().objective_class_digest,
        authority_epoch: 1,
        signers: (0..2)
            .map(|i| TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(names[i]),
                    credential_chain_digest: hash(names[i]),
                    signing_key_digest: Digest32::of_bytes(&keys[i].verifying_key().to_bytes()),
                    scope_digest: identity().feature.scope_digest,
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 1000,
                },
                controller_id: id(if same_controller {
                    "same-controller"
                } else {
                    names[i]
                }),
                verifying_key: keys[i].verifying_key().to_bytes(),
                roles: vec![roles[i]],
                revoked_at: None,
            })
            .collect(),
    })
    .expect("test evidence trust");
    let payload = memory_head_candidate_signing_payload_v1(&context).expect("canonical candidate");
    let sign = |i: usize| {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(names[i]),
            principal_id: id(names[i]),
            role: roles[i],
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 1000,
            payload_digest: Digest32::of_bytes(&payload),
            signature: [0; 64],
        };
        evidence.signature = keys[i].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    };
    (
        MemoryHeadCandidateRequestV1 {
            context,
            replay_attestation: sign(0),
            evaluator_attestation: sign(1),
        },
        verifier,
    )
}

#[test]
fn real_persisted_weights_bind_to_a_successor_without_modifying_current_memory() {
    let fixture = published_fixture(head_manifest());
    let manifest = manifest(&fixture);
    let before = manifest.clone();
    let (request, verifier) = request(context(&fixture), false);
    drop(fixture.service);
    let service = LearningArtifactOwnerService::open(fixture.config).expect("reopen owner");
    let receipt = prepare_memory_head_candidate_v1(&service, &manifest, &request, &verifier, 21)
        .expect("persisted head composition");
    assert_eq!(receipt.candidate(), &request.context.candidate);
    assert_eq!(receipt.head().weights_npz(), WEIGHTS);
    assert_eq!(receipt.head().identity().feature.generation, 1);
    assert_eq!(receipt.candidate().next_model_generation.get(), 2);
    assert_eq!(manifest, before);
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    assert!(!receipt.evidence_digest().is_zero());
}

#[test]
fn valid_bytes_cannot_be_relabelled_as_another_encoder_source_or_head() {
    let fixture = published_fixture(head_manifest());
    let current = manifest(&fixture);
    for field in 0..4 {
        let mut changed = context(&fixture);
        let mut manifest = current.clone();
        let other = contract(hash("unrelated provenance"));
        match field {
            0 => {
                manifest.encoder_digest = other;
                changed.candidate.encoder_digest = other;
            }
            1 => {
                manifest.source_frontier_digest = other;
                changed.candidate.source_frontier_digest = other;
            }
            2 => changed.candidate.replay_snapshot_digest = other,
            _ => changed.candidate.candidate_head_artifact_digest = other,
        }
        let (request, verifier) = request(changed, false);
        assert!(matches!(
            prepare_memory_head_candidate_v1(&fixture.service, &manifest, &request, &verifier, 21),
            Err(MemoryHeadCandidateErrorV1::Binding(_))
        ));
    }
}

#[test]
fn altered_evaluation_and_colliding_controllers_cannot_sign_themselves_in() {
    let fixture = published_fixture(head_manifest());
    let manifest = manifest(&fixture);
    let (mut changed, verifier) = request(context(&fixture), false);
    changed.context.candidate.independent_evaluation_digest = contract(hash("replaced evaluation"));
    assert!(matches!(
        prepare_memory_head_candidate_v1(&fixture.service, &manifest, &changed, &verifier, 21),
        Err(MemoryHeadCandidateErrorV1::Evidence(_))
    ));
    let (colliding, verifier) = request(context(&fixture), true);
    assert!(matches!(
        prepare_memory_head_candidate_v1(&fixture.service, &manifest, &colliding, &verifier, 21),
        Err(MemoryHeadCandidateErrorV1::Evidence(
            SignedEvidenceError::ControllerCollision
        ))
    ));
}

#[test]
fn proposal_refuses_wrong_role_new_adapter_and_stale_withdrawal_pins() {
    let fixture = published_fixture(head_manifest());
    for field in 0..3 {
        let mut manifest = manifest(&fixture);
        let mut changed = context(&fixture);
        match field {
            0 => manifest.role = MemoryCellRoleV1::Episodic,
            1 => {
                changed.candidate.candidate_adapter_artifact_digest =
                    contract(hash("other adapter"))
            }
            _ => changed.artifact_pins.current_withdrawal_head = hash("stale withdrawals"),
        }
        let (request, verifier) = request(changed, false);
        assert!(
            prepare_memory_head_candidate_v1(&fixture.service, &manifest, &request, &verifier, 21)
                .is_err()
        );
    }
}
