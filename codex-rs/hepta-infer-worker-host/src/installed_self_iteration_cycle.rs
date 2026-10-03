//! Drive the installed original round, model adapter and physical compiler.
//! Preparation and independent evidence use the original authenticated route.
use super::SelfIterationHostConfigV1;
use super::publish_status;
use crate::AppServerSelfIterationModelPortV1;
use crate::CpuNeuronFrozenGeneratorClientV1;
use crate::CpuNeuronGovernedParameterCompilerV1;
use crate::initial_cpu_anchor::CpuNeuronOriginalGenerationReaderV3;
use crate::CpuNeuronParameterCandidatePlanV2;
use crate::CpuNeuronParameterCompilerOwnersV2;
use crate::CpuNeuronParameterCompilerPlanV2;
use crate::CpuNeuronParameterPolicyV2;
use crate::CpuNeuronParameterRootMaterialsV2;
use crate::InstalledSelfIterationIndependentOwnersV1;
use crate::initial_cpu_anchor::RegisteredCpuModelResolverV3;
use crate::initial_cpu_anchor::InstalledCpuSourceV1;
use codex_hepta_agent_components::frozen_generator_wire::RoundPreparationResultV1;
use codex_hepta_agent_components::intelligence_eval::ParameterPreRegistrationPurposeV1;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdGovernedParameterCandidateAssemblerV1;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::AgentdSelfIterationModelCycleV1;
use codex_hepta_agentd::AgentdSelfIterationModelOwnerContextV2;
use codex_hepta_agentd::AgentdSelfIterationPreparationTerminalV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InstalledSelfIterationCycleConfigV1 {
    pub schema: String,
    pub root_route: InstalledCpuSourceV1,
    pub canonical: InstalledCpuSourceV1,
    pub maximum_candidates: u16,
    pub worker_executable_digest: String,
    pub generator_principal: String,
    pub maximum_request_duration_ms: u64,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PreparedCandidateAdmissionV1 {
    pub candidate_id: String,
    pub configuration: InstalledCpuSourceV1,
    pub selection: InstalledCpuSourceV1,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InstalledRoundBundleV1 {
    pub schema: String,
    pub round: AgentdSelfIterationRoundV1,
    pub materials: InstalledCpuSourceV1,
    pub plasticity_context: InstalledCpuSourceV1,
    pub independent_owners: InstalledCpuSourceV1,
    pub candidates: Vec<PreparedCandidateAdmissionV1>,
    pub rollback: PreparedCandidateAdmissionV1,
}
pub(crate) struct Composition {
    pub resolver: Arc<dyn RegisteredCpuModelResolverV3>,
    pub reader: CpuNeuronOriginalGenerationReaderV3,
    pub resources: Arc<crate::FleetWorkerResourcePortV2>,
    pub control: Arc<tokio::sync::Mutex<DurableInferenceControl>>,
}
type Cycle = AgentdSelfIterationModelCycleV1<
    AppServerSelfIterationModelPortV1,
    AgentdGovernedParameterCandidateAssemblerV1<CpuNeuronGovernedParameterCompilerV1>,
    InstalledSelfIterationIndependentOwnersV1,
>;

pub(crate) async fn run(
    model: AppServerSelfIterationModelPortV1,
    installed: SelfIterationHostConfigV1,
    identity: AgentdIdentity,
    source: InstalledCpuSourceV1,
    composition: Composition,
    context: AgentdSelfIterationModelOwnerContextV2,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    let bytes = read(&source, 64 * 1024)?;
    let config: InstalledSelfIterationCycleConfigV1 = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.installed-self-iteration-cycle.v1"
        || !(1..=60_000).contains(&config.maximum_request_duration_ms)
    {
        return Err(invalid("installed cycle schema or request bound"));
    }
    let canonical = CanonicalIterationEnvelopeV1::decode(&read(&config.canonical, 262_144)?)
        .map_err(invalid)?;
    let envelope = canonical.execution_envelope(config.maximum_candidates).map_err(invalid)?;
    let runtime = context.iteration_handle().ok_or_else(|| invalid("original round owner absent"))?;
    let plasticity = context.plasticity_handle().ok_or_else(|| invalid("original plasticity owner absent"))?;
    let host = context.neuron_host().ok_or_else(|| invalid("original Neuron host absent"))?;
    let mut model = Some(model);
    let mut cycle: Option<(AgentdSelfIterationRoundV1, Cycle)> = None;
    let mut interval = tokio::time::interval(Duration::from_secs(5));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut status = serde_json::json!({"version":1,"state":"pending_round_preparation","generation_ready":false,"authority_grants":false});
    loop {
        tokio::select! { _ = cancellation.cancelled() => return Ok(()), _ = interval.tick() => {} }
        let result = async {
            if read(&source, 64 * 1024)? != bytes {
                return Err(invalid("installed cycle Source changed"));
            }
            let current = runtime.inspect_current_round().await?;
            let actual_model = if let Some((_, cycle)) = &mut cycle {
                cycle.model_mut()
            } else { model.as_mut() };
            if let Some(actual_model) = actual_model {
                let receipt = actual_model.maintain_native_control(Duration::from_secs(5)).await
                    .map_err(invalid)?;
                if receipt.aborts_unresolved > 0 || receipt.terminal_publications_unresolved > 0
                    || receipt.cleanup_error.is_some()
                    || receipt.cleanup.is_some_and(|cleanup| cleanup.pending_pre_effect > 0 || cleanup.unknown_history_retained > 0 || cleanup.terminal_cleanup_pending > 0 || cleanup.actively_cleaning > 0)
                {
                    return Err(invalid("original native model obligations remain unresolved"));
                }
            }
            if current.as_ref().is_some_and(|current| current.can_admit_next_round())
                && let Some((_, original_cycle)) = &mut cycle
            {
                model = Some(original_cycle.take_model_after_terminal_round().await?);
                cycle = None;
            }
            if let Some((round, cycle)) = &mut cycle {
                if current.as_ref().is_none_or(|current| current.status.round != *round) {
                    return Err(invalid("actual retained cycle lost its original reservation"));
                }
                let record = cycle.run_reserved_round(
                    round.clone(), canonical.clone(), envelope.clone(), installed.objective_prompt.clone(),
                ).await?;
                status["state"] = serde_json::json!(format!("{:?}", record.phase));
                status["round"] = serde_json::json!(round.identity_digest().to_string());
                status["generation_ready"] = serde_json::json!(matches!(record.phase, codex_hepta_agentd::AgentdSelfIterationPhaseV1::Accepted));
                return Ok(());
            }
            let round = if let Some(current) = &current {
                if !current.can_admit_next_round() {
                    current.status.round.clone()
                } else {
                    // This installed driver retains terminal truth. A subsequent
                    // Goal is admitted below only with its actual new scope.
                    let (_, scope) = host.current_installed_owner_v3()?;
                    let scope = scope.ok_or_else(|| invalid("actual serving Goal scope absent"))?;
                    let goal = StableId::new(format!("goal.{}", scope.identity.subject_scope_digest)).map_err(invalid)?;
                    if current.status.round.goal_id() == goal.as_str() {
                        status["state"] = serde_json::json!("completed_original_round");
                        return Ok(());
                    }
                    runtime.reserve_round(goal, canonical.clone(), envelope.clone()).await?
                }
            } else {
                let (_, scope) = host.current_installed_owner_v3()?;
                let scope = scope.ok_or_else(|| invalid("actual serving Goal scope absent"))?;
                let goal = StableId::new(format!("goal.{}", scope.identity.subject_scope_digest)).map_err(invalid)?;
                runtime.reserve_round(goal, canonical.clone(), envelope.clone()).await?
            };
            if round.canonical_policy_digest() != canonical.digest()
                || round.execution_envelope_digest() != codex_hepta_agentd::self_iteration_envelope_digest_v1(&envelope)
            {
                return Err(invalid("cold reservation differs from installed complete policy"));
            }
            let response = crate::frozen_generator_client::round_preparation::prepare(&config.root_route, &round).await?;
            let bundle_source = match response {
                RoundPreparationResultV1::Terminal { source } => {
                    runtime.complete_preparation(round.clone(), AgentdSelfIterationPreparationTerminalV1::from_root_source(source.path, source.digest.parse().map_err(invalid)?)?).await?;
                    status["state"] = serde_json::json!("completed_independent_preparation");
                    return Ok(());
                }
                RoundPreparationResultV1::Prepared { bundle } => InstalledCpuSourceV1 { path:bundle.path, digest:bundle.digest },
                RoundPreparationResultV1::Refused { error } => return Err(invalid(format!("original Root preparation: {error:?}"))),
            };
            let bundle: InstalledRoundBundleV1 = serde_json::from_slice(&read(&bundle_source, 64 * 1024)?)?;
            if bundle.schema != "hepta.installed-round-bundle.v1" || bundle.round != round {
                return Err(invalid("Root bundle changed whole original round"));
            }
            let materials = CpuNeuronParameterRootMaterialsV2::from_protected_source(&bundle.materials, config.worker_executable_digest.parse().map_err(invalid)?)?;
            if materials.canonical_envelope().digest() != canonical.digest()
                || materials.execution_envelope() != &envelope
                || bundle.candidates.len() != materials.with_plan(|plan| plan.candidates.len())
            {
                return Err(invalid("Root bundle changed original whole material frontier"));
            }
            plasticity.refresh_input_context_v2(&runtime, bundle.plasticity_context.path.clone(), bundle.plasticity_context.digest.parse().map_err(invalid)?).await.map_err(|error| invalid(format!("original context refresh: {error:?}")))?;
            let (baseline, _) = host.current_installed_owner_v3()?;
            let capability = composition.resolver.current(&StableId::new(identity.agent_id.as_str()).map_err(invalid)?)?;
            if baseline.configuration_digest() != materials.baseline().runtime.semantic_digest().map_err(invalid)?
                || baseline.body_bundle_digest() != Some(materials.baseline().body.semantic_digest().map_err(invalid)?)
                || capability.plan().runtime.semantic_digest().map_err(invalid)? != baseline.configuration_digest()
            {
                return Err(invalid("actual current baseline differs from whole Root material"));
            }
            let clock = Arc::new(SystemAuthorityClock);
            let worker = |generation| crate::CpuNeuronControlConfigV2 {
                resources:composition.resources.clone(), model_generation:generation,
                maximum_request_duration:Duration::from_millis(config.maximum_request_duration_ms),
            };
            let candidates = materials.with_plan(|plan| {
                plan.candidates.iter().map(|candidate| {
                    let selected = bundle.candidates.iter().find(|selected| selected.candidate_id == candidate.candidate_id.as_str()).ok_or_else(|| invalid("whole candidate admission missing"))?;
                    let (material, admission) = admission(selected, &round, candidate.generation, ParameterPreRegistrationPurposeV1::Candidate, clock.clone())?;
                    let (tick, port) = materials.candidate_canary(candidate.candidate_id).ok_or_else(|| invalid("whole canary input missing"))?;
                    Ok(CpuNeuronParameterCandidatePlanV2 {
                        candidate_id:candidate.candidate_id.clone(), worker:worker(material.runtime.generation), generation:material,
                        admission, canary_tick:tick.clone(), canary_port:port.clone(),
                    })
                }).collect::<Result<Vec<_>, AgentdError>>()
            })?;
            let (rollback, rollback_admission) = admission(&bundle.rollback, &round, materials.rollback(), ParameterPreRegistrationPurposeV1::ExactRollback, clock.clone())?;
            let owners = InstalledSelfIterationIndependentOwnersV1::from_protected_source(&bundle.independent_owners, round.clone(), &materials)?;
            let plan = materials.with_plan(|plan| CpuNeuronParameterCompilerPlanV2 {
                envelope:envelope.clone(), baseline, baseline_runtime:plan.baseline_runtime.clone(), baseline_native:plan.baseline_native.clone(), baseline_body:plan.baseline_body.clone(), baseline_candidate_id:plan.baseline_candidate_id.clone(), request:plan.request.clone(), test_plan_digest:plan.test_plan_digest, candidates,
                rollback_worker:worker(rollback.runtime.generation), rollback, rollback_admission:Some(rollback_admission),
            });
            let compiler = CpuNeuronGovernedParameterCompilerV1::new_v2(plan, CpuNeuronParameterCompilerOwnersV2 {
                resources:composition.resources.clone(), control:composition.control.clone(), clock,
                generator:Arc::new(CpuNeuronFrozenGeneratorClientV1::from_protected_route(config.root_route.path.clone(),config.root_route.digest.parse().map_err(invalid)?,StableId::new(&config.generator_principal).map_err(invalid)?)?),
            }, CpuNeuronParameterPolicyV2::new(canonical.clone(),canonical.digest())?)?;
            composition.reader.publish_round_reader(compiler.physical_generation_reader())?;
            let original_model = model.take().ok_or_else(|| invalid("original model adapter unavailable"))?;
            cycle = Some((round, Cycle::new(original_model, AgentdGovernedParameterCandidateAssemblerV1::new(plasticity.clone(), compiler), owners, runtime.clone())));
            Ok(())
        }.await;
        if let Err(error) = result {
            status["state"] = serde_json::json!("pending_original_round");
            status["diagnostic"] = serde_json::json!(error.to_string().chars().take(2048).collect::<String>());
        }
        publish_status(&installed.status_file, &status)?;
    }
}
fn admission(
    source:&PreparedCandidateAdmissionV1, round:&AgentdSelfIterationRoundV1,
    expected:&crate::CpuNeuronGenerationPlanV1, purpose:ParameterPreRegistrationPurposeV1,
    clock:Arc<SystemAuthorityClock>,
) -> Result<(crate::CpuNeuronGenerationPlanV1,codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1),AgentdError> {
    let verified = crate::initial_cpu_anchor::inspect_parameter_pre_registered_admission_v1(&source.configuration.path,source.configuration.digest.parse().map_err(invalid)?,&source.selection.path,source.selection.digest.parse().map_err(invalid)?).map_err(invalid)?;
    if verified.candidate_id().as_str() != source.candidate_id || verified.purpose() != purpose
        || verified.round().round_digest != round.identity_digest().to_string()
        || verified.round().round_payload_digest != Digest32::of_bytes(&round.canonical_bytes()?).to_string()
        || codex_hepta_neuron::encode_neuron_generation_material_v2(verified.material()).map_err(invalid)? != codex_hepta_neuron::encode_neuron_generation_material_v2(expected).map_err(invalid)?
    { return Err(invalid("whole original E/S material admission changed")); }
    verified.into_original_admission(clock).map_err(invalid)
}
pub(crate) fn read(source:&InstalledCpuSourceV1,maximum:u64)->Result<Vec<u8>,AgentdError> {
    let pin:Digest32 = source.digest.parse().map_err(invalid)?;
    let bytes = codex_hepta_agent_components::learning_ledger::read_root_review_input(&source.path,maximum).map_err(invalid)?;
    if pin.is_zero() || Digest32::of_bytes(&bytes) != pin { return Err(invalid("protected installed Source changed")); }
    Ok(bytes)
}
fn invalid(error:impl std::fmt::Display)->AgentdError { AgentdError::Invalid(error.to_string()) }
