//! Original finite S3 signatures over actual E1 and all four published Sources.
use super::*;
use crate::evolving_agentd::installed_cycle::PreparedCandidateAdmissionV1;
use crate::initial_cpu_anchor::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_neuron::NeuronGenerationMaterialV2;

pub(super) struct Preparation<'a> {
    pub blueprint: &'a blueprint::Blueprint,
    pub publication: &'a ParameterPreRegisteredPublicationV1,
    pub material: &'a NeuronGenerationMaterialV2,
    pub registration: &'a InstalledCpuSourceV1,
    pub predecessor: Option<ParameterPreRegisteredPredecessorV1>,
    pub public: &'a Path,
    pub effects: &'a Path,
    pub round: &'a AgentdSelfIterationRoundV1,
}
impl Preparation<'_> {
    pub(super) fn select(self) -> Result<Option<PreparedCandidateAdmissionV1>> {
        let source = &self.blueprint.pre_registration_selector_template;
        let bytes = configuration::source(source, 64 * 1024)?;
        let mut configuration: ParameterPreRegisteredSelectorConfigV1 =
            serde_json::from_slice(&bytes)?;
        let route = &self.blueprint.pre_registration_selector;
        ensure!(
            configuration.selector.uid == route.uid
                && configuration.selector.gid == route.gid
                && configuration.selector_program.path == route.program.path
                && configuration.selector_program.digest == route.program.digest
                && configuration.inaccessible_paths.as_slice() == route.inaccessible_paths,
            "S3 original whole enrolled role boundary changed"
        );
        let head = &self.publication.publications[3];
        configuration.evaluation = self.publication.evaluation_sources.clone();
        configuration.current_registration = CpuProtectedSourceV1 {
            path: self.registration.path.clone(),
            digest: self.registration.digest.clone(),
        };
        configuration.head_manifest = ParameterRoleSourceV3 {
            path: head.manifest.path.clone(),
            digest: head.manifest.digest.clone(),
        };
        configuration.head_admission_digest = head.admission_digest.clone();
        configuration.head_artifact_id = head.artifact_id.clone();
        configuration.candidate_predecessor = self.predecessor;
        configuration.frozen_at_ms = self.round.admitted_at_ms();
        configuration.expires_at_ms = configuration.expires_at_ms.min(self.round.deadline_ms());
        let projected = serde_json::to_vec(&configuration)?;
        let key = Digest32::of_bytes(&projected);
        let config_source = original_facts::publish(
            self.public,
            &format!("selector-{key}.json"),
            &projected,
            64 * 1024,
        )?;
        let selection_path = self.public.join(format!("selection-{key}.json"));
        let verify = |output: &[u8]| -> std::result::Result<(), Box<dyn std::error::Error>> {
            if configuration::source(source, 64 * 1024)? != bytes {
                return Err("whole original S3 template changed during use".into());
            }
            execution::immutable(&selection_path, output, 64 * 1024)?;
            let actual = inspect_parameter_pre_registered_admission_v1(
                &config_source.path,
                config_source.digest.parse()?,
                &selection_path,
                Digest32::of_bytes(output),
            )?;
            if actual.candidate_id().as_str() != self.publication.candidate_id
                || actual.purpose() != self.publication.purpose
                || actual.round() != &self.publication.original_round
                || codex_hepta_neuron::encode_neuron_generation_material_v2(actual.material())?
                    != codex_hepta_neuron::encode_neuron_generation_material_v2(self.material)?
            {
                return Err("actual S3 differs from complete original publication/material".into());
            }
            actual.revalidate_current()?;
            Ok(())
        };
        let request = crate::ParameterRoleExecutionV1 {
            purpose: crate::ParameterRoleExecutionPurposeV1::SelectorPreRegistration,
            program: ParameterRoleSourceV3 {
                path: route.program.path.clone(),
                digest: route.program.digest.clone(),
            },
            configuration: ParameterRoleSourceV3 {
                path: config_source.path.clone(),
                digest: config_source.digest.clone(),
            },
            original_effect_digest: Digest32::of_parts(&[
                b"hepta.original.round-s3.v1\0",
                &self.round.canonical_bytes()?,
                key.as_array(),
            ]),
            uid: route.uid,
            gid: route.gid,
            inaccessible_paths: route.inaccessible_paths.clone(),
        };
        let Some(output) = crate::execute_retained_parameter_role_v1(
            &request,
            &self.effects.join(format!("selector-{key}.output")),
            verify,
        )
        .map_err(|error| anyhow::anyhow!("{error}"))?
        else {
            return Ok(None);
        };
        Ok(Some(PreparedCandidateAdmissionV1 {
            candidate_id: self.publication.candidate_id.clone(),
            configuration: config_source,
            selection: InstalledCpuSourceV1 {
                path: selection_path,
                digest: Digest32::of_bytes(&output).to_string(),
            },
        }))
    }
}
