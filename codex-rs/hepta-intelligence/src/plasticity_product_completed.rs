//! Completed-only observation over the original writer and governed preparation.
use super::*;
use codex_hepta_plasticity::DurableCompletedProposalV1;

impl AnchoredPlasticityWriterV1 {
    /// Whole existing row plus original append receipt, covered by the independently
    /// acknowledged current head. No absence or raw decoded value grants authority.
    pub fn observe_completed_proposal_v1(
        &self,
        proposal_id: &StableId,
        acknowledged_head: Option<DurableRegistryAnchorV1>,
    ) -> Result<Option<DurableCompletedProposalV1>, DurableProposalRegistryError> {
        if self.state != PlasticityWriterStateV1::Healthy {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        self.registry
            .observe_completed_v1(proposal_id, acknowledged_head)
    }

    /// Recover a receipt only for an exact already committed governed request.
    /// The original signatures and eligibility are rechecked at current use.
    /// This never proposes, appends, acknowledges, or installs anything.
    pub fn observe_completed_parameter_v1(
        &self,
        request: &ParameterPlasticityProductRequestV1,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        acknowledged_head: Option<DurableRegistryAnchorV1>,
    ) -> Result<Option<ParameterPlasticityProductReceiptV1>, ParameterPlasticityProductErrorV1>
    {
        let Some(observation) =
            self.observe_completed_proposal_v1(&request.proposal_id, acknowledged_head)?
        else {
            return Ok(None);
        };
        materialize_completed_parameter_receipt_v1(request, &observation, verifier, now).map(Some)
    }
}

/// Reconstruct the complete original governed receipt from an exact whole row.
/// The caller must authenticate the original writer/independent acknowledged
/// head; raw decoded bytes alone never establish custody or execution authority.
/// This pure function reuses the original governed preparation and composition.
pub fn materialize_completed_parameter_receipt_v1(
    request: &ParameterPlasticityProductRequestV1,
    observation: &DurableCompletedProposalV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<ParameterPlasticityProductReceiptV1, ParameterPlasticityProductErrorV1> {
    observation.to_bytes()?;
    let prepared = prepared::prepare(request, verifier, now)?;
    if prepared.proposal != observation.proposal
        || request.expected_registry_predecessor != observation.receipt.predecessor_frame_digest
    {
        return Err(ParameterPlasticityProductErrorV1::Binding(
            "completed proposal request",
        ));
    }
    // Later acknowledged rows cannot replace this original row's receipt.
    let committed = DurableRegistryAnchorV1 {
        sequence: observation.receipt.sequence,
        frame_digest: observation.receipt.frame_digest,
    };
    Ok(prepared::receipt(
        observation.proposal.clone(),
        observation.receipt.clone(),
        request.generated.generator_digest,
        prepared.generator_authentication_digest,
        prepared.admission_authentication_digest,
        prepared.evaluation_digest,
        prepared.disposition,
        committed,
    ))
}
