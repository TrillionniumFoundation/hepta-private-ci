use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::build_qualified_candidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn candidate() -> QualifiedCompactionCandidateV2 {
    let first = Generation::new(/*value*/ 1).expect("valid generation");
    let revision = Revision::new(/*value*/ 1).expect("valid revision");
    let snapshot = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact"),
        purpose_id: id("purpose:consolidation"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 1,
        tombstone_frontier: 0,
        source_ledger_frontier: 1,
        knowledge_graph_generation: first,
        compact_checkpoint_generation: first,
        prompt_registry_revision: revision,
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 7,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("valid snapshot");
    build_qualified_candidate(
        snapshot,
        first,
        /*predecessor_checkpoint_digest*/ None,
        &CompactionPolicyV2 {
            policy_id: id("policy:compact"),
            algorithm_digest: digest("algorithm"),
            compatibility_digest: digest("compatibility"),
            maximum_retained_records: 1,
            protected_record_ids: Vec::new(),
        },
        vec![CompactionInputRecordV2 {
            record: MemoryRecord {
                record_id: id("memory:1"),
                revision,
                kind: MemoryKind::Fact,
                content_digest: digest("content"),
                predecessor_digest: None,
                citations: Vec::new(),
                state: RecordState::Live,
            },
            retention_priority: 1,
            retention_reason_digest: digest("reason"),
        }],
    )
    .expect("valid candidate")
}

fn trust(binding: &CompactionSourceAuthorityBindingV1) -> LearningEvidenceTrustV1 {
    let signer = |name: &str, controller: &str, seed, role| {
        let verifying_key = SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: digest(name),
                signing_key_digest: Digest32::of_bytes(&verifying_key),
                scope_digest: binding.scope_digest,
                authority_epoch: binding.authority_epoch,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id(controller),
            verifying_key,
            roles: vec![role],
            revoked_at: None,
        }
    };
    LearningEvidenceTrustV1 {
        scope_digest: binding.scope_digest,
        objective_digest: binding.objective_digest,
        authority_epoch: binding.authority_epoch,
        signers: vec![
            signer(
                "generator",
                "generator-controller",
                /*seed*/ 1,
                LearningEvidenceRoleV1::Generator,
            ),
            signer(
                "evaluator",
                "evaluator-controller",
                /*seed*/ 2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    }
}

fn signed(
    verifier: &LearningEvidenceVerifierV1,
    principal: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{principal}")),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    signed
}

fn evidence(verifier: &LearningEvidenceVerifierV1, payload: &[u8]) -> SignedCompactionEvidenceV1 {
    SignedCompactionEvidenceV1 {
        generator: signed(
            verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            /*seed*/ 1,
            payload,
        ),
        evaluator: signed(
            verifier,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            /*seed*/ 2,
            payload,
        ),
    }
}

struct Fixture {
    candidate: QualifiedCompactionCandidateV2,
    binding: CompactionSourceAuthorityBindingV1,
    qualification: CompactionQualificationV2,
    verifier: LearningEvidenceVerifierV1,
    evidence: SignedCompactionEvidenceV1,
}

fn fixture() -> Fixture {
    let candidate = candidate();
    let binding = CompactionSourceAuthorityBindingV1 {
        source_cut_digest: digest("owner-source-cut"),
        scope_digest: digest("host-authority-scope"),
        objective_digest: digest("host-objective"),
        authority_epoch: 7,
    };
    let qualification = CompactionQualificationV2 {
        evaluator_id: id("evaluator"),
        candidate_digest: candidate.candidate_digest,
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
    };
    let verifier = LearningEvidenceVerifierV1::new(trust(&binding)).expect("valid host trust");
    let payload = compaction_qualification_payload_v1(&candidate, &binding, &qualification)
        .expect("valid payload");
    let evidence = evidence(&verifier, &payload);
    Fixture {
        candidate,
        binding,
        qualification,
        verifier,
        evidence,
    }
}

fn admit(
    fixture: &Fixture,
) -> Result<AuthenticatedCompactionProofV1, AuthenticatedCompactionError> {
    prove_compaction_with_signed_evidence_v1(
        &fixture.candidate,
        fixture.binding.clone(),
        fixture.qualification.clone(),
        &fixture.evidence,
        &fixture.verifier,
        /*now*/ 50,
    )
}

#[test]
fn signed_admission_preserves_the_exact_proof_context_and_has_no_writer_authority() {
    let fixture = fixture();
    let admitted = admit(&fixture).expect("authenticated proof");
    assert_eq!(
        admitted.proof(),
        &prove_compaction(&fixture.candidate, fixture.qualification.clone()).expect("proof")
    );
    assert_eq!(admitted.qualification(), &fixture.qualification);
    assert_eq!(admitted.source_binding(), &fixture.binding);
    assert_eq!(admitted.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        admitted.revalidate_for(
            &fixture.candidate,
            fixture.binding.source_cut_digest,
            &fixture.verifier,
            /*now*/ 60
        ),
        Ok(())
    );
}

#[test]
fn candidate_source_cut_and_original_receipt_cannot_be_substituted() {
    let fixture = fixture();
    let admitted = admit(&fixture).expect("proof");
    let mut changed = fixture.candidate.clone();
    changed.selection_input_digest = digest("different-selection");
    changed.candidate_digest = changed.compute_candidate_digest();
    assert_eq!(
        admitted.revalidate_for(
            &changed,
            fixture.binding.source_cut_digest,
            &fixture.verifier,
            /*now*/ 50
        ),
        Err(AuthenticatedCompactionError::CandidateBinding)
    );
    assert_eq!(
        admitted.revalidate_for(
            &fixture.candidate,
            digest("different-cut"),
            &fixture.verifier,
            /*now*/ 50
        ),
        Err(AuthenticatedCompactionError::SourceCutBinding)
    );
    let mut forged = admitted;
    forged.authentication_digest = digest("forged-receipt");
    assert_eq!(
        forged.revalidate_for(
            &fixture.candidate,
            fixture.binding.source_cut_digest,
            &fixture.verifier,
            /*now*/ 50
        ),
        Err(AuthenticatedCompactionError::ReceiptBinding)
    );
}

#[test]
fn authenticated_evaluator_must_match_the_declared_evaluator_even_when_payload_is_resigned() {
    let mut fixture = fixture();
    fixture.qualification.evaluator_id = id("different-evaluator");
    let payload = compaction_qualification_payload_v1(
        &fixture.candidate,
        &fixture.binding,
        &fixture.qualification,
    )
    .expect("payload");
    fixture.evidence = evidence(&fixture.verifier, &payload);
    assert_eq!(
        admit(&fixture),
        Err(AuthenticatedCompactionError::EvaluatorIdentityBinding)
    );
}

#[test]
fn controller_and_credential_collisions_do_not_establish_independent_evaluation() {
    for collision in ["controller", "credential", "key"] {
        let mut fixture = fixture();
        let mut trust = trust(&fixture.binding);
        match collision {
            "controller" => trust.signers[1].controller_id = trust.signers[0].controller_id.clone(),
            "credential" => {
                trust.signers[1].principal.credential_chain_digest =
                    trust.signers[0].principal.credential_chain_digest
            }
            "key" => {
                trust.signers[1].verifying_key = trust.signers[0].verifying_key;
                trust.signers[1].principal.signing_key_digest =
                    trust.signers[0].principal.signing_key_digest;
            }
            _ => unreachable!("test collision"),
        }
        fixture.verifier = LearningEvidenceVerifierV1::new(trust).expect("valid trust structure");
        let payload = compaction_qualification_payload_v1(
            &fixture.candidate,
            &fixture.binding,
            &fixture.qualification,
        )
        .expect("payload");
        fixture.evidence = evidence(&fixture.verifier, &payload);
        if collision == "key" {
            fixture.evidence.evaluator = signed(
                &fixture.verifier,
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                /*seed*/ 1,
                &payload,
            );
        }
        assert!(admit(&fixture).is_err());
    }
}

#[test]
fn wrong_protocol_role_or_invalid_signature_is_rejected() {
    let mut fixture = fixture();
    fixture.evidence.evaluator.role = LearningEvidenceRoleV1::Observer;
    assert!(admit(&fixture).is_err());
    let mut fixture = self::fixture();
    fixture.evidence.evaluator.signature[0] ^= 1;
    assert!(admit(&fixture).is_err());
}

#[test]
fn every_observation_suite_and_flag_remains_signature_bound() {
    let original = fixture();
    for field in 0..7 {
        let mut fixture = fixture();
        match field {
            0 => fixture.qualification.retained_query_suite_digest = digest("different-suite"),
            1 => fixture.qualification.reconstruction_obligation_digest = digest("different-suite"),
            2 => fixture.qualification.contradiction_holdout_digest = digest("different-suite"),
            3 => fixture.qualification.retained_queries_passed = false,
            4 => fixture.qualification.reconstruction_passed = false,
            5 => fixture.qualification.contradictions_preserved = false,
            6 => fixture.qualification.deletion_non_resurrection_passed = false,
            _ => unreachable!("test observation"),
        }
        fixture.evidence = original.evidence.clone();
        assert_ne!(
            qualification_digest(&original.qualification),
            qualification_digest(&fixture.qualification)
        );
        assert!(admit(&fixture).is_err());
    }
}

#[test]
fn current_host_scope_objective_and_epoch_must_match_the_signed_source_binding() {
    for field in ["scope", "objective", "epoch", "cut"] {
        let mut fixture = fixture();
        match field {
            "scope" => fixture.binding.scope_digest = digest("different-scope"),
            "objective" => fixture.binding.objective_digest = digest("different-objective"),
            "epoch" => fixture.binding.authority_epoch += 1,
            "cut" => fixture.binding.source_cut_digest = digest("different-cut"),
            _ => unreachable!("test binding"),
        }
        assert!(admit(&fixture).is_err());
    }
}

#[test]
fn expired_evidence_and_current_revocation_cannot_revalidate_a_stored_admission() {
    let fixture = fixture();
    let admitted = admit(&fixture).expect("proof");
    assert!(
        admitted
            .revalidate_for(
                &fixture.candidate,
                fixture.binding.source_cut_digest,
                &fixture.verifier,
                /*now*/ 91
            )
            .is_err()
    );
    let mut rotated = trust(&fixture.binding);
    rotated.signers[1].controller_id = id("rotated-evaluator-controller");
    let rotated = LearningEvidenceVerifierV1::new(rotated).expect("valid rotated trust");
    assert!(
        admitted
            .revalidate_for(
                &fixture.candidate,
                fixture.binding.source_cut_digest,
                &rotated,
                /*now*/ 60
            )
            .is_err()
    );
    let mut changed = trust(&fixture.binding);
    changed.signers[1].revoked_at = Some(55);
    let revoked = LearningEvidenceVerifierV1::new(changed).expect("current revoked trust");
    assert!(
        admitted
            .revalidate_for(
                &fixture.candidate,
                fixture.binding.source_cut_digest,
                &revoked,
                /*now*/ 60
            )
            .is_err()
    );
    let payload = compaction_qualification_payload_v1(
        &fixture.candidate,
        &fixture.binding,
        &fixture.qualification,
    )
    .expect("payload");
    let resigned = evidence(&revoked, &payload);
    assert!(
        prove_compaction_with_signed_evidence_v1(
            &fixture.candidate,
            fixture.binding.clone(),
            fixture.qualification.clone(),
            &resigned,
            &revoked,
            /*now*/ 60
        )
        .is_err()
    );
}
