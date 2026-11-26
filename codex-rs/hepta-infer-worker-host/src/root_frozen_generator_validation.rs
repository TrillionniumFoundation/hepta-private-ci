//! Complete factual binding before the original isolated Generator runs.
//! Root must load materials and owner observations independently. This pure
//! projection opens no stores, reads no keys and issues no effect capability.
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::intelligence::CanonicalStageV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence_eval::inspect_unsigned_self_iteration_candidate_v1;
use codex_hepta_agentd::AgentdSelfIterationCandidateEffectsV1;
use codex_hepta_agentd::AgentdSelfIterationRoundStatusV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_agentd::self_iteration_envelope_digest_v1;
use codex_hepta_agentd::self_iteration_model_request_digest_v1;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CpuNeuronParameterAdviceContextV2;
use crate::CpuNeuronParameterMaterialPlanV2;
use crate::CpuNeuronParameterPolicyV2;
use crate::sparse_cpu_neuron_parameter_diff_v2;
use crate::validate_cpu_neuron_parameter_advice_v2;
use crate::validate_cpu_neuron_parameter_materials_v2;
use crate::validate_cpu_neuron_parameter_receipt_v2;

pub(crate) struct OriginalGeneratorMaterials<'a> {
    pub canonical: &'a CanonicalIterationEnvelopeV1,
    pub independent_policy_pin: Digest32,
    pub plan: &'a CpuNeuronParameterMaterialPlanV2<'a>,
    pub admitted: &'a ParameterPlasticityProductReceiptV1,
    pub generator_principal: &'a StableId,
    pub canary_tick: &'a NeuronTickInputV1,
    pub canary_port: &'a CanonicalPortInputV1,
}

/// A factual result for Root's immutable original execution sources, not a
/// serializable approval or a replacement for current Fleet authentication.
pub(crate) struct OriginalGeneratorFacts {
    pub payload_digest: Digest32,
    pub round_digest: Digest32,
    pub expires_at_ms: u64,
}

pub(crate) fn validate_original_generator_candidate(
    payload: &[u8],
    materials: &OriginalGeneratorMaterials<'_>,
    status: &AgentdSelfIterationRoundStatusV1,
    request: &SelfIterationModelRequestV1,
    assessment: &SelfIterationModelAssessmentV1,
    now_ms: u64,
) -> anyhow::Result<OriginalGeneratorFacts> {
    use anyhow::ensure;
    // These are the original whole material/receipt rules used by the compiler,
    // and the sole original candidate parser. Root does not reimplement them.
    validate_cpu_neuron_parameter_materials_v2(materials.plan)?;
    validate_cpu_neuron_parameter_receipt_v2(materials.plan.request, materials.admitted)?;
    let policy_owner = CpuNeuronParameterPolicyV2::new(
        materials.canonical.clone(),
        materials.independent_policy_pin,
    )?;
    policy_owner.validate_execution(materials.plan.envelope, materials.plan.request)?;
    status.to_json()?;
    request.validate(now_ms)?;
    assessment.validate(request)?;
    let candidate = inspect_unsigned_self_iteration_candidate_v1(payload, now_ms)?;
    let round = &status.round;
    let policy = materials.canonical.policy();
    let envelope = materials.plan.envelope;
    ensure!(
        candidate.canonical_envelope_bytes() == Some(materials.canonical.canonical_bytes())
            && candidate.generator_round_bytes() == Some(round.canonical_bytes()?.as_slice())
            && round.canonical_policy_digest() == materials.independent_policy_pin
            && round.execution_envelope_digest() == self_iteration_envelope_digest_v1(envelope)
            && round.candidate_admissions() == u32::from(envelope.maximum_candidates)
            && status.maximum_policy_candidates == policy.maximum_candidates
            && status.admitted_policy_candidates <= policy.maximum_candidates
            && now_ms >= status.observed_clock_ms
            && now_ms >= round.admitted_at_ms()
            && now_ms < round.deadline_ms()
            && round.deadline_ms() <= policy.expires_unix_ms
            && !status.terminal
            && status.rejected_proposal.is_none()
            && status.candidate_effects == AgentdSelfIterationCandidateEffectsV1::Started
            && status
                .frozen_digest
                .is_none_or(|digest| digest == candidate.payload_digest()),
        "candidate differs from the actual original admitted round or aggregate quota"
    );
    let request_id = round.model_request_id(SelfIterationModelRoleV1::Generator, None)?;
    ensure!(
        request.role == SelfIterationModelRoleV1::Generator
            && request.request_id == request_id
            && request.envelope_digest == round.execution_envelope_digest()
            && request.candidate_digest.is_none()
            && request.deadline_ms == round.deadline_ms()
            && request.maximum_response_bytes == 8192
            && status.generator_request_id.as_ref() == Some(&request_id)
            && status.generator_model_request_digest
                == Some(self_iteration_model_request_digest_v1(request))
            && status.generator_output.as_ref() == Some(&assessment.model_output)
            && status.generator_native_run_digest == Some(assessment.native_run_digest)
            && status.generator_output_digest
                == Some(Digest32::of_bytes(assessment.model_output.as_bytes()))
            && candidate.generator_model_request_id() == Some(&request_id)
            && candidate.generator_native_run_digest() == Some(assessment.native_run_digest)
            && candidate.generator_model_output_digest() == status.generator_output_digest,
        "candidate does not bind the exact original completed model request"
    );
    let selected = validate_cpu_neuron_parameter_advice_v2(
        CpuNeuronParameterAdviceContextV2 {
            envelope,
            original_round: Some(round),
        },
        envelope,
        materials.plan.request,
        assessment,
    )?;
    let generation = materials
        .plan
        .candidates
        .iter()
        .find(|entry| entry.candidate_id == &selected)
        .ok_or_else(|| anyhow::anyhow!("selected original material absent"))?
        .generation;
    let rollback = materials.plan.rollback;
    let tick = materials.canary_tick;
    let port = materials.canary_port;
    let update = materials
        .admitted
        .proposal
        .candidates
        .iter()
        .find(|entry| entry.candidate_id == selected)
        .ok_or_else(|| anyhow::anyhow!("selected original proposal absent"))?;
    let semantic_diff = sparse_cpu_neuron_parameter_diff_v2(
        materials.plan.baseline_native,
        &selected,
        assessment.native_run_digest,
        &update.parameter_deltas,
    )?;
    ensure!(
        tick.objective_digest == envelope.objective_digest
            && tick.body_generation == Some(generation.runtime.generation.get())
            && tick.tick_id == port.run_id
            && port.objective_digest == envelope.objective_digest
            && port.predecessor_digest == tick.ndu_snapshot_digest
            && port.stage == CanonicalStageV1::NeuralSignalCollected
            && port.budget_micros > 0
            && port.budget_micros <= 10_000_000
            && !semantic_diff.is_empty()
            && semantic_diff.len() as u64 <= envelope.maximum_diff_bytes,
        "original full sparse diff or canary input changed"
    );
    // Every field consumed by the original frozen profile is compared. The
    // complete canonical policy, round and model bytes were checked above.
    ensure!(
        candidate.envelope_id() == &envelope.envelope_id
            && candidate.candidate_id() == &selected
            && candidate.generator_id() == materials.generator_principal
            && candidate.canary_tick_id() == &tick.tick_id
            && candidate.baseline_id() == materials.plan.baseline_candidate_id
            && candidate.base_commit() == envelope.base_commit
            && candidate.base_tree() == envelope.base_tree
            && candidate.objective_digest() == envelope.objective_digest
            && candidate.grammar_digest() == envelope.grammar_digest
            && candidate.semantic_diff_digest() == Digest32::of_bytes(&semantic_diff)
            && candidate.test_plan_digest() == materials.plan.test_plan_digest
            && candidate.rollback_digest() == rollback.runtime.semantic_digest()?
            && candidate.governed_proposal_digest() == materials.admitted.proposal.proposal_digest
            && candidate.governed_anchor_digest()
                == materials.admitted.committed_registry_anchor.frame_digest
            && candidate.governed_composition_digest() == materials.admitted.composition_digest
            && candidate.canary_snapshot_digest() == port.snapshot_digest
            && candidate.canary_candidate_set_digest() == port.candidate_set_digest
            && candidate.canary_predecessor_digest() == port.predecessor_digest
            && candidate.successor_body() == generation.body.semantic_digest()?
            && candidate.rollback_body() == rollback.body.semantic_digest()?
            && candidate.successor_configuration() == generation.runtime.semantic_digest()?
            && candidate.rollback_configuration() == rollback.runtime.semantic_digest()?
            && candidate.canary_input_digest() == tick.semantic_digest()?
            && candidate.base_generation() == materials.plan.baseline_runtime.generation.get()
            && candidate.maximum_files() == u64::from(envelope.maximum_files)
            && candidate.maximum_diff_bytes() == envelope.maximum_diff_bytes
            && candidate.candidate_admissions() == u64::from(envelope.maximum_candidates)
            && candidate.maximum_parallel_sandboxes()
                == u64::from(envelope.maximum_parallel_sandboxes)
            && candidate.expires_unix_seconds() == envelope.expiry_unix_seconds
            && candidate.changed_files() == 1
            && candidate.canary_budget_micros() == port.budget_micros,
        "whole frozen candidate differs from the original protected material and owner receipt"
    );
    Ok(OriginalGeneratorFacts {
        payload_digest: candidate.payload_digest(),
        round_digest: round.identity_digest(),
        expires_at_ms: round.deadline_ms(),
    })
}
