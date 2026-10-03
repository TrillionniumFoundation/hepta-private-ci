//! Immutable original role inputs and consumed purpose slots. No role output
//! is inferred from a model assessment, caller flag or a planned operation.
use super::*;
use crate::ParameterRoleExecutionPurposeV1;
use crate::ParameterRoleExecutionV1;
use crate::RootSelfIterationRoleRouteV1;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2;
use std::path::PathBuf;

#[path = "root_self_iteration_owners_publication.rs"]
mod publication;
pub(super) use publication::prepare_effect_directory;
pub(super) use publication::publish_consumer;

pub(super) struct RoleInput {
    pub configuration: RoundConfiguration,
    pub configuration_path: PathBuf,
    pub configuration_bytes: Vec<u8>,
    pub original_round: AgentdSelfIterationRoundV1,
    pub purpose: SelfIterationOwnerPurposeV1,
    pub consumer: InstalledCpuSourceV1,
    pub record: AgentdSelfIterationRecordV1,
    pub original_request_digest: Digest32,
    pub directory: PathBuf,
    pub frozen_digest: Digest32,
}

pub(super) async fn actual_canary(
    client: &AgentdClient,
    before: &SupervisordAgentStatus,
    materials: &crate::CpuNeuronParameterRootMaterialsV2,
    input: &RoleInput,
) -> Result<NeuronAcknowledgedOperationV2> {
    let (tick, _) = materials
        .candidate_canary(&StableId::new(&input.record.candidate_id)?)
        .context("original selected canary input absent")?;
    let scope = tick.journal_scope()?;
    let (generation, receipt) = client
        .canary_operation_receipt(codex_hepta_agentd::CanaryOperationQueryV2 {
            model_generation: input.record.successor_generation,
            configuration_digest: input.record.successor_configuration.to_string(),
            body_digest: input.record.successor_body.to_string(),
            scope_digest: scope.scope_digest.to_string(),
            objective_digest: scope.objective_digest.to_string(),
            tick_id: tick.tick_id.to_string(),
            input_semantic_digest: tick.semantic_digest()?.to_string(),
        })
        .await?;
    current::validate_runtime_generation(before, generation)?;
    let native = receipt.record();
    let physical = &receipt.commit().output;
    ensure!(
        receipt.generation() == input.record.successor_generation
            && native.witness_acknowledged
            && input.record.canary_operation_digest == Some(native.operation_digest)
            && input.record.canary_checkpoint_digest == Some(physical.tick.checkpoint_after)
            && input
                .record
                .canary_observation
                .as_ref()
                .is_some_and(|observation| observation.latency_micros
                    == physical.model_runtime.latency_micros
                    && observation.resident_bytes == physical.model_runtime.resident_bytes
                    && observation.confidence_ppm == physical.tick.confidence_ppm
                    && observation.ood_ppm == physical.tick.ood_ppm
                    && observation.abstain == physical.tick.abstain),
        "caller record differs from actual original committed canary/ACK/checkpoint"
    );
    Ok(receipt)
}

pub(super) fn execute(
    input: RoleInput,
    canary: Option<NeuronAcknowledgedOperationV2>,
) -> Result<Option<Vec<u8>>> {
    let config = &input.configuration;
    let route = match input.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => &config.evaluator,
        SelfIterationOwnerPurposeV1::Select => &config.selector,
        SelfIterationOwnerPurposeV1::Observe => &config.observer,
    };
    let mut template: serde_json::Value = serde_json::from_slice(&configuration::source(
        &route.configuration_template,
        64 * 1024,
    )?)?;
    ensure!(
        template.is_object(),
        "whole fixed role template must be an object"
    );
    template["canonical_envelope_digest"] = input
        .original_round
        .canonical_policy_digest()
        .to_string()
        .into();
    match input.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => {
            template["publication_path"] = config
                .paired_custody_execution
                .path
                .display()
                .to_string()
                .into();
            template["publication_digest"] = config.paired_custody_execution.digest.clone().into();
            template["self_iteration_consumer"] = serde_json::json!({"path":input.consumer.path,
                "generator_uid":config.generator_uid,"canonical_envelope_digest":input.original_round.canonical_policy_digest().to_string()});
            template
                .as_object_mut()
                .unwrap()
                .remove("canonical_envelope_digest");
            template["parameter_evaluation"] = serde_json::Value::Null;
        }
        SelfIterationOwnerPurposeV1::Select | SelfIterationOwnerPurposeV1::Observe => {
            template["consumer"] =
                serde_json::json!({"path":input.consumer.path,"uid":config.generator_uid});
            let evaluation = completed_evaluation(&input)?;
            template["evaluation"] =
                serde_json::json!({"path":evaluation.path,"uid":config.evaluator.uid});
        }
    }
    if input.purpose == SelfIterationOwnerPurposeV1::Observe {
        let receipt = canary.context("actual original canary whole receipt absent")?;
        let source = publication::root_source(
            &input.directory,
            "original-canary.bin",
            receipt.bytes(),
            codex_hepta_agent_components::neuron::MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2,
        )?;
        template["canary"] = serde_json::to_value(source)?;
        let selection =
            publication::root_existing(&input.directory, "cycle-selector.output", 32 * 1024)?;
        template["selection"] =
            serde_json::json!({"path":selection.path,"uid":config.selector.uid});
    }
    let label = match input.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => "cycle-evaluator",
        SelfIterationOwnerPurposeV1::Select => "cycle-selector",
        SelfIterationOwnerPurposeV1::Observe => "cycle-observer",
    };
    let configuration = publication::root_source(
        &input.directory,
        &format!("{label}.json"),
        &serde_json::to_vec(&template)?,
        64 * 1024,
    )?;
    let purpose = match input.purpose {
        SelfIterationOwnerPurposeV1::Evaluate => {
            ParameterRoleExecutionPurposeV1::EvaluatorPairedReview
        }
        SelfIterationOwnerPurposeV1::Select => {
            ParameterRoleExecutionPurposeV1::SelectorRegisteredCycleStage
        }
        SelfIterationOwnerPurposeV1::Observe => {
            ParameterRoleExecutionPurposeV1::ObserverRegisteredCanary
        }
    };
    let request = role_request(route, configuration, purpose, input.original_request_digest);
    let output = input.directory.join(format!("{label}.output"));
    let original = crate::execute_retained_parameter_role_v1(&request, &output, |bytes| {
        revalidate(&input).map_err(|error| -> Box<dyn std::error::Error> { format!("{error}").into() })?;
        verify_publication(&input, bytes).map_err(|error| format!("{error}").into())
    })
    .map_err(|error| anyhow::anyhow!("{error}"))?;
    let Some(original) = original else {
        return Ok(None);
    };
    if input.purpose == SelfIterationOwnerPurposeV1::Evaluate {
        return finish_evaluation(&input, &original).map(Some);
    }
    revalidate(&input)?;
    Ok(Some(original))
}

fn role_request(
    route: &RootSelfIterationRoleRouteV1,
    configuration: InstalledCpuSourceV1,
    purpose: ParameterRoleExecutionPurposeV1,
    effect: Digest32,
) -> ParameterRoleExecutionV1 {
    ParameterRoleExecutionV1 {
        purpose,
        program: ParameterRoleSourceV3 {
            path: route.program.path.clone(),
            digest: route.program.digest.clone(),
        },
        configuration: ParameterRoleSourceV3 {
            path: configuration.path,
            digest: configuration.digest,
        },
        uid: route.uid,
        gid: route.gid,
        original_effect_digest: effect,
        inaccessible_paths: route.inaccessible_paths.clone(),
    }
}
fn revalidate(input: &RoleInput) -> Result<()> {
    ensure!(
        now_ms()? < input.original_round.deadline_ms()
            && RoundConfiguration::read(&input.configuration_path, &input.original_round)?.1
                == input.configuration_bytes,
        "original finite purpose expired or whole configuration changed"
    );
    Ok(())
}

#[path = "root_self_iteration_owners_evaluation.rs"]
mod evaluation;
use evaluation::completed_evaluation;
use evaluation::finish_evaluation;
use evaluation::verify_publication;
