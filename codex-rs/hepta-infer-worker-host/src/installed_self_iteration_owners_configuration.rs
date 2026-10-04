//! Public protected routing and original whole-material identities.
use super::*;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InstalledSelfIterationIndependentOwnersConfigV1 {
    pub schema: String,
    pub route: InstalledCpuSourceV1,
    pub learning_trust: InstalledCpuSourceV1,
    pub round_digest: String,
    pub canonical_policy_digest: String,
    pub execution_digest: String,
    pub materials_digest: String,
    pub generator: String,
    pub evaluator: String,
    pub selector: String,
    pub selector_uid: u32,
    pub observer: String,
}
pub(super) type Configuration = InstalledSelfIterationIndependentOwnersConfigV1;
impl Configuration {
    pub(super) fn validate(
        &self,
        round: &AgentdSelfIterationRoundV1,
        materials: &CpuNeuronParameterRootMaterialsV2,
        current: u64,
    ) -> Result<(), AgentdError> {
        if self.schema != "hepta.installed-self-iteration-independent-owners.v1"
            || self.round_digest != round.identity_digest().to_string()
            || self.canonical_policy_digest != round.canonical_policy_digest().to_string()
            || self.canonical_policy_digest != materials.canonical_envelope().digest().to_string()
            || self.execution_digest != round.execution_envelope_digest().to_string()
            || self.execution_digest
                != codex_hepta_agentd::self_iteration_envelope_digest_v1(
                    materials.execution_envelope(),
                )
                .to_string()
            || self.materials_digest
                != self_iteration_independent_owner_materials_digest_v1(materials)?.to_string()
            || current < round.admitted_at_ms()
            || current >= round.deadline_ms()
        {
            return Err(protocol(
                "installed independent owner original round/material policy",
            ));
        }
        let identities = [
            &self.generator,
            &self.evaluator,
            &self.selector,
            &self.observer,
        ];
        for (index, id) in identities.iter().enumerate() {
            StableId::new(id.as_str()).map_err(protocol)?;
            if identities[..index].contains(id) {
                return Err(protocol("independent owner principal repeated"));
            }
        }
        Ok(())
    }
    pub(super) fn validate_roster(
        &self,
        trust: &ActivatedLearningTrustV1,
        current: u64,
    ) -> Result<(), AgentdError> {
        trust.revalidate_at(current).map_err(protocol)?;
        let wire: ReviewTrustWireV1 =
            serde_json::from_slice(&read_source(&self.learning_trust, 64 * 1024)?)?;
        let (_, distribution) = wire.native().map_err(protocol)?;
        let mut owners: Vec<TrustedLearningSignerV1> = Vec::new();
        for (id, role) in [
            (&self.generator, LearningEvidenceRoleV1::Generator),
            (&self.evaluator, LearningEvidenceRoleV1::Evaluator),
            (&self.selector, LearningEvidenceRoleV1::Selector),
            (&self.observer, LearningEvidenceRoleV1::Observer),
        ] {
            let owner = distribution
                .distribution
                .trust
                .signers
                .iter()
                .find(|owner| {
                    owner.principal.principal_id.as_str() == id && owner.roles.contains(&role)
                })
                .ok_or_else(|| protocol("independent original roster purpose missing"))?;
            owner.principal.validate(current).map_err(protocol)?;
            if owner.revoked_at.is_some_and(|at| current >= at) {
                return Err(protocol("original independent owner revoked"));
            }
            for previous in &owners {
                let previous: &TrustedLearningSignerV1 = previous;
                verify_independent_roles(&owner.principal, &previous.principal, current)
                    .map_err(protocol)?;
                if owner.controller_id == previous.controller_id {
                    return Err(protocol("independent owner controllers repeated"));
                }
            }
            owners.push(owner.clone());
        }
        Ok(())
    }
}
pub(super) struct CandidateBinding {
    pub id: String,
    pub base_generation: u64,
    pub successor_configuration: Digest32,
    pub successor_body: Digest32,
    pub rollback_configuration: Digest32,
    pub rollback_body: Digest32,
}
pub(super) fn candidate_bindings(
    materials: &CpuNeuronParameterRootMaterialsV2,
) -> Result<Vec<CandidateBinding>, AgentdError> {
    materials.with_plan(|plan| {
        plan.candidates
            .iter()
            .map(|candidate| {
                let rollback = materials.rollback_for_candidate(candidate.candidate_id)?;
                Ok(CandidateBinding {
                    id: candidate.candidate_id.to_string(),
                    base_generation: plan.baseline_runtime.generation.get(),
                    successor_configuration: candidate
                        .generation
                        .runtime
                        .semantic_digest()
                        .map_err(protocol)?,
                    successor_body: candidate
                        .generation
                        .body
                        .semantic_digest()
                        .map_err(protocol)?,
                    rollback_configuration: rollback.runtime.semantic_digest().map_err(protocol)?,
                    rollback_body: rollback.body.semantic_digest().map_err(protocol)?,
                })
            })
            .collect()
    })
}
/// Hash every original encoded request/generation/canary under one fixed
/// purpose. This is a factual pin, never an Artifact or physical admission.
pub fn self_iteration_independent_owner_materials_digest_v1(
    materials: &CpuNeuronParameterRootMaterialsV2,
) -> Result<Digest32, AgentdError> {
    use codex_hepta_agent_components::intelligence::*;
    materials.validate_rollback_pairs()?;
    let mut bytes = b"hepta.installed-independent-owner-materials.v1\0".to_vec();
    bytes.extend_from_slice(materials.canonical_envelope().digest().as_array());
    bytes.extend_from_slice(
        codex_hepta_agentd::self_iteration_envelope_digest_v1(materials.execution_envelope())
            .as_array(),
    );
    let request = encode_parameter_plasticity_request_v1(materials.request()).map_err(protocol)?;
    bytes.extend_from_slice(Digest32::of_bytes(&request).as_array());
    for material in [materials.baseline(), materials.rollback()] {
        bytes.extend_from_slice(
            Digest32::of_bytes(
                &codex_hepta_neuron::encode_neuron_generation_material_v2(material)
                    .map_err(protocol)?,
            )
            .as_array(),
        );
    }
    materials.with_plan(|plan| -> Result<(), AgentdError> {
        bytes.extend_from_slice(
            Digest32::of_bytes(plan.baseline_candidate_id.as_str().as_bytes()).as_array(),
        );
        bytes.extend_from_slice(plan.test_plan_digest.as_array());
        bytes.extend_from_slice(&(plan.candidates.len() as u64).to_be_bytes());
        for candidate in plan.candidates {
            bytes.extend_from_slice(
                Digest32::of_bytes(candidate.candidate_id.as_str().as_bytes()).as_array(),
            );
            bytes.extend_from_slice(
                Digest32::of_bytes(
                    &codex_hepta_neuron::encode_neuron_generation_material_v2(candidate.generation)
                        .map_err(protocol)?,
                )
                .as_array(),
            );
            let (tick, port) = materials
                .candidate_canary(candidate.candidate_id)
                .ok_or_else(|| protocol("full candidate canary absent"))?;
            bytes.extend_from_slice(
                Digest32::of_bytes(
                    &codex_hepta_neuron::encode_neuron_tick_input_v1(tick).map_err(protocol)?,
                )
                .as_array(),
            );
            bytes.extend_from_slice(
                Digest32::of_bytes(
                    &encode_canonical_port_input_material_v1(port).map_err(protocol)?,
                )
                .as_array(),
            );
        }
        if plan.candidates.len() > 1 {
            bytes.extend_from_slice(b"hepta.installed-independent-owner-rollback-pairs.v2\0");
            for candidate in plan.candidates {
                let rollback = materials.rollback_for_candidate(candidate.candidate_id)?;
                bytes.extend_from_slice(
                    Digest32::of_bytes(candidate.candidate_id.as_str().as_bytes()).as_array(),
                );
                bytes.extend_from_slice(
                    Digest32::of_bytes(
                        &codex_hepta_neuron::encode_neuron_generation_material_v2(rollback)
                            .map_err(protocol)?,
                    )
                    .as_array(),
                );
            }
        }
        Ok(())
    })?;
    bytes.extend_from_slice(
        materials
            .worker_source()
            .digest
            .parse::<Digest32>()
            .map_err(protocol)?
            .as_array(),
    );
    Ok(Digest32::of_bytes(&bytes))
}
pub(super) fn read_source(
    source: &InstalledCpuSourceV1,
    maximum: u64,
) -> Result<Vec<u8>, AgentdError> {
    let pin: Digest32 = source.digest.parse().map_err(protocol)?;
    if pin.is_zero() || pin.to_string() != source.digest {
        return Err(protocol("nonzero original owner Source pin"));
    }
    let bytes = read_root_review_input(&source.path, maximum).map_err(protocol)?;
    if Digest32::of_bytes(&bytes) != pin {
        return Err(protocol("whole independent owner Source pin changed"));
    }
    Ok(bytes)
}
pub(super) fn now() -> Result<u64, AgentdError> {
    u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(protocol)?
            .as_millis(),
    )
    .map_err(protocol)
}
