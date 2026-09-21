//! Cryptographically authenticated operator-evaluation admission.
//!
//! Legacy applicability/regularity validators remain deterministic structural
//! checks. Qualification-scoped external evaluation uses the host-owned
//! LearningEvidenceVerifierV1 and signed role separation so a nonzero credential
//! digest or caller-supplied boolean can never be mistaken for authenticated
//! independent evidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::OperatorApplicabilityCertificateV1;
use crate::OperatorClosureError;
use crate::OperatorRegularityAdmissionV1;
use crate::OperatorRegularityAssessmentV1;
use crate::admit_operator_regularity;
use crate::validate_applicability_certificate;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOperatorApplicabilityAdmissionV2 {
    pub certificate_digest: Digest32,
    pub generator_id: StableId,
    pub evaluator_id: StableId,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedOperatorRegularityAdmissionV2 {
    pub admission: OperatorRegularityAdmissionV1,
    pub generator_id: StableId,
    pub evaluator_id: StableId,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn operator_applicability_signing_payload_v2(
    certificate: &OperatorApplicabilityCertificateV1,
    now: u64,
) -> Result<Vec<u8>, AuthenticatedOperatorEvidenceError> {
    let certificate_digest = validate_applicability_certificate(certificate, now)?;
    let mut bytes = b"hepta.bellman-operator.signed-applicability.v2".to_vec();
    bytes.extend_from_slice(certificate_digest.as_array());
    Ok(bytes)
}

pub fn operator_regularity_signing_payload_v2(
    assessment: &OperatorRegularityAssessmentV1,
) -> Result<Vec<u8>, AuthenticatedOperatorEvidenceError> {
    let admission = admit_operator_regularity(assessment.clone())?;
    let mut bytes = b"hepta.bellman-operator.signed-regularity.v2".to_vec();
    bytes.extend_from_slice(admission.assessment_digest.as_array());
    Ok(bytes)
}

pub fn admit_signed_operator_applicability_v2(
    certificate: &OperatorApplicabilityCertificateV1,
    generator_evidence: &SignedLearningEvidenceV1,
    evaluator_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedOperatorApplicabilityAdmissionV2, AuthenticatedOperatorEvidenceError> {
    let payload = operator_applicability_signing_payload_v2(certificate, now)?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        generator_evidence,
        &payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evaluator_evidence,
        &payload,
        now,
    )?;
    verify_signed_role_separation(&generator, &evaluator, now)?;
    if evaluator.principal().principal_id != certificate.evaluator_id
        || evaluator.principal().credential_chain_digest != certificate.evaluator_credential_digest
    {
        return Err(AuthenticatedOperatorEvidenceError::IdentityBinding);
    }

    let certificate_digest = validate_applicability_certificate(certificate, now)?;
    Ok(AuthenticatedOperatorApplicabilityAdmissionV2 {
        certificate_digest,
        generator_id: generator.principal().principal_id.clone(),
        evaluator_id: evaluator.principal().principal_id.clone(),
        trust_digest: verifier.trust_digest(),
        authentication_digest: authentication_digest(
            b"hepta.bellman-operator.applicability-auth.v2",
            verifier.trust_digest(),
            certificate_digest,
            generator_evidence,
            evaluator_evidence,
        ),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn admit_signed_operator_regularity_v2(
    assessment: &OperatorRegularityAssessmentV1,
    generator_evidence: &SignedLearningEvidenceV1,
    evaluator_evidence: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedOperatorRegularityAdmissionV2, AuthenticatedOperatorEvidenceError> {
    let payload = operator_regularity_signing_payload_v2(assessment)?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        generator_evidence,
        &payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evaluator_evidence,
        &payload,
        now,
    )?;
    verify_signed_role_separation(&generator, &evaluator, now)?;
    if evaluator.principal().principal_id != assessment.evaluator_id
        || evaluator.principal().credential_chain_digest != assessment.evaluator_credential_digest
    {
        return Err(AuthenticatedOperatorEvidenceError::IdentityBinding);
    }

    let admission = admit_operator_regularity(assessment.clone())?;
    let assessment_digest = admission.assessment_digest;
    Ok(AuthenticatedOperatorRegularityAdmissionV2 {
        admission,
        generator_id: generator.principal().principal_id.clone(),
        evaluator_id: evaluator.principal().principal_id.clone(),
        trust_digest: verifier.trust_digest(),
        authentication_digest: authentication_digest(
            b"hepta.bellman-operator.regularity-auth.v2",
            verifier.trust_digest(),
            assessment_digest,
            generator_evidence,
            evaluator_evidence,
        ),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn authentication_digest(
    domain: &[u8],
    trust_digest: Digest32,
    subject_digest: Digest32,
    generator_evidence: &SignedLearningEvidenceV1,
    evaluator_evidence: &SignedLearningEvidenceV1,
) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    for evidence in [generator_evidence, evaluator_evidence] {
        bytes.extend_from_slice(Digest32::of_bytes(&evidence.signing_bytes()).as_array());
        bytes.extend_from_slice(&evidence.signature);
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedOperatorEvidenceError {
    Operator(OperatorClosureError),
    Evidence(SignedEvidenceError),
    IdentityBinding,
}

impl fmt::Display for AuthenticatedOperatorEvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthenticatedOperatorEvidenceError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Operator(error) => Some(error),
            Self::Evidence(error) => Some(error),
            Self::IdentityBinding => None,
        }
    }
}

impl From<OperatorClosureError> for AuthenticatedOperatorEvidenceError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Operator(value)
    }
}

impl From<SignedEvidenceError> for AuthenticatedOperatorEvidenceError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_types::FixedQ32;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::ApplicabilityDecisionV1;
    use crate::OperatorErrorComponentV1;

    struct Fixture {
        verifier: LearningEvidenceVerifierV1,
        generator_key: SigningKey,
        evaluator_key: SigningKey,
        generator: AuthenticatedPrincipalV1,
        evaluator: AuthenticatedPrincipalV1,
        scope: Digest32,
        objective: Digest32,
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned())
            .unwrap_or_else(|error| panic!("valid fixture id: {error:?}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn principal(
        name: &str,
        credential: &str,
        key: &SigningKey,
        scope: Digest32,
    ) -> AuthenticatedPrincipalV1 {
        AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(credential),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 11,
            authenticated_at: 10,
            expires_at: 100,
        }
    }

    fn fixture() -> Fixture {
        let generator_key = SigningKey::from_bytes(&[5; 32]);
        let evaluator_key = SigningKey::from_bytes(&[7; 32]);
        let scope = digest("scope");
        let objective = digest("objective");
        let generator = principal(
            "operator-generator",
            "generator-credential",
            &generator_key,
            scope,
        );
        let evaluator = principal(
            "independent-evaluator",
            "evaluator-credential",
            &evaluator_key,
            scope,
        );
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 11,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: generator.clone(),
                    controller_id: id("generator-controller"),
                    verifying_key: generator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: evaluator.clone(),
                    controller_id: id("evaluator-controller"),
                    verifying_key: evaluator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Evaluator],
                    revoked_at: None,
                },
            ],
        })
        .unwrap_or_else(|error| panic!("host trust: {error:?}"));
        Fixture {
            verifier,
            generator_key,
            evaluator_key,
            generator,
            evaluator,
            scope,
            objective,
        }
    }

    fn sign(
        fixture: &Fixture,
        payload: &[u8],
        role: LearningEvidenceRoleV1,
    ) -> SignedLearningEvidenceV1 {
        let (principal, key, evidence_id) = match role {
            LearningEvidenceRoleV1::Generator => (
                &fixture.generator,
                &fixture.generator_key,
                "generator-evidence",
            ),
            LearningEvidenceRoleV1::Evaluator => (
                &fixture.evaluator,
                &fixture.evaluator_key,
                "evaluator-evidence",
            ),
            LearningEvidenceRoleV1::Observer => panic!("observer not used in operator fixture"),
            LearningEvidenceRoleV1::DatasetOwner => {
                panic!("dataset owner not used in evaluator fixture")
            }
        };
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(evidence_id),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: fixture.verifier.trust_digest(),
            scope_digest: fixture.scope,
            objective_digest: fixture.objective,
            authority_epoch: 11,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }

    fn certificate() -> OperatorApplicabilityCertificateV1 {
        OperatorApplicabilityCertificateV1 {
            certificate_id: id("applicability"),
            axis_partition_digest: digest("axis"),
            domain_digest: digest("domain"),
            action_space_digest: digest("actions"),
            holder_exponents_digest: digest("holder-exponents"),
            holder_constants_digest: digest("holder-constants"),
            state_lipschitz_digest: digest("state-lipschitz"),
            action_lipschitz_digest: digest("action-lipschitz"),
            ellipticity_nu_lcb: FixedQ32::from_raw(1),
            control_interval_millis: 100,
            evaluator_id: id("independent-evaluator"),
            evaluator_credential_digest: digest("evaluator-credential"),
            fallback_digest: digest("fallback"),
            expires_at: 100,
            decision: ApplicabilityDecisionV1::Pass,
        }
    }

    fn assessment() -> OperatorRegularityAssessmentV1 {
        OperatorRegularityAssessmentV1 {
            artifact_id: id("operator-artifact"),
            measured_rank: 8,
            reconstruction_gain_q32: FixedQ32::ONE,
            monotonicity_violations: 0,
            positivity_violations: 0,
            holder_residual_q32: FixedQ32::from_raw(10),
            action_lipschitz_residual_q32: FixedQ32::from_raw(10),
            ood_false_acceptance_q32: FixedQ32::from_raw(10),
            error_components: vec![
                OperatorErrorComponentV1 {
                    component_id: id("model"),
                    normalized_error: FixedQ32::from_raw(10),
                    evidence_digest: digest("model-error"),
                },
                OperatorErrorComponentV1 {
                    component_id: id("sensor"),
                    normalized_error: FixedQ32::from_raw(10),
                    evidence_digest: digest("sensor-error"),
                },
            ],
            dominant_component_approved: false,
            evaluator_id: id("independent-evaluator"),
            evaluator_credential_digest: digest("evaluator-credential"),
        }
    }

    #[test]
    fn op_06_signed_applicability_authenticates_exact_evaluator_and_payload() {
        let fixture = fixture();
        let certificate = certificate();
        let payload = operator_applicability_signing_payload_v2(&certificate, 50)
            .unwrap_or_else(|error| panic!("payload: {error:?}"));
        let generator = sign(&fixture, &payload, LearningEvidenceRoleV1::Generator);
        let evaluator = sign(&fixture, &payload, LearningEvidenceRoleV1::Evaluator);
        let admitted = admit_signed_operator_applicability_v2(
            &certificate,
            &generator,
            &evaluator,
            &fixture.verifier,
            50,
        )
        .unwrap_or_else(|error| panic!("authenticated admission: {error:?}"));
        assert_eq!(admitted.generator_id, id("operator-generator"));
        assert_eq!(admitted.evaluator_id, id("independent-evaluator"));
        assert_eq!(admitted.trust_digest, fixture.verifier.trust_digest());
        assert_eq!(admitted.authority, AuthorityPosture::DENY_ALL);

        let mut altered = certificate;
        altered.fallback_digest = digest("changed-fallback");
        assert!(
            admit_signed_operator_applicability_v2(
                &altered,
                &generator,
                &evaluator,
                &fixture.verifier,
                50,
            )
            .is_err()
        );
    }

    #[test]
    fn op_06_signed_regularity_rejects_role_or_identity_drift() {
        let fixture = fixture();
        let assessment = assessment();
        let payload = operator_regularity_signing_payload_v2(&assessment)
            .unwrap_or_else(|error| panic!("payload: {error:?}"));
        let generator = sign(&fixture, &payload, LearningEvidenceRoleV1::Generator);
        assert!(
            admit_signed_operator_regularity_v2(
                &assessment,
                &generator,
                &generator,
                &fixture.verifier,
                50,
            )
            .is_err()
        );

        let mut wrong_identity = assessment;
        wrong_identity.evaluator_id = id("different-evaluator");
        let payload = operator_regularity_signing_payload_v2(&wrong_identity)
            .unwrap_or_else(|error| panic!("payload: {error:?}"));
        let generator = sign(&fixture, &payload, LearningEvidenceRoleV1::Generator);
        let evaluator = sign(&fixture, &payload, LearningEvidenceRoleV1::Evaluator);
        assert_eq!(
            admit_signed_operator_regularity_v2(
                &wrong_identity,
                &generator,
                &evaluator,
                &fixture.verifier,
                50,
            ),
            Err(AuthenticatedOperatorEvidenceError::IdentityBinding)
        );
    }
}
