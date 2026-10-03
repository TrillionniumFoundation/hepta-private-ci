//! Join the original pre-publication E1 materials to a freshly authenticated
//! post-publication admission. This grants no proposal, registration or use.
use super::*;
use codex_hepta_agent_components::intelligence_eval::RegisteredArtifactCurrentFactsV3;
use codex_hepta_agent_components::intelligence_eval::validate_current_parameter_admission_v1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_agent_components::learning_ledger::verify_signed_role_separation;
use codex_hepta_agent_components::plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_agent_components::plasticity::plasticity_admission_signing_payload_v1;
use codex_hepta_agent_components::plasticity::validate_parameter_admission_binding_v1;

pub(crate) struct FinalRoundParameterAdmissionV3<'a> {
    pub request: ParameterPlasticityProductRequestV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub current: &'a RegisteredArtifactCurrentFactsV3,
    /// Obtained from the same healthy Agentd proposal writer, independently
    /// of the Artifact CURRENT head and without opening another writer.
    pub proposal_registry_predecessor: Digest32,
    pub now: u64,
}

impl CpuNeuronRoundMaterialsV3 {
    pub(crate) fn install_registered_materials(
        self,
        candidates: &[codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1],
        rollback: &codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1,
        final_admission: FinalRoundParameterAdmissionV3<'_>,
    ) -> Result<Self, AgentdError> {
        // E1 must first be checked against its original pre-publication head.
        // Updating that head before this check would erase the actual lineage.
        let mut materials = self.install_evaluated_materials(candidates, rollback)?;
        final_admission
            .current
            .revalidate_current(final_admission.now)
            .map_err(material_error)?;
        validate_current_parameter_admission_v1(
            final_admission.current,
            &final_admission.request.admission,
            materials.baseline(),
        )
        .map_err(material_error)?;
        validate_final_request(
            materials.round(),
            materials.request(),
            &final_admission.request,
            final_admission.verifier,
            final_admission.proposal_registry_predecessor,
            final_admission.now,
        )?;
        materials.request = final_admission.request;
        materials.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
        final_admission
            .current
            .revalidate_current(final_admission.now)
            .map_err(material_error)?;
        Ok(materials)
    }
}

pub(super) fn validate_final_request(
    round: &AgentdSelfIterationRoundV1,
    original: &ParameterPlasticityProductRequestV1,
    actual: &ParameterPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    proposal_registry_predecessor: Digest32,
    now: u64,
) -> Result<(), AgentdError> {
    if now < round.admitted_at_ms() || now >= round.deadline_ms() {
        return Err(error("final admission crossed the original round window"));
    }
    // Only these original owner frontiers can change after publication. All
    // numerical, Dataset/NDU, policy, proposal and search identities stay exact.
    let mut stable_admission = actual.admission.clone();
    stable_admission.artifact_registry_head_digest =
        original.admission.artifact_registry_head_digest;
    stable_admission.qualification_evidence_head_digest =
        original.admission.qualification_evidence_head_digest;
    stable_admission.owner_evidence_set_digest = original.admission.owner_evidence_set_digest;
    if actual.proposal_id != original.proposal_id
        || actual.generator_profile != original.generator_profile
        || actual.generated != original.generated
        || stable_admission != original.admission
        || actual.no_change_attestation != original.no_change_attestation
        || actual.evaluations != original.evaluations
        || actual.expected_registry_predecessor != proposal_registry_predecessor
        || actual.generator_attestation.principal_id != original.generator_attestation.principal_id
        || actual.admission_attestation.principal_id != original.admission_attestation.principal_id
        || actual.generator_attestation.objective_digest != actual.admission.objective_digest
        || actual.admission_attestation.objective_digest != actual.admission.objective_digest
    {
        return Err(error(
            "post-publication request changed whole original E1 search facts",
        ));
    }
    verify_generated_parameter_candidates_v3(actual.generator_profile.clone(), &actual.generated)
        .map_err(material_error)?;
    validate_parameter_admission_binding_v1(
        &actual.generator_profile,
        &actual.generated,
        &actual.admission,
    )
    .map_err(material_error)?;
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &actual.generator_attestation,
            &parameter_generator_signing_payload_v3(&actual.generated),
            now,
        )
        .map_err(material_error)?;
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &actual.admission_attestation,
            &plasticity_admission_signing_payload_v1(&actual.admission),
            now,
        )
        .map_err(material_error)?;
    verify_signed_role_separation(&generator, &observer, now).map_err(material_error)?;
    Ok(())
}
