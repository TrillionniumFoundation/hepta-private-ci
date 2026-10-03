//! Actual five original fixed purposes for every generated Update. Graph/cuts,
//! estimator/gates and physical input membership remain the enrolled template.
use super::projection::*;
use super::*;
use crate::ParameterRoleExecutionPurposeV1 as Purpose;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;

fn field_source(value: &serde_json::Value, name: &str) -> Result<ParameterRoleSourceV3> {
    Ok(serde_json::from_value(value[name].clone())?)
}
fn result_source(source: &InstalledCpuSourceV1) -> FixedParameterEvaluationSourceV1 {
    FixedParameterEvaluationSourceV1 {
        path: source.path.clone(),
        digest: source.digest.clone(),
    }
}
fn round_key(
    pipeline: &Pipeline<'_>,
    candidate: &StableId,
    role: &[u8],
    record: &[u8],
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.original.paired.parameter-round.v1\0",
        pipeline.round.identity_digest().as_array(),
        candidate.as_str().as_bytes(),
        role,
        record,
    ])
}
pub(super) fn measure(
    pipeline: &mut Pipeline<'_>,
    materials: &crate::CpuNeuronRoundMaterialsV3,
    _subject: &StableId,
    trust: &ActivatedLearningTrustV1,
) -> Result<Option<Vec<FixedParameterCompletedReviewSourceV1>>> {
    let template = pipeline.template;
    let generator_inputs = read(&template.generator_inputs, 128 * 1024 * 1024)?;
    let original_inputs: serde_json::Value = serde_json::from_slice(&generator_inputs)?;
    let raw = decode_review_payload_hex(
        original_inputs["plan_inputs_hex"]
            .as_str()
            .context("complete original paired plan template absent")?,
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    let original_plan =
        decode_original_paired_review_source_plan_v1(&raw).map_err(|e| anyhow::anyhow!("{e}"))?;
    ensure!(
        original_plan
            .tasks
            .iter()
            .all(|task| task.candidate_input_digest.is_zero()
                && task.baseline_input_digest.is_zero()),
        "fresh unsealed original physical input template required"
    );
    let execution_bytes = read(&template.observer_execution_configuration, 32 * 1024)?;
    let execution_template: serde_json::Value = serde_json::from_slice(&execution_bytes)?;
    let candidate_manifest = field_source(&execution_template["candidate"], "manifest")?;
    let baseline_manifest = field_source(&execution_template["baseline"], "manifest")?;
    let scorer = field_source(&execution_template, "scorer")?;
    // The physical manifest/runtime pins come from the enrolled full model
    // descriptors, not from an invented echo of prospective sparse parameters.
    ensure!(
        baseline_manifest.digest.parse::<Digest32>()?
            == materials.baseline().runtime.model_manifest_digest,
        "actual paired baseline descriptor differs from original material"
    );
    let request = materials.request();
    let binding = round_binding(&pipeline.round)?;
    let mut reports = Vec::new();
    for candidate in materials.candidates() {
        pipeline.validate_time(trust)?;
        ensure!(
            candidate_manifest.digest.parse::<Digest32>()?
                == candidate.generation.runtime.model_manifest_digest,
            "actual paired candidate descriptor differs from original prospective material"
        );
        let label = format!("raw-{}", candidate.candidate_id);
        let admission_configuration = InstalledCpuSourceV1 {
            path: template.observer_admission_configuration.path.clone(),
            digest: template.observer_admission_configuration.digest.clone(),
        };
        let Some(admission_output) = pipeline.execute(
            &format!("{label}-admit"),
            &template.observer,
            &admission_configuration,
            Purpose::ObserverPairedAdmission,
        )?
        else {
            return Ok(None);
        };
        let admission_wire: ReviewTrustWireV1 = serde_json::from_slice(&admission_output)?;
        let (root, distribution) = admission_wire
            .native()
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        let declared = activate_learning_trust(&root, distribution, None, now_ms()?)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        ensure!(
            declared.verifier().trust_digest() == trust.verifier().trust_digest()
                && declared.distribution_digest() == trust.distribution_digest(),
            "actual paired admission differs from independently installed role trust"
        );
        let mut plan = original_plan.clone();
        plan.base_plan.plan_id = StableId::new(format!(
            "parameter.plan.{}",
            round_key(
                pipeline,
                &candidate.candidate_id,
                b"plan",
                template.generator_inputs.digest.as_bytes()
            )
        ))?;
        plan.base_plan.candidate_id = candidate.candidate_id.clone();
        plan.base_plan.baseline_id = request.admission.baseline_id.clone();
        plan.base_plan.objective_digest = request.admission.objective_digest;
        plan.base_plan.dataset_digest = request.admission.dataset_digest;
        plan.source_scope.objective_digest = request.admission.objective_digest;
        plan.runtime.candidate_artifact_digest = candidate_manifest.digest.parse()?;
        plan.runtime.deployed_baseline_digest = baseline_manifest.digest.parse()?;
        plan.runtime.candidate_runtime_digest = scorer.digest.parse()?;
        plan.runtime.baseline_runtime_digest = scorer.digest.parse()?;
        for task in &mut plan.tasks {
            task.candidate_request_id = StableId::new(format!(
                "parameter.c.{}",
                round_key(
                    pipeline,
                    &candidate.candidate_id,
                    b"candidate",
                    task.source_record_digest.as_array()
                )
            ))?;
            task.baseline_request_id = StableId::new(format!(
                "parameter.b.{}",
                round_key(
                    pipeline,
                    &candidate.candidate_id,
                    b"baseline",
                    task.source_record_digest.as_array()
                )
            ))?;
        }
        let mut input: serde_json::Value = serde_json::from_slice(
            &project_original_paired_parameter_generator_inputs_v1(&generator_inputs, &plan)
                .map_err(|e| anyhow::anyhow!("{e}"))?,
        )?;
        input["trust"] = serde_json::to_value(admission_wire)?;
        let input = pipeline.publish(
            &format!("{label}-generator-inputs"),
            &serde_json::to_vec(&input)?,
        )?;
        let config = project_original_paired_parameter_configuration_v1(
            &read(&template.generator_configuration, 32 * 1024)?,
            OriginalPairedParameterConfigurationV1::Generator {
                inputs: &as_role(&input),
            },
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let config = pipeline.publish(&format!("{label}-generator-config"), &config)?;
        let Some(output) = pipeline.execute(
            &format!("{label}-generator"),
            &template.generator,
            &config,
            Purpose::GeneratorPairedRegistration,
        )?
        else {
            return Ok(None);
        };
        let actual: serde_json::Value = serde_json::from_slice(&output)?;
        ensure!(
            actual["schema"] == "hepta.eval.paired-supervised.public-generator-source.v1"
                && actual["generator_uid"] == template.generator.uid
                && actual["generator_gid"] == template.generator.gid,
            "actual original enrolled G identity/purpose changed"
        );
        let generated = pipeline.publish(&format!("{label}-generator-publication"), &output)?;
        let work = pipeline.directory.join(format!(
            "{}-custody",
            round_key(pipeline, &candidate.candidate_id, b"work", b"")
        ));
        independent_owners::roles::prepare_effect_directory(&work)?;
        let config = project_original_paired_parameter_configuration_v1(
            &execution_bytes,
            OriginalPairedParameterConfigurationV1::Execution {
                generator: &as_role(&generated),
                work_directory: &work,
                deadline_ms: pipeline.round.deadline_ms(),
            },
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let config = pipeline.publish(&format!("{label}-execution-config"), &config)?;
        if pipeline
            .execute(
                &format!("{label}-execution"),
                &template.observer,
                &config,
                Purpose::ObserverPairedExecution,
            )?
            .is_none()
        {
            return Ok(None);
        }
        let publication = read_root_review_input(&work.join("execution.json"), 128 * 1024 * 1024)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        let publication =
            pipeline.publish(&format!("{label}-custody-publication"), &publication)?;
        let inputs = encode_fixed_parameter_role_inputs_v1(
            &binding,
            &request.generator_profile,
            &request.admission,
            &request.generator_attestation,
            &request.admission_attestation,
            Some(&candidate.candidate_id),
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let parameter = pipeline.publish(&format!("{label}-parameter-inputs"), &inputs)?;
        let config = project_original_paired_parameter_configuration_v1(
            &read(&template.evaluator_review_configuration, 32 * 1024)?,
            OriginalPairedParameterConfigurationV1::Review {
                publication: &as_role(&publication),
                parameter: &as_role(&parameter),
            },
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let config = pipeline.publish(&format!("{label}-review-config"), &config)?;
        let Some(output) = pipeline.execute(
            &format!("{label}-review"),
            &template.evaluator,
            &config,
            Purpose::EvaluatorParameterReview,
        )?
        else {
            return Ok(None);
        };
        let review = pipeline.publish(&format!("{label}-review-publication"), &output)?;
        let evidence_directory = pipeline.directory.join(format!(
            "{}-evidence",
            round_key(pipeline, &candidate.candidate_id, b"sink", b"")
        ));
        let acknowledgement_directory = pipeline.directory.join(format!(
            "{}-ack",
            round_key(pipeline, &candidate.candidate_id, b"ack", b"")
        ));
        independent_owners::roles::prepare_effect_directory(&evidence_directory)?;
        independent_owners::roles::prepare_effect_directory(&acknowledgement_directory)?;
        let evidence = evidence_directory.join("original-full-evidence.json");
        let acknowledgement = acknowledgement_directory.join("original-ack.txt");
        let config = project_original_paired_parameter_configuration_v1(
            &read(&template.observer_finish_configuration, 32 * 1024)?,
            OriginalPairedParameterConfigurationV1::Finish {
                publication: &as_role(&publication),
                evaluation: &as_role(&review),
                parameter: &as_role(&parameter),
                evidence_path: &evidence,
                acknowledgement_path: &acknowledgement,
            },
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let config = pipeline.publish(&format!("{label}-finish-config"), &config)?;
        let Some(output) = pipeline.execute(
            &format!("{label}-finish"),
            &template.observer,
            &config,
            Purpose::ObserverPairedFinish,
        )?
        else {
            return Ok(None);
        };
        let finished = pipeline.publish(&format!("{label}-finished-publication"), &output)?;
        let ack_bytes =
            read_root_review_input(&acknowledgement, 65).map_err(|e| anyhow::anyhow!("{e}"))?;
        let ack = pipeline.publish(&format!("{label}-whole-ack"), &ack_bytes)?;
        reports.push(FixedParameterCompletedReviewSourceV1 {
            publication: result_source(&publication),
            result: result_source(&finished),
            acknowledgement: result_source(&ack),
        });
    }
    ensure!(
        reports.len()
            == request
                .generated
                .candidates
                .iter()
                .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
                .count(),
        "original complete generated evaluation frontier changed"
    );
    pipeline.validate_time(trust)?;
    Ok(Some(reports))
}
