//! Plan normalization and content binding before any demand, training or study
//! observation. All fields, including diagnostic and scoring protocols, are bound.

use std::collections::BTreeSet;

use crate::differentiation_types::ARMS;
use crate::differentiation_types::DifferentiationErrorV1;
use crate::differentiation_types::DifferentiationPlanRequestV1;
use crate::differentiation_types::DifferentiationPlanV1;
use crate::differentiation_types::DifferentiationTriggerV1;
use crate::differentiation_types::DigestTranscript;
use crate::differentiation_types::MAX_TASKS;
use crate::differentiation_types::PPM;
use crate::differentiation_types::require_digest;
use crate::differentiation_types::validate_actors;

pub fn freeze_differentiation_plan_v1(
    mut request: DifferentiationPlanRequestV1,
) -> Result<DifferentiationPlanV1, DifferentiationErrorV1> {
    let demand = &request.demand;
    let study = &request.study;
    let demand_ends_at_ms = demand
        .window_width_ms
        .checked_mul(u64::from(demand.required_windows))
        .and_then(|width| demand.starts_at_ms.checked_add(width))
        .ok_or(DifferentiationErrorV1::Arithmetic)?;
    request
        .parent
        .generation
        .next()
        .map_err(|_| DifferentiationErrorV1::Arithmetic)?;
    if !(2..=64).contains(&demand.required_windows)
        || demand.minimum_tasks_per_window == 0
        || usize::from(demand.required_windows) * usize::from(demand.minimum_tasks_per_window)
            > MAX_TASKS
        || demand.window_width_ms == 0
        || request.frozen_at_ms >= demand.starts_at_ms
        || demand_ends_at_ms >= study.opens_at_ms
        || study.opens_at_ms >= study.deadline_at_ms
        || request.parent.namespace == request.candidate_namespace
        || study.maximum_cost_per_arm == 0
        || study.maximum_cost_per_arm > study.maximum_total_study_cost
        || (demand.trigger == DifferentiationTriggerV1::PersistentError
            && demand.minimum_error_ppm == 0)
        || (demand.trigger == DifferentiationTriggerV1::PersistentTaskPartition
            && demand.minimum_error_ppm != 0)
        || demand.minimum_diagnosis_ppm == 0
        || study.minimum_net_gain_ppm_per_task == 0
    {
        return Err(DifferentiationErrorV1::InvalidPlan);
    }
    for value in [
        demand.minimum_error_ppm,
        demand.minimum_diagnosis_ppm,
        study.cost_penalty_ppm_per_unit,
        study.minimum_net_gain_ppm_per_task,
        study.maximum_retention_regression_ppm,
        study.maximum_migration_regression_ppm,
    ] {
        if u64::from(value) > PPM {
            return Err(DifferentiationErrorV1::InvalidPlan);
        }
    }
    for digest in [
        request.parent.artifact_digest,
        request.parent.topology_digest,
        request.parent.capability_digest,
        request.parent.state_schema_digest,
        request.parent.checkpoint_digest,
        study.cost_profile_digest,
        study.outcome_protocol_digest,
        demand.measurement_protocol_digest,
        request.compatibility_plan_digest,
        request.migration_plan_digest,
        request.rollback_plan_digest,
    ] {
        require_digest(digest)?;
    }
    validate_actors(&request.actors)?;
    if request.arm_protocols.len() != ARMS.len()
        || ARMS
            .iter()
            .any(|arm| !request.arm_protocols.contains_key(arm))
    {
        return Err(DifferentiationErrorV1::MissingComparator);
    }
    let mut protocols = BTreeSet::new();
    for digest in request.arm_protocols.values() {
        require_digest(*digest)?;
        if !protocols.insert(*digest) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
    }
    if request.new_task_ids.is_empty()
        || request.new_task_ids.len() > MAX_TASKS
        || request.retention_panels.is_empty()
        || request.retention_panels.len() > 64
    {
        return Err(DifferentiationErrorV1::Bounds);
    }
    let total_tasks = request
        .retention_panels
        .iter()
        .try_fold(request.new_task_ids.len(), |count, panel| {
            count.checked_add(panel.task_ids.len())
        })
        .ok_or(DifferentiationErrorV1::Arithmetic)?;
    if total_tasks > MAX_TASKS {
        return Err(DifferentiationErrorV1::Bounds);
    }
    request.new_task_ids.sort();
    request
        .retention_panels
        .sort_by(|a, b| a.slice_id.cmp(&b.slice_id));
    let mut tasks = BTreeSet::new();
    let mut slices = BTreeSet::new();
    for task in &request.new_task_ids {
        if !tasks.insert(task.clone()) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
    }
    for panel in &mut request.retention_panels {
        if panel.task_ids.is_empty() {
            return Err(DifferentiationErrorV1::Bounds);
        }
        if !slices.insert(panel.slice_id.clone()) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
        panel.task_ids.sort();
        for task in &panel.task_ids {
            if !tasks.insert(task.clone()) {
                return Err(DifferentiationErrorV1::DuplicateIdentity);
            }
        }
    }
    let mut binding = DigestTranscript::new(b"hepta.differentiation.plan.v1\0");
    for id in [
        &request.study_id,
        &request.module_id,
        &request.partition_id,
        &request.parent.namespace,
        &request.candidate_namespace,
    ] {
        binding.id(id);
    }
    for digest in [
        request.parent.artifact_digest,
        request.parent.topology_digest,
        request.parent.capability_digest,
        request.parent.state_schema_digest,
        request.parent.checkpoint_digest,
        study.cost_profile_digest,
        study.outcome_protocol_digest,
        demand.measurement_protocol_digest,
        request.compatibility_plan_digest,
        request.migration_plan_digest,
        request.rollback_plan_digest,
    ] {
        binding.digest(digest);
    }
    for value in [
        request.parent.generation.get(),
        request.frozen_at_ms,
        demand.starts_at_ms,
        demand.window_width_ms,
        u64::from(demand.required_windows),
        u64::from(demand.minimum_tasks_per_window),
        u64::from(demand.minimum_error_ppm),
        u64::from(demand.minimum_diagnosis_ppm),
        demand.diagnosis as u64,
        demand.trigger as u64,
        study.opens_at_ms,
        study.deadline_at_ms,
        study.maximum_cost_per_arm,
        study.maximum_total_study_cost,
        u64::from(study.cost_penalty_ppm_per_unit),
        u64::from(study.minimum_net_gain_ppm_per_task),
        u64::from(study.maximum_retention_regression_ppm),
        u64::from(study.maximum_migration_regression_ppm),
    ] {
        binding.number(value);
    }
    for (arm, digest) in &request.arm_protocols {
        binding.number(*arm as u64);
        binding.digest(*digest);
    }
    binding.number(request.new_task_ids.len() as u64);
    for task in &request.new_task_ids {
        binding.id(task);
    }
    binding.number(request.retention_panels.len() as u64);
    for panel in &request.retention_panels {
        binding.id(&panel.slice_id);
        binding.number(panel.task_ids.len() as u64);
        for task in &panel.task_ids {
            binding.id(task);
        }
    }
    for actor in [
        &request.actors.generator,
        &request.actors.evaluator,
        &request.actors.outcome_observer,
    ] {
        binding.id(&actor.principal);
        binding.digest(actor.signing_key_digest);
        binding.digest(actor.credential_chain_digest);
        binding.digest(actor.controller_digest);
    }
    Ok(DifferentiationPlanV1 {
        request,
        plan_digest: binding.finish(),
        demand_ends_at_ms,
    })
}
