#[path = "intelligence_evaluation_product_test_support.rs"]
mod product_fixture;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(
    name: &str,
    credential: &str,
    key: &SigningKey,
    scope: Digest32,
    now: u64,
) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 11,
        authenticated_at: now - 100,
        expires_at: now + 60_000,
    }
}

fn fold(index: u8) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(&format!("fold-{index}")),
        training_principals: vec![id(&format!("train-principal-{index}"))],
        training_episodes: vec![id(&format!("train-episode-{index}"))],
        training_windows: vec![id(&format!("train-window-{index}"))],
        holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
        holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
        holdout_windows: vec![id(&format!("holdout-window-{index}"))],
        model_digest: digest(&format!("model-{index}")),
        predictions_digest: digest(&format!("predictions-{index}")),
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{}-evidence", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: 11,
        issued_at: principal.authenticated_at + 10,
        expires_at: principal.expires_at - 10,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

use super::evaluation::*;
use codex_hepta_intelligence::CanonicalPortInputV1;
use codex_hepta_intelligence::CanonicalStageV1;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Generation;
use std::sync::Arc;

fn activate(trust: LearningEvidenceTrustV1, now: u64) -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: trust.scope_digest,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: now - 200,
        expires_at: now + 120_000,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("distribution"),
            generation: 1,
            effective_at: now - 100,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: now - 150,
        expires_at: now + 60_000,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    activate_learning_trust(&root, distribution, None, now).unwrap()
}

pub(super) fn evidence_fixture(
    binding: &AgentdEvaluationBindingV1,
    now: u64,
) -> (ActivatedLearningTrustV1, AgentdQualifiedEvaluationV1) {
    evidence_fixture_with_policy(binding, now, GeneratorEvidencePolicy::Current)
}

#[derive(Clone, Copy)]
enum GeneratorEvidencePolicy {
    Current,
    ExpiresAt(u64),
    RevokedAt(u64),
}

fn evidence_fixture_with_policy(
    binding: &AgentdEvaluationBindingV1,
    now: u64,
    policy: GeneratorEvidencePolicy,
) -> (ActivatedLearningTrustV1, AgentdQualifiedEvaluationV1) {
    let objective_digest = binding.objective_digest;
    let dataset_digest = digest("dataset");
    let estimand_digest = digest("qualification-estimand");
    let scope_digest = digest("shared-learning-scope");
    let generator_key = SigningKey::from_bytes(&[31; 32]);
    let evaluator_key = SigningKey::from_bytes(&[47; 32]);
    let generator = principal(
        "generator",
        "generator-credential",
        &generator_key,
        scope_digest,
        now,
    );
    let evaluator = principal(
        "evaluator",
        "evaluator-credential",
        &evaluator_key,
        scope_digest,
        now,
    );

    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::from_raw(5),
        },
    }];
    let plan = CrossFoldPlanV1 {
        plan_id: id("qualification-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: binding.selected_candidate_id.clone(),
        baseline_id: id("baseline"),
        objective_digest,
        dataset_digest,
        estimand_digest,
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-utility"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![fold(1), fold(2)],
        final_holdout_window_id: id("holdout-window-2"),
        final_holdout_digest: digest("final-holdout"),
    };

    let trust_definition = LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch: 11,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: generator.clone(),
                controller_id: generator.principal_id.clone(),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: match policy {
                    GeneratorEvidencePolicy::RevokedAt(at) => Some(at),
                    GeneratorEvidencePolicy::Current | GeneratorEvidencePolicy::ExpiresAt(_) => {
                        None
                    }
                },
            },
            TrustedLearningSignerV1 {
                principal: evaluator.clone(),
                controller_id: evaluator.principal_id.clone(),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    };
    let trust = activate(trust_definition, now);
    let verifier = trust.verifier();

    let qualification = product_fixture::qualify(
        plan,
        roles,
        generator.clone(),
        evaluator.clone(),
        verifier,
        now,
        |role, payload| {
            let (principal, key) = match role {
                LearningEvidenceRoleV1::Generator => (&generator, &generator_key),
                LearningEvidenceRoleV1::Evaluator => (&evaluator, &evaluator_key),
                LearningEvidenceRoleV1::Observer
                | LearningEvidenceRoleV1::CreditAllocator
                | LearningEvidenceRoleV1::UnlearningAuthority
                | LearningEvidenceRoleV1::Selector => panic!("fixture has no other signer"),
            };
            let mut evidence = sign(verifier, principal, key, role, objective_digest, payload);
            if role == LearningEvidenceRoleV1::Generator
                && let GeneratorEvidencePolicy::ExpiresAt(at) = policy
            {
                evidence.expires_at = at;
                evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
            }
            evidence
        },
    )
    .expect("true product qualification");
    let payload = intelligence_evaluation_binding_payload_v2(binding, &qualification).unwrap();
    let use_attestation = sign(
        verifier,
        &evaluator,
        &evaluator_key,
        LearningEvidenceRoleV1::Evaluator,
        objective_digest,
        &payload,
    );
    (
        trust,
        AgentdQualifiedEvaluationV1 {
            qualification,
            use_attestation,
        },
    )
}

fn binding() -> AgentdEvaluationBindingV1 {
    AgentdEvaluationBindingV1 {
        run_id: id("run"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        context_receipt_digest: digest("context"),
        candidate_set_digest: digest("candidate-set"),
        selected_candidate_id: id("candidate"),
    }
}

fn input(binding: &AgentdEvaluationBindingV1) -> CanonicalPortInputV1 {
    CanonicalPortInputV1 {
        run_id: binding.run_id.clone(),
        objective_digest: binding.objective_digest,
        snapshot_digest: binding.snapshot_digest,
        predecessor_digest: binding.context_receipt_digest,
        candidate_set_digest: binding.candidate_set_digest,
        budget_micros: 10_000_000,
        stage: CanonicalStageV1::EvaluationAdmitted,
    }
}

fn session(binding: &AgentdEvaluationBindingV1, now: u64) -> AgentdEvaluationSessionV1 {
    let (trust, signed) = evidence_fixture(binding, now);
    AgentdEvaluationSessionV1 {
        run_id: binding.run_id.clone(),
        current_owner: CurrentOwnerStateV1 {
            owner_id: id("learning.eval"),
            generation: Generation::new(7).unwrap(),
            implementation_digest: digest("eval-code"),
            key_digest: signed.qualification.evaluator.signing_key_digest,
            key_epoch: 1,
            authority_epoch: 11,
            revocation_frontier_digest: digest("frontier"),
        },
        trust: Arc::new(trust),
        signed,
    }
}

#[test]
fn signed_candidate_passes_only_with_bound_owner_run_context_and_root_trust() {
    let binding = binding();
    let receipt = session(&binding, 1_000)
        .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
        .unwrap();
    assert!(!receipt.is_zero());
}

#[test]
fn signed_use_rejects_context_snapshot_candidate_set_and_run_substitution() {
    let binding = binding();
    for field in 0..5 {
        let mut changed = input(&binding);
        match field {
            0 => changed.run_id = id("other-run"),
            1 => changed.predecessor_digest = digest("other-context"),
            2 => changed.snapshot_digest = digest("other-snapshot"),
            3 => changed.candidate_set_digest = digest("other-set"),
            _ => changed.objective_digest = digest("other-objective"),
        }
        assert!(
            session(&binding, 1_000)
                .evaluate(&changed, &binding.selected_candidate_id, 1_000)
                .is_err()
        );
    }
    assert!(
        session(&binding, 1_000)
            .evaluate(&input(&binding), &id("other-action"), 1_000)
            .is_err()
    );
}

#[test]
fn evaluator_key_epoch_expiry_and_signed_metrics_are_not_self_asserted() {
    let binding = binding();
    let mut changed = session(&binding, 1_000);
    changed.current_owner.key_digest = digest("different-key");
    assert!(
        changed
            .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
            .is_err()
    );
    let mut changed = session(&binding, 1_000);
    changed.current_owner.authority_epoch += 1;
    assert!(
        changed
            .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
            .is_err()
    );
    assert!(
        session(&binding, 1_000)
            .evaluate(&input(&binding), &binding.selected_candidate_id, 62_000)
            .is_err()
    );
    let mut changed = session(&binding, 1_000);
    changed.signed.qualification.publication_digest = Digest32::ZERO;
    assert!(
        changed
            .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
            .is_err()
    );
    let mut changed = session(&binding, 1_000);
    changed.signed.use_attestation.signature[0] ^= 1;
    assert!(
        changed
            .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
            .is_err()
    );
}

#[test]
fn qualification_consumption_rejects_unsealed_decisions_and_changed_host_trust() {
    let binding = binding();
    for field in 0..4 {
        let mut changed = session(&binding, 1_000);
        match field {
            0 => changed.signed.qualification.decision.decision.baseline_id = id("forged-baseline"),
            1 => {
                changed.signed.qualification.decision.decision.disposition =
                    codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1::Ineligible
            }
            2 => changed
                .signed
                .qualification
                .decision
                .decision
                .failed_metrics
                .push(id("forged-metric")),
            _ => changed.trust = Arc::new(evidence_fixture(&binding, 1_001).0),
        }
        assert!(
            changed
                .evaluate(&input(&binding), &binding.selected_candidate_id, 1_000)
                .is_err()
        );
    }
}

#[test]
fn fresh_evaluator_use_cannot_extend_original_generator_evidence_or_scheduled_revocation() {
    let binding = binding();
    for policy in [
        GeneratorEvidencePolicy::RevokedAt(1_500),
        GeneratorEvidencePolicy::ExpiresAt(1_500),
    ] {
        let (trust, mut signed) = evidence_fixture_with_policy(&binding, 1_000, policy);
        // The evaluator is live and explicitly authorizes this exact current use.
        // The unchanged trust digest already includes the future revocation.
        signed.use_attestation.issued_at = 1_990;
        signed.use_attestation.signature = SigningKey::from_bytes(&[47; 32])
            .sign(&signed.use_attestation.signing_bytes())
            .to_bytes();
        let payload = intelligence_evaluation_binding_payload_v2(&binding, &signed.qualification)
            .expect("current-use payload");
        trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed.use_attestation,
                &payload,
                2_000,
            )
            .expect("fresh independent evaluator use remains valid");
        let session = AgentdEvaluationSessionV1 {
            run_id: binding.run_id.clone(),
            current_owner: CurrentOwnerStateV1 {
                owner_id: id("learning.eval"),
                generation: Generation::new(7).unwrap(),
                implementation_digest: digest("eval-code"),
                key_digest: signed.qualification.evaluator.signing_key_digest,
                key_epoch: 1,
                authority_epoch: 11,
                revocation_frontier_digest: digest("frontier"),
            },
            trust: Arc::new(trust),
            signed,
        };
        let expected = match policy {
            GeneratorEvidencePolicy::RevokedAt(_) => {
                codex_hepta_learning_ledger::SignedEvidenceError::Revoked
            }
            GeneratorEvidencePolicy::ExpiresAt(_) => {
                codex_hepta_learning_ledger::SignedEvidenceError::ValidityWindow
            }
            GeneratorEvidencePolicy::Current => panic!("negative fixture requires a boundary"),
        };
        assert!(matches!(
            session.evaluate(&input(&binding), &binding.selected_candidate_id, 2_000),
            Err(AgentdIntelligenceEvaluationError::Qualification(
                codex_hepta_intelligence_eval::ProductEvaluationError::Signed(
                    codex_hepta_intelligence_eval::SignedEvaluationError::Evidence(error)
                )
            )) if error == expected
        ));
    }
}
