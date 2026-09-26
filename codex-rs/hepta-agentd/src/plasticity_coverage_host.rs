//! Agentd final-use host for Observer-signed generator coverage.
//!
//! The long-lived runtime owner recomputes current artifact, ledger and owner
//! evidence frontiers before the covered product adapter runs. The wrapper owns no
//! writer and grants no selection, installation or topology-application authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::AnchoredPlasticityWriterV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductErrorV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::propose_covered_parameter_plasticity_v1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::AgentdPlasticityAdmissionInputV1;
use crate::AgentdPlasticityAnchorStoreV1;
use crate::AgentdPlasticityHostErrorV1;
use crate::PlasticityOwnerEvidencePolicyV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::resolve_agentd_plasticity_admission_v1;

#[derive(Debug)]
pub enum AgentdCoveredPlasticityHostErrorV1 {
    Admission(AgentdPlasticityHostErrorV1),
    Product(CoveredParameterPlasticityProductErrorV1),
}

impl fmt::Display for AgentdCoveredPlasticityHostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdCoveredPlasticityHostErrorV1 {}
impl From<AgentdPlasticityHostErrorV1> for AgentdCoveredPlasticityHostErrorV1 {
    fn from(value: AgentdPlasticityHostErrorV1) -> Self {
        Self::Admission(value)
    }
}
impl From<CoveredParameterPlasticityProductErrorV1> for AgentdCoveredPlasticityHostErrorV1 {
    fn from(value: CoveredParameterPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn propose_agentd_covered_plasticity_v1(
    mut request: CoveredParameterPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_store: &mut AgentdPlasticityAnchorStoreV1,
    now: u64,
) -> Result<CoveredParameterPlasticityProductReceiptV1, AgentdCoveredPlasticityHostErrorV1> {
    let product = &request.product;
    let resolved = resolve_agentd_plasticity_admission_v1(
        &AgentdPlasticityAdmissionInputV1 {
            baseline_id: product.admission.baseline_id.clone(),
            objective_digest: product.admission.objective_digest,
            generator_profile: product.generator_profile.clone(),
            generated: product.generated.clone(),
            baseline_generation: product.admission.baseline_generation,
            candidate_generation: product.admission.candidate_generation,
            dataset_digest: product.admission.dataset_digest,
            update_rule_digest: product.admission.update_rule_digest,
            modulator_digest: product.admission.modulator_digest,
            modulator_broadcast_digest: product.admission.modulator_broadcast_digest,
            eligibility_digest: product.admission.eligibility_digest,
        },
        artifacts,
        ledger,
        owner_evidence_resolver,
        owner_evidence_policy,
        now,
    )?;
    if resolved != request.product.admission
        || request.coverage.owner_frontier_digest != resolved.owner_evidence_set_digest
    {
        return Err(AgentdPlasticityHostErrorV1::AdmissionDrift.into());
    }
    request.product.admission = resolved;
    propose_covered_parameter_plasticity_v1(request, verifier, writer, anchor_store, now)
        .map_err(Into::into)
}
