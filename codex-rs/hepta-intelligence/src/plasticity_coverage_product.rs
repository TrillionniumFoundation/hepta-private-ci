//! Product admission wrapper for generator coverage evidence.
//!
//! The underlying plasticity product verifies generated candidates and independent
//! evaluation. This wrapper additionally requires the same trusted Observer that
//! attests admission to sign an exact generator-coverage receipt. It still grants
//! no selection, training, installation, activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::GeneratorCoverageTerminalV1;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;

use crate::plasticity_product::AnchoredPlasticityWriterV1;
use crate::plasticity_product::ParameterPlasticityProductErrorV1;
use crate::plasticity_product::ParameterPlasticityProductReceiptV1;
use crate::plasticity_product::ParameterPlasticityProductRequestV1;
use crate::plasticity_product::PlasticityAnchorCommitterV1;
use crate::plasticity_product::plasticity_admission_signing_payload_v1;
use crate::plasticity_product::propose_authenticated_parameter_plasticity_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoveredParameterPlasticityProductRequestV1 {
    pub product: ParameterPlasticityProductRequestV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_attestation: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoveredParameterPlasticityProductReceiptV1 {
    pub product: ParameterPlasticityProductReceiptV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_authentication_digest: Digest32,
    pub composition_digest: Digest32,
}

#[derive(Debug)]
pub enum CoveredParameterPlasticityProductErrorV1 {
    Coverage(GeneratorCoverageErrorV1),
    Evidence(SignedEvidenceError),
    Binding(&'static str),
    Product(ParameterPlasticityProductErrorV1),
}

impl fmt::Display for CoveredParameterPlasticityProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CoveredParameterPlasticityProductErrorV1 {}
impl From<GeneratorCoverageErrorV1> for CoveredParameterPlasticityProductErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<SignedEvidenceError> for CoveredParameterPlasticityProductErrorV1 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<ParameterPlasticityProductErrorV1> for CoveredParameterPlasticityProductErrorV1 {
    fn from(value: ParameterPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}

pub fn propose_covered_parameter_plasticity_v1(
    request: CoveredParameterPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_committer: &mut impl PlasticityAnchorCommitterV1,
    now: u64,
) -> Result<CoveredParameterPlasticityProductReceiptV1, CoveredParameterPlasticityProductErrorV1>
{
    verify_generator_coverage_receipt_v1(&request.product.generator_profile, &request.coverage)?;
    if request.coverage.selected_artifact_digest
        != request.product.generated.selected_artifact_digest
        || request.coverage.window != request.product.generated.window
        || request.coverage.mutation_grammar_digest
            != request
                .product
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
        || request.coverage.owner_frontier_digest
            != request.product.admission.owner_evidence_set_digest
    {
        return Err(CoveredParameterPlasticityProductErrorV1::Binding(
            "coverage/product context",
        ));
    }

    let has_update = request
        .product
        .generated
        .candidates
        .iter()
        .any(|candidate| candidate.kind == ParameterCandidateKindV2::Update);
    match request.coverage.terminal {
        GeneratorCoverageTerminalV1::Ready => {}
        GeneratorCoverageTerminalV1::ZeroEligibleSignals
        | GeneratorCoverageTerminalV1::PolicyDisabledUpdates
            if has_update =>
        {
            return Err(CoveredParameterPlasticityProductErrorV1::Binding(
                "coverage terminal has update candidate",
            ));
        }
        GeneratorCoverageTerminalV1::ZeroEligibleSignals
        | GeneratorCoverageTerminalV1::PolicyDisabledUpdates => {}
    }

    let coverage_payload = generator_coverage_signing_payload_v1(&request.coverage);
    let coverage_observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &request.coverage_attestation,
        &coverage_payload,
        now,
    )?;
    let admission_payload = plasticity_admission_signing_payload_v1(&request.product.admission);
    let admission_observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &request.product.admission_attestation,
        &admission_payload,
        now,
    )?;
    if coverage_observer.principal() != admission_observer.principal()
        || request.coverage_attestation.objective_digest
            != request.product.admission.objective_digest
    {
        return Err(CoveredParameterPlasticityProductErrorV1::Binding(
            "coverage observer",
        ));
    }

    let coverage_authentication_digest = coverage_authentication_digest(
        &request.coverage_attestation,
        verifier.trust_digest(),
    );
    let coverage = request.coverage;
    let product = propose_authenticated_parameter_plasticity_v1(
        request.product,
        verifier,
        writer,
        anchor_committer,
        now,
    )?;
    let mut bytes = b"hepta.intelligence.plasticity-covered-composition.v1\0".to_vec();
    for digest in [
        product.composition_digest,
        coverage.coverage_digest,
        coverage_authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(CoveredParameterPlasticityProductReceiptV1 {
        product,
        coverage,
        coverage_authentication_digest,
        composition_digest: Digest32::of_bytes(&bytes),
    })
}

fn coverage_authentication_digest(
    evidence: &SignedLearningEvidenceV1,
    trust_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.plasticity-coverage-authentication.v1\0".to_vec();
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(&evidence.signing_bytes());
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}
