use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_agentd::AgentdIntuitionPolicyError;
use codex_hepta_agentd::AgentdIntuitionPolicyHostV1;
use codex_hepta_agentd::AgentdIntuitionPolicyPinsV2;
use codex_hepta_agentd::IntuitionPolicyLearningSink;
use codex_hepta_agentd::intuition_risk_rule_digest_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::PolicyGeneration;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_assignment_distribution_digest_v2;
use codex_hepta_intuition::canonical_candidate_identity_digest_v2;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::tempdir;

const NOW: u64 = 150;
const GENERATION: u64 = 4;
const SPAWN_GENERATION: u64 = 7;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(name: &str, key: &SigningKey, scope_digest: Digest32) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("credential:{name}")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest,
        authority_epoch: 9,
        authenticated_at: 1,
        expires_at: 1_000,
    }
}

fn trusted(
    principal: AuthenticatedPrincipalV1,
    controller: &str,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    TrustedLearningSignerV1 {
        principal,
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn trust_material() -> (
    ActivatedLearningTrustV1,
    Arc<LearningEvidenceVerifierV1>,
    [SigningKey; 3],
    [AuthenticatedPrincipalV1; 3],
) {
    let keys = [
        SigningKey::from_bytes(&[11; 32]),
        SigningKey::from_bytes(&[23; 32]),
        SigningKey::from_bytes(&[37; 32]),
    ];
    let scope_digest = digest("scope:intuition-product-v3");
    let principals = [
        principal("generator", &keys[0], scope_digest),
        principal("evaluator", &keys[1], scope_digest),
        principal("observer", &keys[2], scope_digest),
    ];
    let trust = LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest: digest("objective:intuition-product-v3"),
        authority_epoch: 9,
        signers: vec![
            trusted(
                principals[0].clone(),
                "controller:generator",
                &keys[0],
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                principals[1].clone(),
                "controller:evaluator",
                &keys[1],
                LearningEvidenceRoleV1::Evaluator,
            ),
            trusted(
                principals[2].clone(),
                "controller:observer",
                &keys[2],
                LearningEvidenceRoleV1::Observer,
            ),
        ],
    };
    let root_key = SigningKey::from_bytes(&[97; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("root:intuition-product-v3"),
        scope_digest,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("distribution:intuition-product-v3"),
            generation: 1,
            effective_at: 20,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 10,
        expires_at: 900,
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(&signed.signing_bytes().expect("trust distribution payload"))
        .to_bytes();
    let activated = activate_learning_trust(&root, signed, None, 50).expect("activated trust");
    let verifier = Arc::new(activated.verifier().clone());
    (activated, verifier, keys, principals)
}

fn sign_evidence(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: verifier.objective_digest(),
        authority_epoch: principal.authority_epoch,
        issued_at: 100,
        expires_at: 200,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn request_and_profile() -> (CalibratedDecisionRequestV1, CanonicalPolicyProfileV1) {
    let policy_digest = digest("policy:intuition-product-v3");
    let objective_digest = digest("objective:intuition-product-v3");
    let objective_class_digest = digest("objective-class:intuition-product-v3");
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate:ship"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(17),
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("support:candidate:ship"),
    }];
    let candidate_set_digest =
        canonical_candidate_set_digest_v1(&candidates).expect("candidate set digest");
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:intuition-product-v3"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("state:intuition-product-v3"),
        policy_digest,
        policy_generation: GENERATION,
        sequence: 12,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("completeness:intuition-product-v3"),
            generator_digest: digest("generator-code:intuition-product-v3"),
            grammar_digest: digest("grammar:intuition-product-v3"),
            hard_filter_digest: digest("hard-filter:intuition-product-v3"),
            truncation_digest: digest("truncation:intuition-product-v3"),
            candidate_set_digest,
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("candidate order digest"),
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration:intuition-product-v3"),
            policy_digest,
            objective_class_digest,
            generation: GENERATION,
            valid_from_sequence: 1,
            expires_after_sequence: 20,
            measured_ece_ppm: 1,
            subgroup_audit_digest: digest("subgroup:intuition-product-v3"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood:intuition-product-v3"),
            policy_digest,
            detector_digest: digest("detector:intuition-product-v3"),
            support_digest: digest("ood-support:intuition-product-v3"),
            generation: GENERATION,
            valid_from_sequence: 1,
            expires_after_sequence: 20,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 1,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:intuition-product-v3"),
        policy_digest,
        objective_class_digest,
        generation: GENERATION,
        valid_from_sequence: 1,
        expires_after_sequence: 20,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest: digest("model:intuition-product-v3"),
            feature_schema_digest: digest("feature-schema:intuition-product-v3"),
            output_schema_digest: digest("output-schema:intuition-product-v3"),
            score_semantics_digest: digest("score-semantics:intuition-product-v3"),
            scorer_contract_digest: digest("scorer-contract:intuition-product-v3"),
        },
        calibration_dataset_digest: digest("calibration-data:intuition-product-v3"),
        ood_dataset_digest: digest("ood-data:intuition-product-v3"),
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
    };
    (request, profile)
}

fn commitments(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> (ScoringCommitmentV2, AssignmentCommitmentV2) {
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: profile.scorer.model_digest,
        feature_snapshot_digest: digest("feature-snapshot:intuition-product-v3"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        candidate_identity_digest: canonical_candidate_identity_digest_v2(&request.candidates)
            .expect("candidate identity digest"),
        scored_outputs_digest: canonical_scored_outputs_digest_v2(request)
            .expect("scored output digest"),
        policy_digest: request.policy_digest,
        policy_generation: PolicyGeneration::new(request.policy_generation)
            .expect("policy generation"),
    };
    let assignment = AssignmentCommitmentV2::Deterministic {
        distribution_digest: canonical_assignment_distribution_digest_v2(request)
            .expect("assignment distribution digest"),
    };
    (scoring, assignment)
}

fn open_rw(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("open durable test file")
}

#[test]
fn v3_product_host_commits_once_replays_idempotently_and_reopens() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde")
        .expect("agent id");
    let (request, profile) = request_and_profile();
    let (scoring, assignment) = commitments(&request, &profile);
    let (activated, verifier, keys, principals) = trust_material();

    let directory = tempdir().expect("ledger directory");
    let ledger_path = directory.path().join("ledger");
    let witness_path = directory.path().join("witness");
    File::create(&ledger_path).expect("ledger file");
    File::create(&witness_path).expect("witness file");
    let binding = digest("binding:intuition-product-v3");
    let ledger = DurableLedger::create(open_rw(&ledger_path), binding, 64).expect("ledger");
    let witness =
        LedgerWitnessStore::create(open_rw(&witness_path), binding).expect("witness");
    let ledger_directory = File::open(directory.path()).expect("ledger parent");
    let witness_directory = File::open(directory.path()).expect("witness parent");
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        activated,
        &ledger_directory,
        &witness_directory,
    )
    .expect("product ledger writer");
    let learning = Arc::new(IntuitionPolicyLearningSink::new(writer));
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: canonical_policy_profile_digest_v1(&profile)
            .expect("profile digest"),
        policy_digest: profile.policy_digest,
        policy_generation: PolicyGeneration::new(GENERATION).expect("generation"),
        objective_class_digest: profile.objective_class_digest,
        model_artifact_digest: profile.scorer.model_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        calibration_artifact_digest: profile.calibration_artifact_digest,
        ood_artifact_digest: profile.ood_artifact_digest,
        risk_rule_digest: intuition_risk_rule_digest_v1(profile.risk_rule),
        rng_owner_digest: None,
    };
    let host = AgentdIntuitionPolicyHostV1::new_product(
        agent_id.clone(),
        SPAWN_GENERATION,
        verifier.clone(),
        pins,
        learning.clone(),
    )
    .expect("product host");

    let completeness_payload =
        canonical_completeness_evidence_payload_v1(&request).expect("completeness payload");
    let profile_payload =
        canonical_profile_qualification_payload_v1(&profile).expect("profile payload");
    let runtime_payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime payload");
    let completeness = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:completeness:v3",
        &completeness_payload,
    );
    let profile_evidence = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:profile:v3",
        &profile_payload,
    );
    let runtime_evidence = sign_evidence(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:runtime:v3",
        &runtime_payload,
    );

    let qualification = || IntuitionQualificationEvidenceV2 {
        completeness: &completeness,
        profile_qualification: &profile_evidence,
        runtime: &runtime_evidence,
    };

    let mut drifted_profile = profile.clone();
    drifted_profile.calibration_dataset_digest = digest("calibration-data:drifted");
    assert!(matches!(
        host.prepare_v3(
            &agent_id,
            SPAWN_GENERATION,
            request.clone(),
            drifted_profile,
            scoring.clone(),
            assignment.clone(),
            qualification(),
            id("episode:intuition-product-v3"),
            digest("run-snapshot:intuition-product-v3"),
            NOW,
        ),
        Err(AgentdIntuitionPolicyError::ProfilePinMismatch)
    ));
    assert!(matches!(
        host.prepare_v3(
            &agent_id,
            SPAWN_GENERATION + 1,
            request.clone(),
            profile.clone(),
            scoring.clone(),
            assignment.clone(),
            qualification(),
            id("episode:intuition-product-v3"),
            digest("run-snapshot:intuition-product-v3"),
            NOW,
        ),
        Err(AgentdIntuitionPolicyError::GenerationFence)
    ));

    let prepared = host
        .prepare_v3(
            &agent_id,
            SPAWN_GENERATION,
            request,
            profile,
            scoring,
            assignment,
            qualification(),
            id("episode:intuition-product-v3"),
            digest("run-snapshot:intuition-product-v3"),
            NOW,
        )
        .expect("prepared V3 decision");
    assert!(matches!(
        prepared.decision().decision.disposition,
        ProductionDispositionV1::Selected(_)
    ));
    let decision_payload = prepared
        .decision_signing_payload()
        .expect("decision payload result")
        .expect("selected decision payload");
    let decision_evidence = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:durable-decision:v3",
        &decision_payload,
    );
    let replay_prepared = prepared.clone();
    let first = host
        .commit_v3(
            &agent_id,
            SPAWN_GENERATION,
            prepared,
            Digest32::ZERO,
            Some(decision_evidence.clone()),
            NOW,
        )
        .expect("first durable commit");
    let replay = host
        .commit_v3(
            &agent_id,
            SPAWN_GENERATION,
            replay_prepared,
            Digest32::ZERO,
            Some(decision_evidence),
            NOW,
        )
        .expect("idempotent durable replay");
    let first_append = first.learning.as_ref().expect("first append receipt");
    let replay_append = replay.learning.as_ref().expect("replay append receipt");
    assert_eq!(first_append.disposition, AppendDisposition::Appended);
    assert_eq!(replay_append.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first_append.event_digest, replay_append.event_digest);
    assert_eq!(first_append.chain_digest, replay_append.chain_digest);
    assert_eq!(first_append.sequence, replay_append.sequence);
    assert_eq!(first.production_record_id, replay.production_record_id);

    let anchor = LedgerAnchor {
        sequence: first_append.sequence.get(),
        chain_digest: first_append.chain_digest,
    };
    drop(host);
    drop(learning);

    let recovered_ledger = DurableLedger::recover(
        open_rw(&ledger_path),
        binding,
        64,
        LedgerRecovery::Acknowledged(anchor),
    )
    .expect("recovered ledger");
    let recovered_witness =
        LedgerWitnessStore::recover(open_rw(&witness_path), binding).expect("recovered witness");
    let (recovered_trust, _, _, _) = trust_material();
    let ledger_directory = File::open(directory.path()).expect("recovered ledger parent");
    let witness_directory = File::open(directory.path()).expect("recovered witness parent");
    let reopened = LedgerWriter::from_durable(
        recovered_ledger,
        recovered_witness,
        recovered_trust,
        &ledger_directory,
        &witness_directory,
    )
    .expect("reopened writer");
    let records = reopened.records().expect("reopened records");
    assert_eq!(records.len(), 1, "idempotent replay appended a duplicate");
    assert_eq!(reopened.snapshot().expect("snapshot").records, 1);
}
