//! Return the original whole E transport only after original custody finish.
use super::*;
use codex_hepta_agentd::AgentdSelfIterationCanaryVerdictV1;

fn trust(
    input: &RoleInput,
) -> Result<(
    crate::InstalledSelfIterationIndependentOwnersConfigV1,
    ActivatedLearningTrustV1,
)> {
    let bytes = configuration::source(&input.configuration.client_configuration, 64 * 1024)?;
    let config: crate::InstalledSelfIterationIndependentOwnersConfigV1 =
        serde_json::from_slice(&bytes)?;
    let wire: ReviewTrustWireV1 =
        serde_json::from_slice(&configuration::source(&config.learning_trust, 64 * 1024)?)?;
    let (root, distribution) = wire.native().map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok((
        config,
        activate_learning_trust(&root, distribution, None, now_ms()?)?,
    ))
}
fn transport(bytes: &[u8]) -> Result<Vec<u8>> {
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    let hex = value["self_iteration_evaluation_transport_hex"]
        .as_str()
        .context("original full cycle E transport absent")?;
    let bytes = decode_review_payload_hex(hex).map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(
        !bytes.is_empty() && bytes.len() <= MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES,
        "whole original E transport bound"
    );
    Ok(bytes)
}
fn verify_transport(input: &RoleInput, bytes: &[u8]) -> Result<Digest32> {
    let (config, trust) = trust(input)?;
    let verified = decode_self_iteration_evaluation_transport_v1(
        bytes,
        input.frozen_digest,
        &trust,
        now_ms()?,
    )?;
    let authentication = verified.admission().decision.authentication_digest;
    let (bundle, _, _, evaluator) = verified.into_parts();
    let consumer = read_self_iteration_role_input_v1(
        &input.consumer.path,
        input.configuration.generator_uid,
        MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let frozen = decode_self_iteration_frozen_consumer_v1(&consumer, &bundle, &trust, now_ms()?)?;
    let actor = trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evaluator,
        &self_iteration_evaluation_use_payload_v1(input.frozen_digest, authentication),
        now_ms()?,
    )?;
    ensure!(
        actor.principal().principal_id.as_str() == config.evaluator,
        "actual independently installed E principal changed"
    );
    verify_signed_independent_roles_v1(frozen.generator(), &actor, now_ms()?)?;
    Ok(authentication)
}

pub(super) fn verify_publication(input: &RoleInput, bytes: &[u8]) -> Result<()> {
    if input.purpose == SelfIterationOwnerPurposeV1::Evaluate {
        verify_transport(input, &transport(bytes)?)?;
        return Ok(());
    }
    let (config, trust) = trust(input)?;
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    ensure!(
        value["frozen_digest"].as_str() == Some(input.frozen_digest.to_string().as_str())
            && value["production_activation"] == false,
        "native whole role output differs from actual frozen request"
    );
    let (role, field, principal, payload) = match input.purpose {
        SelfIterationOwnerPurposeV1::Select => {
            ensure!(
                value["schema"] == "hepta.cpu-neuron.self-iteration-stage-selection.v1"
                    && value["selector_uid"].as_u64()
                        == Some(u64::from(input.configuration.selector.uid))
                    && value["artifact_publication"] == false,
                "original finite S stage purpose changed"
            );
            let actual = verify_transport(
                input,
                &configuration::source(
                    &completed_evaluation(input)?,
                    MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES,
                )?,
            )?;
            ensure!(
                input.record.evaluation_digest == Some(actual)
                    && value["evaluation_digest"] == actual.to_string(),
                "actual whole E/record/S binding changed"
            );
            (
                LearningEvidenceRoleV1::Selector,
                "selector_evidence",
                config.selector,
                codex_hepta_agentd::self_iteration_stage_payload_v1(input.frozen_digest, actual),
            )
        }
        SelfIterationOwnerPurposeV1::Observe => {
            let verdict = match value["verdict"].as_str() {
                Some("accept") => AgentdSelfIterationCanaryVerdictV1::Accept,
                Some("rollback") => AgentdSelfIterationCanaryVerdictV1::RollBack,
                _ => anyhow::bail!("actual physical O verdict absent"),
            };
            ensure!(
                value["schema"] == "hepta.cpu-neuron.self-iteration-canary-observation.v1"
                    && value["canary_operation_digest"].as_str()
                        == input
                            .record
                            .canary_operation_digest
                            .map(|v| v.to_string())
                            .as_deref()
                    && value["canary_checkpoint_digest"].as_str()
                        == input
                            .record
                            .canary_checkpoint_digest
                            .map(|v| v.to_string())
                            .as_deref()
                    && serde_json::from_value::<
                        codex_hepta_agentd::AgentdSelfIterationCanaryObservationV1,
                    >(value["physical_observation"].clone())?
                        == input
                            .record
                            .canary_observation
                            .clone()
                            .context("actual full physical observation absent")?,
                "native O output differs from actual whole committed canary"
            );
            (
                LearningEvidenceRoleV1::Observer,
                "observer_evidence",
                config.observer,
                codex_hepta_agentd::self_iteration_canary_payload_v1(&input.record, verdict)?,
            )
        }
        SelfIterationOwnerPurposeV1::Evaluate => unreachable!(),
    };
    let evidence: ReviewEvidenceWireV1 = serde_json::from_value(value[field].clone())?;
    let verified = trust.verifier().verify(
        role,
        &evidence
            .native()
            .map_err(|error| anyhow::anyhow!("{error}"))?,
        &payload,
        now_ms()?,
    )?;
    ensure!(
        verified.principal().principal_id.as_str() == principal,
        "original native role principal changed"
    );
    Ok(())
}

pub(super) fn completed_evaluation(input: &RoleInput) -> Result<InstalledCpuSourceV1> {
    let bytes = read_root_review_input(
        &input.directory.join("cycle-custody-finish.output"),
        3 * 1024 * 1024,
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let native = transport(&bytes)?;
    verify_transport(input, &native)?;
    publication::role_source(
        &input.configuration.evaluation_directory,
        &format!("evaluation-{}.bin", input.frozen_digest),
        &native,
        MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES,
        input.configuration.evaluator.uid,
        input.configuration.evaluator.gid,
    )
}

pub(super) fn finish_evaluation(input: &RoleInput, original_review: &[u8]) -> Result<Vec<u8>> {
    let route = &input.configuration.custody_finish;
    let review = publication::root_source(
        &input.directory,
        "cycle-evaluator-result.json",
        original_review,
        3 * 1024 * 1024,
    )?;
    let mut template: serde_json::Value = serde_json::from_slice(&configuration::source(
        &route.configuration_template,
        32 * 1024,
    )?)?;
    ensure!(template.is_object(), "original custody finish template");
    template["execution"] = serde_json::to_value(&input.configuration.paired_custody_execution)?;
    template["evaluator_result"] = serde_json::to_value(review)?;
    template["self_iteration"] = serde_json::json!({"path":input.consumer.path,
        "generator_uid":input.configuration.generator_uid,"canonical_envelope_digest":input.original_round.canonical_policy_digest().to_string()});
    template["parameter_evaluation"] = serde_json::Value::Null;
    let configuration = publication::root_source(
        &input.directory,
        "cycle-custody-finish.json",
        &serde_json::to_vec(&template)?,
        32 * 1024,
    )?;
    let request = role_request(
        route,
        configuration,
        ParameterRoleExecutionPurposeV1::ObserverPairedFinish,
        input.original_request_digest,
    );
    let output = crate::execute_retained_parameter_role_v1(
        &request,
        &input.directory.join("cycle-custody-finish.output"),
        |bytes| {
            revalidate(input)
                .map_err(|error| -> Box<dyn std::error::Error> { format!("{error}").into() })?;
            let value: serde_json::Value = serde_json::from_slice(bytes)?;
            if value["schema"] != "hepta.fixed-paired-original-custody-qualified.v1"
                || value["original_full_sink_acknowledged"] != true
                || value["authority_grants_any"] != false
                || value["production_activation"] != false
            {
                return Err("actual original FULL sink/ACK custody completion absent".into());
            }
            verify_transport(
                input,
                &transport(bytes)
                    .map_err(|error| -> Box<dyn std::error::Error> { format!("{error}").into() })?,
            )
            .map_err(|error| -> Box<dyn std::error::Error> { format!("{error}").into() })?;
            Ok(())
        },
    )
    .map_err(|error| anyhow::anyhow!("{error}"))?
    .context("original custody finish remains unknown")?;
    let native = transport(&output)?;
    verify_transport(input, &native)?;
    revalidate(input)?;
    Ok(native)
}
