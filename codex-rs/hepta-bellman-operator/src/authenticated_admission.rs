//! Authenticated evaluator admission for applicability and regularity claims.
//!
//! Structural Bellman validation remains pure and deterministic. This module adds
//! the cryptographic/role boundary required before those structural results may be
//! described as independently evaluated evidence. Trust always comes from the
//! host-owned `LearningEvidenceVerifierV1`; caller-supplied credential digests
//! alone are never authentication.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::OperatorApplicabilityCertificateV1;
use crate::OperatorClosureError;
use crate::OperatorRegularityAssessmentV1;
use crate::admit_operator_regularity;
use crate::validate_applicability_certificate;

const APPLICABILITY_DOMAIN: &[u8] =
    b"hepta.bellman-operator.authenticated-applicability.v1";
const REGULARITY_DOMAIN: &[u8] =
    b"hepta.bellman-operator.authenticated-regularity.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedApplicabilityAdmissionV1 {
    pub certificate_id: StableId,
    pub certificate_digest: Digest32,
    pub evaluator_id: StableId,
    pub evaluator_statement_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedRegularityAdmissionV1 {
    pub artifact_id: StableId,
    pub assessment_digest: Digest32,
    pub evaluator_id: StableId,
    pub evaluator_statement_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedEvaluatorError {
    Structural(OperatorClosureError),
    Signed(SignedEvidenceError),
    EvaluatorIdentityMismatch,
    EvaluatorCredentialMismatch,
}

impl fmt::Display for AuthenticatedEvaluatorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthenticatedEvaluatorError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Structural(error) => Some(error),
            Self::Signed(error) => Some(error),
            Self::EvaluatorIdentityMismatch | Self::EvaluatorCredentialMismatch => None,
        }
    }
}

impl From<OperatorClosureError> for AuthenticatedEvaluatorError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Structural(value)
    }
}

impl From<SignedEvidenceError> for AuthenticatedEvaluatorError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Signed(value)
    }
}

/// Validate the applicability certificate and authenticate the exact resulting
/// structural digest as an independent evaluator statement.
pub fn admit_authenticated_applicability_v1(
    certificate: &OperatorApplicabilityCertificateV1,
    generator: &VerifiedLearningEvidenceV1,
    signed_evaluator: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedApplicabilityAdmissionV1, AuthenticatedEvaluatorError> {
    let certificate_digest = validate_applicability_certificate(certificate, now)?;
    let statement = evaluator_statement(APPLICABILITY_DOMAIN, certificate_digest);
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        signed_evaluator,
        &statement,
        now,
    )?;
    require_evaluator_binding(
        &certificate.evaluator_id,
        certificate.evaluator_credential_digest,
        &evaluator,
    )?;
    verify_signed_role_separation(generator, &evaluator, now)?;

    Ok(AuthenticatedApplicabilityAdmissionV1 {
        certificate_id: certificate.certificate_id.clone(),
        certificate_digest,
        evaluator_id: evaluator.principal().principal_id.clone(),
        evaluator_statement_digest: evaluator.payload_digest(),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Validate the complete regularity/error budget and authenticate the exact
/// resulting assessment digest as an independent evaluator statement.
///
/// This makes `dominant_component_approved` part of signed evidence instead of
/// trusting a caller-provided boolean in isolation.
pub fn admit_authenticated_regularity_v1(
    assessment: &OperatorRegularityAssessmentV1,
    generator: &VerifiedLearningEvidenceV1,
    signed_evaluator: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedRegularityAdmissionV1, AuthenticatedEvaluatorError> {
    let structural = admit_operator_regularity(assessment.clone())?;
    let statement = evaluator_statement(REGULARITY_DOMAIN, structural.assessment_digest);
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        signed_evaluator,
        &statement,
        now,
    )?;
    require_evaluator_binding(
        &assessment.evaluator_id,
        assessment.evaluator_credential_digest,
        &evaluator,
    )?;
    verify_signed_role_separation(generator, &evaluator, now)?;

    Ok(AuthenticatedRegularityAdmissionV1 {
        artifact_id: structural.artifact_id,
        assessment_digest: structural.assessment_digest,
        evaluator_id: evaluator.principal().principal_id.clone(),
        evaluator_statement_digest: evaluator.payload_digest(),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_evaluator_binding(
    evaluator_id: &StableId,
    credential_digest: Digest32,
    evaluator: &VerifiedLearningEvidenceV1,
) -> Result<(), AuthenticatedEvaluatorError> {
    if evaluator_id != &evaluator.principal().principal_id {
        return Err(AuthenticatedEvaluatorError::EvaluatorIdentityMismatch);
    }
    if credential_digest != evaluator.principal().credential_chain_digest {
        return Err(AuthenticatedEvaluatorError::EvaluatorCredentialMismatch);
    }
    Ok(())
}

fn evaluator_statement(domain: &[u8], digest: Digest32) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(domain.len() + 32);
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(digest.as_array());
    bytes
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

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn signer(
        name: &str,
        controller: &str,
        seed: u8,
        role: LearningEvidenceRoleV1,
    ) -> TrustedLearningSignerV1 {
        let key = SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: digest(&format!("{name}-credential")),
                signing_key_digest: Digest32::of_bytes(&key),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id(controller),
            verifying_key: key,
            roles: vec![role],
            revoked_at: None,
        }
    }

    fn trust(shared_controller: bool) -> LearningEvidenceTrustV1 {
        LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: vec![
                signer(
                    "generator",
                    "controller-a",
                    1,
                    LearningEvidenceRoleV1::Generator,
                ),
                signer(
                    "evaluator",
                    if shared_controller {
                        "controller-a"
                    } else {
                        "controller-b"
                    },
                    2,
                    LearningEvidenceRoleV1::Evaluator,
                ),
            ],
        }
    }

    fn sign(
        verifier: &LearningEvidenceVerifierV1,
        name: &str,
        role: LearningEvidenceRoleV1,
        seed: u8,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("evidence-{name}")),
            principal_id: id(name),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[seed; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    fn generator(verifier: &LearningEvidenceVerifierV1) -> VerifiedLearningEvidenceV1 {
        let payload = b"candidate-generation";
        let signed = sign(
            verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            payload,
        );
        verifier
            .verify(LearningEvidenceRoleV1::Generator, &signed, payload, 50)
            .expect("generator evidence")
    }

    fn applicability() -> OperatorApplicabilityCertificateV1 {
        OperatorApplicabilityCertificateV1 {
            certificate_id: id("certificate"),
            axis_partition_digest: digest("axis"),
            domain_digest: digest("domain"),
            action_space_digest: digest("actions"),
            holder_exponents_digest: digest("holder-exponents"),
            holder_constants_digest: digest("holder-constants"),
            state_lipschitz_digest: digest("state-lipschitz"),
            action_lipschitz_digest: digest("action-lipschitz"),
            ellipticity_nu_lcb: FixedQ32::from_raw(1),
            control_interval_millis: 100,
            evaluator_id: id("evaluator"),
            evaluator_credential_digest: digest("evaluator-credential"),
            fallback_digest: digest("fallback"),
            expires_at: 80,
            decision: ApplicabilityDecisionV1::Pass,
        }
    }

    fn regularity() -> OperatorRegularityAssessmentV1 {
        OperatorRegularityAssessmentV1 {
            artifact_id: id("artifact"),
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
            evaluator_id: id("evaluator"),
            evaluator_credential_digest: digest("evaluator-credential"),
        }
    }

    #[test]
    fn op_06_applicability_requires_authenticated_independent_evaluator() {
        let verifier = LearningEvidenceVerifierV1::new(trust(false)).expect("host trust");
        let generator = generator(&verifier);
        let certificate = applicability();
        let structural =
            validate_applicability_certificate(&certificate, 50).expect("structural certificate");
        let statement = evaluator_statement(APPLICABILITY_DOMAIN, structural);
        let evaluator = sign(
            &verifier,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            2,
            &statement,
        );
        let admitted = admit_authenticated_applicability_v1(
            &certificate,
            &generator,
            &evaluator,
            &verifier,
            50,
        )
        .expect("authenticated applicability");
        assert_eq!(admitted.evaluator_id, id("evaluator"));
        assert!(!admitted.authority.grants_any());

        let shared = LearningEvidenceVerifierV1::new(trust(true)).expect("shared controller trust");
        let shared_generator = generator(&shared);
        let shared_evaluator = sign(
            &shared,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            2,
            &statement,
        );
        assert!(matches!(
            admit_authenticated_applicability_v1(
                &certificate,
                &shared_generator,
                &shared_evaluator,
                &shared,
                50,
            ),
            Err(AuthenticatedEvaluatorError::Signed(
                SignedEvidenceError::ControllerCollision
            ))
        ));
    }

    #[test]
    fn op_06_regularity_signature_binds_dominance_and_metrics() {
        let verifier = LearningEvidenceVerifierV1::new(trust(false)).expect("host trust");
        let generator = generator(&verifier);
        let assessment = regularity();
        let structural = admit_operator_regularity(assessment.clone()).expect("structural regularity");
        let statement = evaluator_statement(REGULARITY_DOMAIN, structural.assessment_digest);
        let evaluator = sign(
            &verifier,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            2,
            &statement,
        );
        admit_authenticated_regularity_v1(
            &assessment,
            &generator,
            &evaluator,
            &verifier,
            50,
        )
        .expect("authenticated regularity");

        let mut altered = assessment;
        altered.holder_residual_q32 = FixedQ32::from_raw(11);
        assert!(matches!(
            admit_authenticated_regularity_v1(
                &altered,
                &generator,
                &evaluator,
                &verifier,
                50,
            ),
            Err(AuthenticatedEvaluatorError::Signed(
                SignedEvidenceError::PayloadMismatch
            ))
        ));
    }
}
