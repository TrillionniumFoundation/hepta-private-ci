//! Owner-clock final use over the existing host frontiers and writer.
use super::*;
use codex_hepta_agent_components::intelligence::propose_authenticated_parameter_plasticity_with_final_time_v1;
use std::cell::Cell;

pub(crate) fn propose_agentd_plasticity_with_clock_v1(
    mut request: ParameterPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredPlasticityWriterV1,
    anchor_store: &mut AgentdPlasticityAnchorStoreV1,
    now: u64,
    clock: &mut dyn FnMut() -> Result<u64, crate::AgentdError>,
) -> Result<ParameterPlasticityProductReceiptV1, AgentdPlasticityHostErrorV1> {
    let receipt_windows = ReceiptWindowResolverV1 {
        inner: owner_evidence_resolver,
        observed_at: Cell::new(0),
        expires_at: Cell::new(u64::MAX),
    };
    let resolved = resolve_admission_at_observed_head(
        &AgentdPlasticityAdmissionInputV1 {
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            generator_profile: request.generator_profile.clone(),
            generated: request.generated.clone(),
            baseline_generation: request.admission.baseline_generation,
            candidate_generation: request.admission.candidate_generation,
            dataset_digest: request.admission.dataset_digest,
            update_rule_digest: request.admission.update_rule_digest,
            modulator_digest: request.admission.modulator_digest,
            modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
            eligibility_digest: request.admission.eligibility_digest,
        },
        artifacts,
        ledger,
        &receipt_windows,
        owner_evidence_policy,
        Some(request.admission.qualification_evidence_head_digest),
        now,
    )?;
    if resolved != request.admission {
        return Err(AgentdPlasticityHostErrorV1::AdmissionDrift);
    }
    request.admission = resolved;
    propose_authenticated_parameter_plasticity_with_final_time_v1(
        request,
        verifier,
        writer,
        anchor_store,
        now,
        &mut || {
            let final_now = clock().map_err(|_| {
                ParameterPlasticityProductErrorV1::Binding("host clock unavailable")
            })?;
            if final_now < receipt_windows.observed_at.get()
                || final_now > receipt_windows.expires_at.get()
            {
                return Err(ParameterPlasticityProductErrorV1::Binding(
                    "owner evidence expired before append",
                ));
            }
            Ok(final_now)
        },
    )
    .map_err(Into::into)
}

// Admission validates each returned receipt before the aggregated window can
// reach the append guard. This wrapper retains no new evidence or authority.
struct ReceiptWindowResolverV1<'a> {
    inner: &'a dyn PlasticityOwnerEvidenceResolverV1,
    observed_at: Cell<u64>,
    expires_at: Cell<u64>,
}

impl PlasticityOwnerEvidenceResolverV1 for ReceiptWindowResolverV1<'_> {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let receipt = self.inner.resolve(query)?;
        self.observed_at
            .set(self.observed_at.get().max(receipt.observed_at));
        self.expires_at
            .set(self.expires_at.get().min(receipt.expires_at));
        Ok(receipt)
    }
    fn resolve_with_ledger(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
        current: &codex_hepta_agent_components::learning_ledger::LedgerSnapshot,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        let receipt = self.inner.resolve_with_ledger(query, current)?;
        self.observed_at
            .set(self.observed_at.get().max(receipt.observed_at));
        self.expires_at
            .set(self.expires_at.get().min(receipt.expires_at));
        Ok(receipt)
    }
    fn qualification_head(
        &self,
        current: &codex_hepta_agent_components::learning_ledger::LedgerSnapshot,
        expected: Option<Digest32>,
        now: u64,
    ) -> Result<Digest32, PlasticityOwnerEvidenceErrorV1> {
        self.inner.qualification_head(current, expected, now)
    }
}

/// Read-only recovery reuses the original frontier/owner-evidence validation.
/// An absent committed row stays unknown; this function never calls propose.
#[allow(clippy::too_many_arguments)]
pub(crate) fn observe_completed_agentd_plasticity_with_clock_v1(
    request: &ParameterPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    owner_evidence_resolver: &dyn PlasticityOwnerEvidenceResolverV1,
    owner_evidence_policy: &PlasticityOwnerEvidencePolicyV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &AnchoredPlasticityWriterV1,
    anchor_store: &AgentdPlasticityAnchorStoreV1,
    now: u64,
    clock: &mut dyn FnMut() -> Result<u64, crate::AgentdError>,
) -> Result<Option<ParameterPlasticityProductReceiptV1>, AgentdPlasticityHostErrorV1> {
    let receipt_windows = ReceiptWindowResolverV1 {
        inner: owner_evidence_resolver,
        observed_at: Cell::new(0),
        expires_at: Cell::new(u64::MAX),
    };
    let resolved = resolve_admission_at_observed_head(
        &AgentdPlasticityAdmissionInputV1 {
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            generator_profile: request.generator_profile.clone(),
            generated: request.generated.clone(),
            baseline_generation: request.admission.baseline_generation,
            candidate_generation: request.admission.candidate_generation,
            dataset_digest: request.admission.dataset_digest,
            update_rule_digest: request.admission.update_rule_digest,
            modulator_digest: request.admission.modulator_digest,
            modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
            eligibility_digest: request.admission.eligibility_digest,
        },
        artifacts,
        ledger,
        &receipt_windows,
        owner_evidence_policy,
        Some(request.admission.qualification_evidence_head_digest),
        now,
    )?;
    if resolved != request.admission {
        return Err(AgentdPlasticityHostErrorV1::AdmissionDrift);
    }
    let final_now = clock()
        .map_err(|_| ParameterPlasticityProductErrorV1::Binding("host clock unavailable"))?;
    if final_now < now
        || final_now < receipt_windows.observed_at.get()
        || final_now > receipt_windows.expires_at.get()
    {
        return Err(ParameterPlasticityProductErrorV1::Binding(
            "owner evidence expired before completed observation",
        )
        .into());
    }
    writer
        .observe_completed_parameter_v1(request, verifier, final_now, anchor_store.anchor())
        .map_err(Into::into)
}
