//! Signature-verified evaluation admission. The host supplies a trusted verifier;
//! callers cannot turn asserted identity digests into authenticated evidence.
//! Frozen plans must still be persisted before collecting their holdout data.
//! Signing metrics authenticates who attested them, not the estimator's validity.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;

use crate::EvaluationClosureError;
use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use crate::MetricRoleContractV2;
use crate::closure::digest_evaluation_bundle;
use crate::closure::digest_evaluation_roles;
use crate::decide_independently;
use crate::decide_independently_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedEvaluationEvidenceV1 {
    /// Generator signs the frozen plan digest bytes under the objective/scope.
    pub generator_plan: SignedLearningEvidenceV1,
    /// Evaluator signs the exact bytes from `evaluation_signing_payload_v1/v2`.
    pub evaluator_bundle: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedEvaluationDecisionV1 {
    pub decision: IndependentEvaluationDecisionV1,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
}

pub fn evaluation_signing_payload_v1(
    bundle: &IndependentEvaluationBundleV1,
) -> Result<Vec<u8>, EvaluationClosureError> {
    let digest = digest_evaluation_bundle(
        bundle,
        IndependentEvaluationDispositionV1::InsufficientEvidence,
        &[],
    )?;
    let mut bytes = b"hepta.intelligence-eval.signed-request.v1".to_vec();
    bytes.extend_from_slice(&(bundle.metrics.len() as u64).to_be_bytes());
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

pub fn evaluation_signing_payload_v2(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
) -> Result<Vec<u8>, EvaluationClosureError> {
    let mut bytes = b"hepta.intelligence-eval.signed-request.v2".to_vec();
    bytes.extend_from_slice(&evaluation_signing_payload_v1(bundle)?);
    bytes.extend_from_slice(digest_evaluation_roles(bundle, roles)?.as_array());
    Ok(bytes)
}

pub fn decide_with_signed_evidence_v1(
    bundle: IndependentEvaluationBundleV1,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
    let payload = evaluation_signing_payload_v1(&bundle)?;
    let authentication_digest = authenticate(&bundle, evidence, verifier, &payload, now)?;
    Ok(SignedEvaluationDecisionV1 {
        decision: decide_independently(bundle, now)?,
        trust_digest: verifier.trust_digest(),
        authentication_digest,
    })
}

pub fn decide_with_signed_evidence_v2(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
    let payload = evaluation_signing_payload_v2(&bundle, &roles)?;
    let authentication_digest = authenticate(&bundle, evidence, verifier, &payload, now)?;
    Ok(SignedEvaluationDecisionV1 {
        decision: decide_independently_v2(bundle, roles, now)?,
        trust_digest: verifier.trust_digest(),
        authentication_digest,
    })
}

fn authenticate(
    bundle: &IndependentEvaluationBundleV1,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    payload: &[u8],
    now: u64,
) -> Result<Digest32, SignedEvaluationError> {
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator_plan,
        bundle.frozen_plan.plan_digest.as_array(),
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence.evaluator_bundle,
        payload,
        now,
    )?;
    if generator.principal() != &bundle.generator
        || evaluator.principal() != &bundle.evaluator
        || evidence.generator_plan.objective_digest != bundle.objective_digest
        || evidence.evaluator_bundle.objective_digest != bundle.objective_digest
    {
        return Err(SignedEvaluationError::IdentityBinding);
    }
    verify_signed_role_separation(&generator, &evaluator, now)?;
    let mut bytes = b"hepta.intelligence-eval.authenticated-decision.v1".to_vec();
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    for attestation in [&evidence.generator_plan, &evidence.evaluator_bundle] {
        bytes.extend_from_slice(Digest32::of_bytes(&attestation.signing_bytes()).as_array());
        bytes.extend_from_slice(&attestation.signature);
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SignedEvaluationError {
    Evidence(SignedEvidenceError),
    Evaluation(EvaluationClosureError),
    IdentityBinding,
}
impl fmt::Display for SignedEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SignedEvaluationError {}
impl From<SignedEvidenceError> for SignedEvaluationError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<EvaluationClosureError> for SignedEvaluationError {
    fn from(value: EvaluationClosureError) -> Self {
        Self::Evaluation(value)
    }
}
