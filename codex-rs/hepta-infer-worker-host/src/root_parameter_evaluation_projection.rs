//! Sole bounded Source/role slot projection for the original raw preparation.
use super::*;
use crate::ParameterRoleExecutionPurposeV1 as Purpose;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;

pub(super) struct Pipeline<'a> {
    pub template: &'a OriginalParameterEvaluationTemplateV1,
    pub directory: PathBuf,
    pub round: AgentdSelfIterationRoundV1,
}
fn boxed(error: impl std::fmt::Display) -> anyhow::Error {
    anyhow::anyhow!("{error}")
}
pub(super) fn read(source: &ParameterRoleSourceV3, maximum: u64) -> Result<Vec<u8>> {
    let bytes = read_root_review_input(&source.path, maximum).map_err(boxed)?;
    ensure!(
        Digest32::of_bytes(&bytes).to_string() == source.digest,
        "whole original native template/source changed"
    );
    Ok(bytes)
}
pub(super) fn as_role(source: &InstalledCpuSourceV1) -> ParameterRoleSourceV3 {
    ParameterRoleSourceV3 {
        path: source.path.clone(),
        digest: source.digest.clone(),
    }
}
pub(super) fn as_cpu(source: &InstalledCpuSourceV1) -> CpuProtectedSourceV1 {
    CpuProtectedSourceV1 {
        path: source.path.clone(),
        digest: source.digest.clone(),
    }
}
pub(super) fn round_binding(
    round: &AgentdSelfIterationRoundV1,
) -> Result<ParameterEvaluationRoundBindingV1> {
    Ok(ParameterEvaluationRoundBindingV1 {
        round_identity_digest: round.identity_digest(),
        round_payload_digest: Digest32::of_bytes(&round.canonical_bytes()?),
        canonical_policy_digest: round.canonical_policy_digest(),
        execution_envelope_digest: round.execution_envelope_digest(),
        admitted_at_ms: round.admitted_at_ms(),
        deadline_ms: round.deadline_ms(),
    })
}
pub(super) fn pre_round(
    round: &AgentdSelfIterationRoundV1,
) -> Result<ParameterPreRegistrationRoundV1> {
    let binding = round_binding(round)?;
    Ok(ParameterPreRegistrationRoundV1 {
        round_digest: binding.round_identity_digest.to_string(),
        round_payload_digest: binding.round_payload_digest.to_string(),
        canonical_policy_digest: binding.canonical_policy_digest.to_string(),
        execution_digest: binding.execution_envelope_digest.to_string(),
        admitted_at_ms: binding.admitted_at_ms,
        deadline_ms: binding.deadline_ms,
    })
}
pub(super) fn validate_terminal(
    round: &AgentdSelfIterationRoundV1,
    facts: &SelfIterationPreparationFactsV1,
) -> Result<()> {
    let binding = round_binding(round)?;
    ensure!(
        facts.round_identity_digest == binding.round_identity_digest
            && facts.round_payload_digest == binding.round_payload_digest
            && facts.canonical_policy_digest == binding.canonical_policy_digest
            && facts.execution_envelope_digest == binding.execution_envelope_digest
            && facts.admitted_at_ms == binding.admitted_at_ms
            && facts.deadline_ms == binding.deadline_ms,
        "actual E preparation belongs to another original Round"
    );
    Ok(())
}
pub(super) fn current(
    source: &InstalledCpuSourceV1,
    material: &codex_hepta_neuron::NeuronGenerationMaterialV2,
    subject: &StableId,
) -> Result<RegisteredArtifactCurrentFactsV3> {
    inspect_registered_artifact_current_material_v3(
        &source.path,
        source.digest.parse()?,
        material,
        subject,
        now_ms()?,
    )
    .map_err(boxed)
}
impl Pipeline<'_> {
    pub fn validate_time(&self, trust: &ActivatedLearningTrustV1) -> Result<()> {
        let now = now_ms()?;
        ensure!(
            now >= self.round.admitted_at_ms() && now < self.round.deadline_ms(),
            "original preparation window expired"
        );
        trust.revalidate_at(now).map_err(boxed)
    }
    fn name(&self, label: &str) -> String {
        Digest32::of_parts(&[
            b"hepta.original.raw-preparation.source.v1\0",
            self.round.identity_digest().as_array(),
            label.as_bytes(),
        ])
        .to_string()
    }
    pub fn publish(&self, label: &str, bytes: &[u8]) -> Result<InstalledCpuSourceV1> {
        independent_owners::roles::publish_public_source(
            &self.template.public_source_directory,
            &self.name(label),
            bytes,
            128 * 1024 * 1024,
        )
    }
    pub fn existing(&self, label: &str) -> Result<Option<InstalledCpuSourceV1>> {
        let path = self.template.public_source_directory.join(self.name(label));
        if !path.try_exists()? {
            return Ok(None);
        }
        let bytes = read_root_review_input(&path, 128 * 1024 * 1024).map_err(boxed)?;
        Ok(Some(InstalledCpuSourceV1 {
            path,
            digest: Digest32::of_bytes(&bytes).to_string(),
        }))
    }
    pub fn execute(
        &self,
        label: &str,
        program: &OriginalParameterRoleProgramV1,
        configuration: &InstalledCpuSourceV1,
        purpose: Purpose,
    ) -> Result<Option<Vec<u8>>> {
        let effect = Digest32::of_parts(&[
            b"hepta.original.raw-preparation.effect.v1\0",
            &self.round.canonical_bytes()?,
            label.as_bytes(),
            configuration.digest.as_bytes(),
            program.program.digest.as_bytes(),
            &program.uid.to_be_bytes(),
            &program.gid.to_be_bytes(),
        ]);
        let request = crate::ParameterRoleExecutionV1 {
            purpose,
            program: program.program.clone(),
            configuration: as_role(configuration),
            uid: program.uid,
            gid: program.gid,
            original_effect_digest: effect,
            inaccessible_paths: program.inaccessible_paths.clone(),
        };
        crate::execute_retained_parameter_role_v1(
            &request,
            &self.directory.join(format!("{}.output", self.name(label))),
            |bytes| {
                // The native fixed purpose owns scientific/signature checks. Root
                // later replays full original output, never promotes this JSON check.
                let _: serde_json::Value = serde_json::from_slice(bytes)?;
                if bytes.len() > 128 * 1024 * 1024 {
                    return Err("whole finite native output bound".into());
                }
                read(&request.configuration, 64 * 1024)
                    .map_err(|e| -> Box<dyn std::error::Error> { format!("{e}").into() })?;
                Ok(())
            },
        )
        .map_err(boxed)
    }
    pub fn preparation(&self, inputs: &[u8], measured: bool) -> Result<Option<Vec<u8>>> {
        let input = self.publish("terminal-inputs", inputs)?;
        let mut config: FixedParameterEvaluatorConfigV1 = serde_json::from_slice(&read(
            &self.template.evaluator_preparation_configuration,
            32 * 1024,
        )?)?;
        config.schema = if measured {
            "hepta.fixed-parameter-preparation-config.v1"
        } else {
            "hepta.fixed-parameter-no-change-config.v1"
        }
        .into();
        config.inputs_path = input.path;
        config.inputs_digest = input.digest;
        let configuration = self.publish(
            "terminal-config",
            &encode_fixed_parameter_evaluator_config_v1(&config).map_err(boxed)?,
        )?;
        self.execute(
            "terminal",
            &self.template.evaluator,
            &configuration,
            if measured {
                Purpose::EvaluatorPreparation
            } else {
                Purpose::EvaluatorNoChange
            },
        )
    }
    pub fn terminal(
        &self,
        output: &serde_json::Value,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<OriginalParameterEvaluationPreparationResultV1> {
        let hex = output["preparation_terminal_hex"]
            .as_str()
            .context("actual signed preparation terminal absent")?;
        ensure!(
            hex.len() <= 2 * MAX_SELF_ITERATION_PREPARATION_TERMINAL_BYTES_V1,
            "whole original preparation terminal hex bound"
        );
        let bytes = decode_review_payload_hex(hex).map_err(boxed)?;
        self.terminal_bytes(&bytes, trust)
    }
    pub fn terminal_bytes(
        &self,
        bytes: &[u8],
        trust: &ActivatedLearningTrustV1,
    ) -> Result<OriginalParameterEvaluationPreparationResultV1> {
        let (facts, evidence) =
            decode_self_iteration_preparation_terminal_v1(bytes).map_err(boxed)?;
        validate_terminal(&self.round, &facts)?;
        let now = now_ms()?;
        trust.revalidate_at(now).map_err(boxed)?;
        trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence,
                &self_iteration_preparation_terminal_signing_payload_v1(&facts).map_err(boxed)?,
                now,
            )
            .map_err(boxed)?;
        Ok(OriginalParameterEvaluationPreparationResultV1::Terminal {
            source: self.publish("preparation-terminal", bytes)?,
        })
    }
    pub fn e1(
        &self,
        materials: &crate::CpuNeuronRoundMaterialsV3,
        candidate: &StableId,
        prospective: &codex_hepta_neuron::NeuronGenerationMaterialV2,
        purpose: ParameterPreRegistrationPurposeV1,
        subject: &StableId,
    ) -> Result<
        Option<(
            VerifiedParameterPreRegistrationEvaluationV1,
            ParameterPreRegistrationEvaluationSourcesV1,
        )>,
    > {
        let label = format!("e1-{purpose:?}-{candidate}");
        let template = match purpose {
            ParameterPreRegistrationPurposeV1::Candidate => {
                &self.template.candidate_evaluation_configuration
            }
            ParameterPreRegistrationPurposeV1::ExactRollback => {
                &self.template.rollback_evaluation_configuration
            }
        };
        let mut config: FixedParameterPreRegistrationConfigV1 =
            serde_json::from_slice(&read(template, 64 * 1024)?)?;
        let request = materials.request();
        let profile = self.publish("parameter-profile", &codex_hepta_agent_components::plasticity::encode_untrusted_parameter_generator_profile_v3(&request.generator_profile).map_err(boxed)?)?;
        let admission = self.publish(
            "parameter-admission",
            &codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1(
                &request.admission,
            )
            .map_err(boxed)?,
        )?;
        config.round = pre_round(&self.round)?;
        config.subject = subject.to_string();
        config.candidate_id = candidate.to_string();
        config.purpose = purpose;
        config.profile = as_role(&profile);
        config.admission = as_role(&admission);
        config.generator_evidence =
            ReviewEvidenceWireV1::from_native(&request.generator_attestation);
        config.observer_evidence =
            ReviewEvidenceWireV1::from_native(&request.admission_attestation);
        config.prospective_material = as_role(&self.publish(
            &format!("{label}-prospective"),
            &encode_neuron_generation_material_v2(prospective).map_err(boxed)?,
        )?);
        ensure!(
            config.baseline_material.digest.parse::<Digest32>()?
                == Digest32::of_bytes(
                    &encode_neuron_generation_material_v2(materials.baseline()).map_err(boxed)?
                ),
            "original E1 template baseline differs from actual original material"
        );
        let configuration =
            self.publish(&format!("{label}-config"), &serde_json::to_vec(&config)?)?;
        let Some(output) = self.execute(
            &label,
            &self.template.evaluator,
            &configuration,
            Purpose::EvaluatorPreRegistration,
        )?
        else {
            return Ok(None);
        };
        let report = self.publish(&format!("{label}-report"), &output)?;
        let verified = inspect_parameter_pre_registration_history_v1(
            &configuration.path,
            configuration.digest.parse()?,
            &report.path,
            report.digest.parse()?,
        )
        .map_err(boxed)?;
        ensure!(
            verified.round() == &pre_round(&self.round)?
                && verified.purpose() == purpose
                && verified.candidate_id() == candidate
                && verified.subject() == subject,
            "full actual E1 round/purpose/subject changed"
        );
        Ok(Some((
            verified,
            ParameterPreRegistrationEvaluationSourcesV1 {
                configuration: as_cpu(&configuration),
                report: as_cpu(&report),
            },
        )))
    }
    pub fn publish_e1(
        &self,
        evaluation: &(
            VerifiedParameterPreRegistrationEvaluationV1,
            ParameterPreRegistrationEvaluationSourcesV1,
        ),
        predecessor: Option<ParameterPreRegisteredPredecessorV1>,
    ) -> Result<Option<(ParameterPreRegisteredPublicationV1, InstalledCpuSourceV1)>> {
        let label = format!(
            "publication-{:?}-{}",
            evaluation.0.purpose(),
            evaluation.0.candidate_id()
        );
        let configuration = if let Some(original) = self.existing(&format!("{label}-config"))? {
            let prior: ParameterPreRegistrationPublicationConfigV1 =
                serde_json::from_slice(&read(&as_role(&original), 64 * 1024)?)?;
            ensure!(
                serde_json::to_vec(&prior.evaluation)? == serde_json::to_vec(&evaluation.1)?
                    && prior
                        .candidate_predecessor
                        .as_ref()
                        .map(|p| &p.head_artifact_id)
                        == predecessor.as_ref().map(|p| &p.head_artifact_id),
                "immutable original publication configuration identity changed"
            );
            original
        } else {
            let mut config: ParameterPreRegistrationPublicationConfigV1 = serde_json::from_slice(
                &read(&self.template.publication_configuration, 64 * 1024)?,
            )?;
            config.evaluation = evaluation.1.clone();
            config.candidate_predecessor = predecessor;
            self.publish(&format!("{label}-config"), &serde_json::to_vec(&config)?)?
        };
        // Read complete historical facts first. Partial/unknown never repairs or
        // redispatches; the original consumed slot also refuses reissue.
        if let Some(original) = observe_parameter_pre_registered_artifacts_v1(
            &configuration.path,
            configuration.digest.parse()?,
        )
        .map_err(boxed)?
        {
            return Ok(Some((original, configuration)));
        }
        let Some(output) = self.execute(
            &label,
            &self.template.publisher,
            &configuration,
            Purpose::ArtifactPreRegistrationPublication,
        )?
        else {
            return Ok(None);
        };
        let returned: ParameterPreRegisteredPublicationV1 = serde_json::from_slice(&output)?;
        let original = observe_parameter_pre_registered_artifacts_v1(
            &configuration.path,
            configuration.digest.parse()?,
        )
        .map_err(boxed)?
        .context("actual publisher terminal lacks complete original four-set")?;
        ensure!(
            serde_json::to_vec(&returned)? == serde_json::to_vec(&original)?,
            "publisher output differs from actual original completion"
        );
        Ok(Some((original, configuration)))
    }
}
