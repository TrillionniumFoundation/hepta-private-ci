//! Attach only the original completed reader's full E frontier to the same
//! material request. This grants no publication, selection or activation.
use super::*;
use codex_hepta_agent_components::intelligence::CandidateEvaluationAdmissionV1;
use codex_hepta_agent_components::intelligence_eval::CompletedParameterEvaluationsV1;
use codex_hepta_agent_components::intelligence_eval::ParameterEvaluationRoundBindingV1;
use std::collections::BTreeSet;

impl CpuNeuronRoundMaterialsV3 {
    pub(crate) fn install_completed_evaluations(
        self,
        completed: &CompletedParameterEvaluationsV1,
    ) -> Result<Self, AgentdError> {
        let binding = ParameterEvaluationRoundBindingV1 {
            round_identity_digest: self.round.identity_digest(),
            round_payload_digest: Digest32::of_bytes(&self.round.canonical_bytes()?),
            canonical_policy_digest: self.canonical.digest(),
            execution_envelope_digest: self_iteration_envelope_digest_v1(&self.execution),
            admitted_at_ms: self.round.admitted_at_ms(),
            deadline_ms: self.round.deadline_ms(),
        };
        completed
            .validate_parameter_binding_v1(
                &binding,
                &self.request.generator_profile,
                &self.request.admission,
                &self.request.generator_attestation,
                &self.request.admission_attestation,
            )
            .map_err(material_error)?;
        let evaluations = completed
            .evaluations()
            .iter()
            .map(
                |(bundle, metric_roles, evidence)| CandidateEvaluationAdmissionV1 {
                    bundle: bundle.clone(),
                    metric_roles: metric_roles.clone(),
                    evidence: evidence.clone(),
                },
            )
            .collect();
        self.attach_complete_evaluation_frontier(evaluations)
    }

    fn attach_complete_evaluation_frontier(
        mut self,
        evaluations: Vec<CandidateEvaluationAdmissionV1>,
    ) -> Result<Self, AgentdError> {
        let expected: BTreeSet<_> = self
            .candidates
            .iter()
            .map(|candidate| &candidate.candidate_id)
            .collect();
        let actual: BTreeSet<_> = evaluations
            .iter()
            .map(|evaluation| &evaluation.bundle.candidate_id)
            .collect();
        if expected.is_empty()
            || evaluations.len() != expected.len()
            || actual != expected
            || evaluations.iter().any(|evaluation| {
                evaluation.bundle.baseline_id != self.request.admission.baseline_id
                    || evaluation.bundle.objective_digest != self.request.admission.objective_digest
                    || evaluation.bundle.dataset_digest != self.request.admission.dataset_digest
                    || evaluation.bundle.generator.principal_id
                        != self.request.generator_attestation.principal_id
            })
            || (!self.request.evaluations.is_empty() && self.request.evaluations != evaluations)
        {
            return Err(error(
                "completed E changed the original full request frontier or lineage",
            ));
        }
        self.request.evaluations = evaluations;
        self.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
        Ok(self)
    }
}

#[cfg(test)]
#[path = "local_cpu_round_completed_evaluations_tests_v3.rs"]
mod tests;
