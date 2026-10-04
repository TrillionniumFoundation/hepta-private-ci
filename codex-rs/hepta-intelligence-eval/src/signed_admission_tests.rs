//! Public admission caller tests using existing synthetic fixture keys only.
//! These fixtures establish no real host, activation, or release authority.
use super::*;
use crate::SignedEligibilityAdmissionError;
use crate::SignedEligibilityAdmissionReceiptV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::admit_signed_eligibility_v2;
use crate::evaluation_signing_payload_v2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

struct Fixture {
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    verifier: LearningEvidenceVerifierV1,
    keys: [SigningKey; 2],
    signers: [AuthenticatedPrincipalV1; 2],
}

impl Fixture {
    fn new(claim_scope: EvaluationClaimScopeV1) -> Self {
        let mut bundle = bundle();
        bundle.claim_scope = claim_scope;
        let mut plan = plan();
        plan.claim_scope = claim_scope;
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        bundle.frozen_plan = freeze_cross_fold_plan_v2(plan, roles.clone()).expect("frozen roles");
        bundle.holdout_use = FinalHoldoutRegistry::new()
            .consume(&bundle.frozen_plan)
            .expect("bound holdout");
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
        ];
        let mut signers = [bundle.generator.clone(), bundle.evaluator.clone()];
        let mut trusted = Vec::new();
        for (index, role) in [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
        ]
        .into_iter()
        .enumerate()
        {
            signers[index].scope_digest = digest("shared-learning-scope");
            signers[index].signing_key_digest =
                Digest32::of_bytes(&keys[index].verifying_key().to_bytes());
            trusted.push(TrustedLearningSignerV1 {
                principal: signers[index].clone(),
                controller_id: signers[index].principal_id.clone(),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            });
        }
        bundle.generator = signers[0].clone();
        bundle.evaluator = signers[1].clone();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("shared-learning-scope"),
            objective_digest: bundle.objective_digest,
            authority_epoch: 4,
            signers: trusted,
        })
        .expect("synthetic fixture trust");
        Self {
            bundle,
            roles,
            verifier,
            keys,
            signers,
        }
    }

    fn evidence(&self) -> SignedEvaluationEvidenceV1 {
        let payload = evaluation_signing_payload_v2(&self.bundle, &self.roles)
            .expect("bounded fixture signing payload");
        let mut attestations = Vec::new();
        for (index, role, payload) in [
            (
                0,
                LearningEvidenceRoleV1::Generator,
                self.bundle.frozen_plan.plan_digest.as_array().as_slice(),
            ),
            (1, LearningEvidenceRoleV1::Evaluator, payload.as_slice()),
        ] {
            let principal = &self.signers[index];
            let mut signed = SignedLearningEvidenceV1 {
                evidence_id: principal.principal_id.clone(),
                principal_id: principal.principal_id.clone(),
                role,
                trust_digest: self.verifier.trust_digest(),
                scope_digest: principal.scope_digest,
                objective_digest: self.bundle.objective_digest,
                authority_epoch: 4,
                issued_at: 20,
                expires_at: 90,
                payload_digest: Digest32::of_bytes(payload),
                signature: [0; 64],
            };
            signed.signature = self.keys[index].sign(&signed.signing_bytes()).to_bytes();
            attestations.push(signed);
        }
        SignedEvaluationEvidenceV1 {
            generator_plan: attestations[0].clone(),
            evaluator_bundle: attestations[1].clone(),
        }
    }

    fn admit(
        &self,
        evidence: &SignedEvaluationEvidenceV1,
        binding: Digest32,
        now: u64,
    ) -> Result<SignedEligibilityAdmissionReceiptV1, SignedEligibilityAdmissionError> {
        admit_signed_eligibility_v2(
            self.bundle.clone(),
            self.roles.clone(),
            evidence,
            &self.verifier,
            binding,
            now,
        )
    }
}

#[test]
fn public_admission_preserves_all_decision_outcomes_without_authority() {
    for disposition in [
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        IndependentEvaluationDispositionV1::Ineligible,
        IndependentEvaluationDispositionV1::InsufficientEvidence,
    ] {
        let mut fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
        let failed_metrics = match disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => Vec::new(),
            IndependentEvaluationDispositionV1::Ineligible => {
                fixture.bundle.metrics[0].candidate = EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(60),
                    upper: FixedQ32::from_raw(65),
                };
                vec![id("task-utility")]
            }
            IndependentEvaluationDispositionV1::InsufficientEvidence => {
                fixture.bundle.metrics[0].support_digest = Digest32::ZERO;
                Vec::new()
            }
        };
        let evidence = fixture.evidence();
        let binding = digest("consumer-request");
        let receipt = fixture
            .admit(&evidence, binding, /*now*/ 50)
            .expect("receipt");
        assert_eq!(receipt.validate_integrity(), Ok(()));
        assert_eq!(
            (
                &receipt.evaluation_id,
                &receipt.candidate_id,
                &receipt.baseline_id,
                receipt.objective_digest,
                receipt.dataset_digest,
                receipt.consumer_binding_digest,
                receipt.decision.trust_digest,
                receipt.decision.decision.disposition,
                &receipt.decision.decision.failed_metrics,
                receipt.authority,
                receipt.decision.decision.authority,
            ),
            (
                &fixture.bundle.evaluation_id,
                &fixture.bundle.candidate_id,
                &fixture.bundle.baseline_id,
                fixture.bundle.objective_digest,
                fixture.bundle.dataset_digest,
                binding,
                fixture.verifier.trust_digest(),
                disposition,
                &failed_metrics,
                AuthorityPosture::DENY_ALL,
                AuthorityPosture::DENY_ALL,
            ),
        );
        assert_eq!(fixture.admit(&evidence, binding, /*now*/ 50), Ok(receipt));
    }
}

#[test]
fn public_admission_seals_the_actual_consumer_binding() {
    let fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    let evidence = fixture.evidence();
    let original_binding = digest("consumer-request");
    let changed_binding = digest("another-consumer-request");
    let mut original = fixture
        .admit(&evidence, original_binding, /*now*/ 50)
        .expect("original receipt");
    let changed = fixture
        .admit(&evidence, changed_binding, /*now*/ 50)
        .expect("separate consumer receipt");
    assert_eq!(changed.validate_integrity(), Ok(()));
    assert_eq!(original.decision, changed.decision);
    assert_ne!(original.evidence_digest, changed.evidence_digest);
    original.consumer_binding_digest = changed_binding;
    assert_eq!(
        original.validate_integrity(),
        Err(SignedEligibilityAdmissionError::Integrity(
            "signed eligibility admission seal"
        )),
    );
}

#[test]
fn public_admission_requires_binding_before_authenticating() {
    let fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    let mut evidence = fixture.evidence();
    evidence.generator_plan.signature = [0; 64];
    assert_eq!(
        fixture.admit(&evidence, Digest32::ZERO, /*now*/ 50),
        Err(SignedEligibilityAdmissionError::Binding(
            "consumer binding digest"
        )),
    );
}

#[test]
fn public_admission_rejects_each_invalid_signature_and_unknown_signer() {
    let fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    let mut invalid_generator = fixture.evidence();
    invalid_generator.generator_plan.signature = [0; 64];
    let mut invalid_evaluator = fixture.evidence();
    invalid_evaluator.evaluator_bundle.signature = [0; 64];
    for evidence in [invalid_generator, invalid_evaluator] {
        assert_eq!(
            fixture.admit(&evidence, digest("consumer-request"), /*now*/ 50),
            Err(SignedEligibilityAdmissionError::Evaluation(
                SignedEvaluationError::Evidence(SignedEvidenceError::InvalidSignature)
            )),
        );
    }
    let mut evidence = fixture.evidence();
    evidence.generator_plan.principal_id = id("unregistered-signer");
    assert_eq!(
        fixture.admit(&evidence, digest("consumer-request"), /*now*/ 50),
        Err(SignedEligibilityAdmissionError::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::UnknownSigner)
        )),
    );
}

#[test]
fn public_admission_rejects_validly_signed_identity_substitution() {
    let mut fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    fixture.bundle.generator.credential_chain_digest = digest("another-credential-chain");
    // Sign the changed payload with the original trusted fixture keys. Both
    // signatures are valid; the asserted bundle principal is not the signer.
    let evidence = fixture.evidence();
    assert_eq!(
        fixture.admit(&evidence, digest("consumer-request"), /*now*/ 50),
        Err(SignedEligibilityAdmissionError::Evaluation(
            SignedEvaluationError::IdentityBinding
        )),
    );
}

#[test]
fn public_admission_accepts_expiry_boundary_and_rejects_the_next_tick() {
    let fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    let evidence = fixture.evidence();
    let receipt = fixture
        .admit(&evidence, digest("consumer-request"), /*now*/ 90)
        .expect("inclusive expiry boundary");
    assert_eq!(receipt.validate_integrity(), Ok(()));
    assert_eq!(
        fixture.admit(&evidence, digest("consumer-request"), /*now*/ 91),
        Err(SignedEligibilityAdmissionError::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::ValidityWindow)
        )),
    );
}

#[test]
fn public_admission_does_not_promote_untimed_longitudinal_evidence() {
    let fixture = Fixture::new(EvaluationClaimScopeV1::SystemLongitudinal);
    assert_eq!(
        fixture.admit(
            &fixture.evidence(),
            digest("consumer-request"),
            /*now*/ 50
        ),
        Err(SignedEligibilityAdmissionError::Evaluation(
            SignedEvaluationError::MissingLongitudinalTiming
        )),
    );
}

#[test]
fn public_admission_rejects_metric_overflow_before_authentication() {
    let mut fixture = Fixture::new(EvaluationClaimScopeV1::Qualification);
    let evidence = fixture.evidence();
    fixture.bundle.metrics = vec![metric(); 129];
    assert_eq!(
        fixture.admit(&evidence, digest("consumer-request"), /*now*/ 50),
        Err(SignedEligibilityAdmissionError::Evaluation(
            SignedEvaluationError::Evaluation(EvaluationClosureError::MetricLimit)
        )),
    );
}
