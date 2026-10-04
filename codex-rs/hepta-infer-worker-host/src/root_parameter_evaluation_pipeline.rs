//! Actual finite raw E and pre-registration composition over original purpose
//! slots. The authenticated Root caller owns admission and each immutable Source.
//! Unknown consumed slots remain pending; this helper never allocates a journal.
use super::*;
use crate::initial_cpu_anchor::*;
use codex_hepta_agent_components::intelligence::CandidateEvaluationAdmissionV1;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

#[path = "root_parameter_evaluation_measurement.rs"]
mod measurement;
#[path = "root_parameter_evaluation_projection.rs"]
mod projection;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalParameterRoleProgramV1 {
    pub program: ParameterRoleSourceV3,
    pub uid: u32,
    pub gid: u32,
    pub inaccessible_paths: Vec<PathBuf>,
}
/// All templates are complete original native configurations enrolled by Root.
/// Only explicit original per-round fields are projected; custody paths and
/// role key paths are never discovered or copied from an Agent request.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalParameterEvaluationTemplateV1 {
    pub schema: String,
    pub public_source_directory: PathBuf,
    pub private_effect_directory: PathBuf,
    pub generator: OriginalParameterRoleProgramV1,
    pub observer: OriginalParameterRoleProgramV1,
    pub evaluator: OriginalParameterRoleProgramV1,
    pub publisher: OriginalParameterRoleProgramV1,
    pub generator_inputs: ParameterRoleSourceV3,
    pub generator_configuration: ParameterRoleSourceV3,
    pub observer_admission_configuration: ParameterRoleSourceV3,
    pub observer_execution_configuration: ParameterRoleSourceV3,
    pub evaluator_review_configuration: ParameterRoleSourceV3,
    pub observer_finish_configuration: ParameterRoleSourceV3,
    pub evaluator_preparation_configuration: ParameterRoleSourceV3,
    pub candidate_evaluation_configuration: ParameterRoleSourceV3,
    pub rollback_evaluation_configuration: ParameterRoleSourceV3,
    pub publication_configuration: ParameterRoleSourceV3,
}

pub enum OriginalParameterEvaluationPreparationResultV1 {
    Pending,
    Terminal { source: InstalledCpuSourceV1 },
    Completed(OriginalParameterEvaluationPublicationsV1),
}
pub struct OriginalParameterRollbackPublicationV2 {
    pub candidate_id: StableId,
    pub publication: ParameterPreRegisteredPublicationV1,
    pub publication_configuration: InstalledCpuSourceV1,
}
pub struct OriginalParameterEvaluationPublicationsV1 {
    pub materials: crate::CpuNeuronRoundMaterialsV3,
    pub evaluations: Vec<CandidateEvaluationAdmissionV1>,
    /// Original completion Hc/op/ACK is preserved for each whole four-set.
    pub candidates: Vec<ParameterPreRegisteredPublicationV1>,
    pub candidate_publication_configurations: Vec<InstalledCpuSourceV1>,
    pub rollbacks: Vec<OriginalParameterRollbackPublicationV2>,
    /// Compatibility projection of the first exact pair; multi-Update callers
    /// must consume the complete rollbacks frontier.
    pub rollback: ParameterPreRegisteredPublicationV1,
    pub rollback_publication_configuration: InstalledCpuSourceV1,
    /// Separate latest H', including its exact original publication ACK.
    pub latest_registration: InstalledCpuSourceV1,
    pub latest_current: RegisteredArtifactCurrentFactsV3,
}
/// Root supplies independently admitted trust and reviewer, not data-selected
/// credentials. The callback projects all three manifests from the actual four
/// receipts, then uses the original CURRENT reader to obtain the corresponding
/// full registration. No operation ID can be guessed from the last old receipt.
pub fn prepare_original_parameter_evaluation_publications_v1(
    materials: crate::CpuNeuronRoundMaterialsV3,
    template_source: &InstalledCpuSourceV1,
    subject: &StableId,
    trust: &ActivatedLearningTrustV1,
    reviewer: &AuthenticatedPrincipalV1,
    mut current_registration: impl FnMut(
        &ParameterPreRegisteredPublicationV1,
        &codex_hepta_neuron::NeuronGenerationMaterialV2,
        &InstalledCpuSourceV1,
    ) -> Result<InstalledCpuSourceV1>,
) -> Result<OriginalParameterEvaluationPreparationResultV1> {
    let template_bytes = read_root_review_input(&template_source.path, 64 * 1024)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    ensure!(
        Digest32::of_bytes(&template_bytes).to_string() == template_source.digest,
        "original pipeline template pin"
    );
    let template: OriginalParameterEvaluationTemplateV1 = serde_json::from_slice(&template_bytes)?;
    ensure!(
        template.schema == "hepta.original-parameter-evaluation-template.v1",
        "original raw E pipeline purpose"
    );
    let round = materials.round();
    let directory = template
        .private_effect_directory
        .join(format!("round-{}", round.identity_digest()));
    independent_owners::roles::prepare_effect_directory(&directory)?;
    let mut pipeline = projection::Pipeline {
        template: &template,
        directory,
        round: round.clone(),
    };
    pipeline.validate_time(trust)?;
    materials.with_plan(crate::validate_cpu_neuron_parameter_materials_v2)?;
    let request = materials.request();
    let binding = projection::round_binding(round)?;
    if materials.candidates().is_empty() {
        let inputs = encode_fixed_parameter_role_inputs_v1(
            &binding,
            &request.generator_profile,
            &request.admission,
            &request.generator_attestation,
            &request.admission_attestation,
            None,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let Some(output) = pipeline.preparation(&inputs, false)? else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        let verified = decode_fixed_parameter_no_change_output_v1(
            &output,
            &request.generator_profile,
            &request.admission,
            &request.generator_attestation,
            &request.admission_attestation,
            trust,
            now_ms()?,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        projection::validate_terminal(round, &verified.preparation_facts)?;
        return Ok(OriginalParameterEvaluationPreparationResultV1::Terminal {
            source: pipeline
                .publish("preparation-terminal", &verified.preparation_terminal_bytes)?,
        });
    }
    let Some(reviews) = measurement::measure(&mut pipeline, &materials, subject, trust)? else {
        return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
    };
    let completed = inspect_completed_parameter_evaluations_v1(
        &reviews,
        &binding,
        &request.generator_profile,
        &request.admission,
        &request.generator_attestation,
        &request.admission_attestation,
        reviewer,
        trust,
        now_ms()?,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    if !completed
        .dispositions()
        .contains(&IndependentEvaluationDispositionV1::EligibleForIndependentSelection)
    {
        let inputs = encode_fixed_parameter_preparation_inputs_v1(
            &binding,
            &request.generator_profile,
            &request.admission,
            &request.generator_attestation,
            &request.admission_attestation,
            &reviews,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let Some(output) = pipeline.preparation(&inputs, true)? else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        let value: serde_json::Value = serde_json::from_slice(&output)?;
        return pipeline.terminal(&value, trust);
    }
    // Every real E1 is measured before the first registry publication advances H.
    let mut candidates = Vec::new();
    for candidate in materials.candidates() {
        let Some(evaluation) = pipeline.e1(
            &materials,
            &candidate.candidate_id,
            &candidate.generation,
            ParameterPreRegistrationPurposeV1::Candidate,
            subject,
        )?
        else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        if let Some(bytes) = evaluation.0.preparation_terminal_bytes() {
            return pipeline.terminal_bytes(bytes, trust);
        }
        candidates.push(evaluation);
    }
    let mut rollback_evaluations = Vec::new();
    for candidate in materials.candidates() {
        let Some(rollback) = pipeline.e1(
            &materials,
            &candidate.candidate_id,
            materials.rollback_for_candidate(&candidate.candidate_id)?,
            ParameterPreRegistrationPurposeV1::ExactRollback,
            subject,
        )?
        else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        if let Some(bytes) = rollback.0.preparation_terminal_bytes() {
            return pipeline.terminal_bytes(bytes, trust);
        }
        rollback_evaluations.push(rollback);
    }
    let mut publications = Vec::new();
    let mut publication_configurations = Vec::new();

    for evaluation in &candidates {
        let Some((publication, publication_configuration)) =
            pipeline.publish_e1(evaluation, None)?
        else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        let material = evaluation
            .0
            .material()
            .context("actual complete E1 material absent")?;
        let configuration =
            current_registration(&publication, material, &publication_configuration)?;
        let facts = projection::current(&configuration, material, subject)?;
        facts
            .revalidate_current(now_ms()?)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        publications.push(publication);
        publication_configurations.push(publication_configuration);
    }
    let mut rollbacks = Vec::new();
    let mut latest = None;
    for rollback in &rollback_evaluations {
        let chosen = publications
            .iter()
            .position(|publication| publication.candidate_id == rollback.0.candidate_id().as_str())
            .context("exact rollback original predecessor absent")?;
        let chosen_material = candidates[chosen]
            .0
            .material()
            .context("actual predecessor material absent")?;
        let configuration = current_registration(
            &publications[chosen],
            chosen_material,
            &publication_configurations[chosen],
        )?;
        projection::current(&configuration, chosen_material, subject)?
            .revalidate_current(now_ms()?)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        let head = &publications[chosen].publications[3];
        let predecessor = ParameterPreRegisteredPredecessorV1 {
            evaluation: candidates[chosen].1.clone(),
            registration: CpuProtectedSourceV1 {
                path: configuration.path.clone(),
                digest: configuration.digest,
            },
            head_manifest: ParameterRoleSourceV3 {
                path: head.manifest.path.clone(),
                digest: head.manifest.digest.clone(),
            },
            head_admission_digest: head.admission_digest.clone(),
            head_artifact_id: head.artifact_id.clone(),
        };
        let Some((publication, publication_configuration)) =
            pipeline.publish_e1(rollback, Some(predecessor))?
        else {
            return Ok(OriginalParameterEvaluationPreparationResultV1::Pending);
        };
        let material = rollback
            .0
            .material()
            .context("actual exact rollback E1 material absent")?;
        let registration =
            current_registration(&publication, material, &publication_configuration)?;
        latest = Some((
            projection::current(&registration, material, subject)?,
            registration,
        ));
        rollbacks.push(OriginalParameterRollbackPublicationV2 {
            candidate_id: rollback.0.candidate_id().clone(),
            publication,
            publication_configuration,
        });
    }
    let (latest_current, latest_registration) =
        latest.context("complete rollback frontier absent")?;
    let verified_candidates: Vec<_> = candidates.into_iter().map(|value| value.0).collect();
    let verified_rollbacks: Vec<_> = rollback_evaluations
        .into_iter()
        .map(|value| value.0)
        .collect();
    let materials =
        materials.install_evaluated_materials(&verified_candidates, &verified_rollbacks)?;
    let first = rollbacks
        .first()
        .context("complete original rollback frontier absent")?;
    let rollback_publication = first.publication.clone();
    let rollback_publication_configuration = first.publication_configuration.clone();
    pipeline.validate_time(trust)?;
    ensure!(
        read_root_review_input(&template_source.path, 64 * 1024)
            .map_err(|e| anyhow::anyhow!("{e}"))?
            == template_bytes,
        "whole original pipeline template changed"
    );
    // E1 and publication can take time. Reopen the actual FULL sources and ACK
    // after those effects, then join their complete original receipts into the
    // sole pre-publication request used by the final admission owner.
    let request = materials.request();
    let completed = inspect_completed_parameter_evaluations_v1(
        &reviews,
        &binding,
        &request.generator_profile,
        &request.admission,
        &request.generator_attestation,
        &request.admission_attestation,
        reviewer,
        trust,
        now_ms()?,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    let materials = materials.install_completed_evaluations(&completed)?;
    let evaluations = materials.request().evaluations.clone();
    latest_current
        .revalidate_current(now_ms()?)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    pipeline.validate_time(trust)?;
    Ok(OriginalParameterEvaluationPreparationResultV1::Completed(
        OriginalParameterEvaluationPublicationsV1 {
            materials,
            evaluations,
            candidates: publications,
            candidate_publication_configurations: publication_configurations,
            rollbacks,
            rollback: rollback_publication,
            rollback_publication_configuration,
            latest_registration,
            latest_current,
        },
    ))
}
