//! Agentd final-use verification for generator coverage.
//!
//! The control.engineering coordinator supplies a deterministic coverage receipt
//! plus a separate Observer signature. Agentd replays the coverage calculation,
//! verifies that the same trusted Observer signed both the owner-frontier admission
//! and the coverage payload, then invokes the existing governed proposal host.
//! This boundary grants no selection, training, activation, promotion, release,
//! or topology-application authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::GeneratorCoverageRequestV1;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;

use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::propose_agentd_plasticity_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoveredParameterPlasticityRequestV1 {
    pub request: ParameterPlasticityProductRequestV1,
    pub coverage_request: GeneratorCoverageRequestV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_attestation: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CoveredParameterPlasticityReceiptV1 {
    pub product: ParameterPlasticityProductReceiptV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_authentication_digest: Digest32,
    pub composition_digest: Digest32,
}

#[derive(Debug)]
pub enum CoveredParameterPlasticityErrorV1 {
    Coverage(GeneratorCoverageErrorV1),
    CoverageEvidence(SignedEvidenceError),
    AdmissionEvidence(SignedEvidenceError),
    Binding(&'static str),
    Host(AgentdPlasticityHostErrorV1),
}

impl fmt::Display for CoveredParameterPlasticityErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CoveredParameterPlasticityErrorV1 {}
impl From<GeneratorCoverageErrorV1> for CoveredParameterPlasticityErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<AgentdPlasticityHostErrorV1> for CoveredParameterPlasticityErrorV1 {
    fn from(value: AgentdPlasticityHostErrorV1) -> Self {
        Self::Host(value)
    }
}

pub fn propose_agentd_covered_parameter_plasticity_v1(
    covered: CoveredParameterPlasticityRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_store: &mut AgentdPlasticityAnchorStoreV1,
    now: u64,
) -> Result<CoveredParameterPlasticityReceiptV1, CoveredParameterPlasticityErrorV1> {
    verify_generator_coverage_receipt_v1(
        &covered.request.generator_profile,
        covered.coverage_request.clone(),
        &covered.coverage,
    )?;
    if covered.coverage.disposition != GeneratorCoverageDispositionV1::Complete {
        return Err(CoveredParameterPlasticityErrorV1::Binding(
            "non-update coverage terminal entered proposal host",
        ));
    }
    if covered.coverage.selected_artifact_digest
        != covered.request.generated.selected_artifact_digest
        || covered.coverage.window != covered.request.generated.window
        || covered.coverage.mutation_grammar_digest
            != covered
                .request
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
        || covered.coverage.owner_frontier_digest
            != covered.request.admission.owner_evidence_set_digest
    {
        return Err(CoveredParameterPlasticityErrorV1::Binding(
            "coverage/admission context",
        ));
    }

    let coverage_payload = generator_coverage_signing_payload_v1(&covered.coverage);
    let coverage_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &covered.coverage_attestation,
            &coverage_payload,
            now,
        )
        .map_err(CoveredParameterPlasticityErrorV1::CoverageEvidence)?;
    let admission_payload =
        plasticity_admission_signing_payload_v1(&covered.request.admission);
    let admission_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &covered.request.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(CoveredParameterPlasticityErrorV1::AdmissionEvidence)?;
    if coverage_observer.principal() != admission_observer.principal()
        || coverage_observer.controller_id() != admission_observer.controller_id()
        || coverage_observer.trust_digest() != admission_observer.trust_digest()
        || covered.coverage_attestation.objective_digest
            != covered.request.admission.objective_digest
    {
        return Err(CoveredParameterPlasticityErrorV1::Binding(
            "coverage Observer identity/trust context",
        ));
    }

    let coverage_authentication_digest = attestation_digest(&covered.coverage_attestation);
    let product = propose_agentd_plasticity_v1(
        covered.request,
        artifacts,
        ledger,
        owner_evidence_resolver,
        owner_evidence_policy,
        verifier,
        writer,
        anchor_store,
        now,
    )?;
    let mut bytes = b"hepta.agentd.covered-parameter-plasticity.v1\0".to_vec();
    for digest in [
        product.composition_digest,
        covered.coverage.coverage_digest,
        coverage_authentication_digest,
        verifier.trust_digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(CoveredParameterPlasticityReceiptV1 {
        product,
        coverage: covered.coverage,
        coverage_authentication_digest,
        composition_digest: Digest32::of_bytes(&bytes),
    })
}

fn attestation_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}
