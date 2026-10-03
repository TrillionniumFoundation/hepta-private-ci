//! Current factual preparation uses the same original Dynamic/Concrete owner stores.
use super::*;
impl ConcretePlasticityOwnerEvidenceResolverV1 {
    pub(super) fn prepare_parameter_input_current(
        &self,
        input: crate::AgentdPlasticityAdmissionInputV1,
        now: u64,
    ) -> Result<crate::AgentdPlasticityAdmissionInputV1, PlasticityOwnerEvidenceErrorV1> {
        verify_dataset_snapshot_receipt_v3(&self.dataset, now)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Stale)?;
        if now < self.artifact_observed_at
            || now >= self.artifact_expires_at
            || input.objective_digest != self.dataset.snapshot.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let artifact_id = self
            .artifact_bindings
            .get(&PlasticityOwnerEvidenceKindV1::UpdateRule)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        let manifest = self
            .artifacts
            .manifest(artifact_id)
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        if !self.artifacts.is_eligible(artifact_id)
            || manifest.kind != ArtifactKind::Policy
            || manifest.objective_digest != input.objective_digest
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let mut result = self.dynamic.prepare_parameter_input(input, now)?;
        result.dataset_digest = self.dataset.snapshot.dataset_digest;
        result.update_rule_digest = manifest.content_digest;
        Ok(result)
    }
}
impl PlasticityDynamicOwnerEvidenceResolverV1 {
    pub(super) fn prepare_parameter_input_current(
        &self,
        mut input: crate::AgentdPlasticityAdmissionInputV1,
        now: u64,
    ) -> Result<crate::AgentdPlasticityAdmissionInputV1, PlasticityOwnerEvidenceErrorV1> {
        if input.objective_digest != self.objective_digest
            || now < self.observed_at
            || now >= self.expires_at
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let (modulator_digest, _) = self.current_modulator()?;
        let (eligibility_digest, _, eligibility_values) = self.current_eligibility()?;
        let (broadcast_digest, _, _) = self.broadcast(self.broadcast_artifacts.head_digest())?;
        for signal in &mut input.generator_profile.signals {
            let binding = self
                .bindings
                .get(&(signal.layer_id.clone(), signal.parameter_id.clone()))
                .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
            let index = usize::try_from(binding.eligibility_index)
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
            signal.eligibility = q24_to_q32(
                *eligibility_values
                    .get(index)
                    .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?,
            )?;
            signal.modulator =
                weighted_modulator(&binding.modulator_weights, &self.modulator_values)?;
            signal.evidence_digest = plasticity_parameter_signal_digest_v1(
                &signal.layer_id,
                &signal.parameter_id,
                signal.eligibility,
                signal.modulator,
                signal.learning_rate,
                signal.lower_bound,
                signal.upper_bound,
                eligibility_digest,
                modulator_digest,
                broadcast_digest,
            )?;
        }
        input.modulator_digest = modulator_digest;
        input.modulator_broadcast_digest = broadcast_digest;
        input.eligibility_digest = eligibility_digest;
        input.generated =
            codex_hepta_agent_components::plasticity::generate_parameter_candidates_v3(
                input.generator_profile.clone(),
            )
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?;
        Ok(input)
    }
}
