//! Deterministic comparison on a fixed measured panel. Recommendations are
//! research inputs to owner review, not statistical efficacy, authenticated
//! independent acceptance, final holdout consumption or adoption.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::differentiation_demand::DifferentiationDemandAssessmentV1;
use crate::differentiation_observations::DifferentiationStudyObservationV1;
use crate::differentiation_observations::DifferentiationTaskObservationV1;
use crate::differentiation_observations::DifferentiationTaskStatusV1;
use crate::differentiation_types::ARMS;
use crate::differentiation_types::DifferentiationArmV1;
use crate::differentiation_types::DifferentiationConclusionV1;
use crate::differentiation_types::DifferentiationErrorV1;
use crate::differentiation_types::DifferentiationHoldReasonV1;
use crate::differentiation_types::DifferentiationPlanV1;
use crate::differentiation_types::DigestTranscript;
use crate::differentiation_types::MAX_TASKS;
use crate::differentiation_types::PPM;
use crate::differentiation_types::require_digest;
use crate::differentiation_types::validate_actors;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationStudyReceiptV1 {
    pub(super) plan_digest: Digest32,
    pub(super) candidate_artifact_digest: Digest32,
    pub(super) candidate_topology_digest: Digest32,
    pub(super) conclusion: DifferentiationConclusionV1,
    pub(super) receipt_digest: Digest32,
}

impl DifferentiationStudyReceiptV1 {
    pub const fn digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub const fn conclusion(&self) -> DifferentiationConclusionV1 {
        self.conclusion
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    pub const fn candidate_artifact_digest(&self) -> Digest32 {
        self.candidate_artifact_digest
    }
}

pub fn evaluate_differentiation_study_v1(
    plan: &DifferentiationPlanV1,
    demand: &DifferentiationDemandAssessmentV1,
    observation: &DifferentiationStudyObservationV1,
) -> Result<DifferentiationStudyReceiptV1, DifferentiationErrorV1> {
    let request = &plan.request;
    let policy = &request.study;
    let candidate = &observation.candidate;
    if observation.plan_digest != plan.plan_digest
        || demand.plan_digest != plan.plan_digest
        || observation.demand_digest != demand.receipt_digest
        || observation.cost_profile_digest != policy.cost_profile_digest
        || observation.outcome_protocol_digest != policy.outcome_protocol_digest
    {
        return Err(DifferentiationErrorV1::PlanBinding);
    }
    validate_actors(&observation.actors)?;
    if observation.actors != request.actors {
        return Err(DifferentiationErrorV1::PlanBinding);
    }
    if candidate.parent_artifact_digest != request.parent.artifact_digest
        || candidate.parent_generation != request.parent.generation
    {
        return Err(DifferentiationErrorV1::ParentBinding);
    }
    let next_generation = request
        .parent
        .generation
        .next()
        .map_err(|_| DifferentiationErrorV1::Arithmetic)?;
    if candidate.generation != next_generation
        || candidate.capability_digest != request.parent.capability_digest
        || candidate.state_schema_digest != request.parent.state_schema_digest
        || candidate.namespace != request.candidate_namespace
        || candidate.artifact_digest == request.parent.artifact_digest
        || candidate.topology_digest == request.parent.topology_digest
    {
        return Err(DifferentiationErrorV1::CandidateCompatibility);
    }
    if candidate.training_started_at_ms < plan.demand_ends_at_ms
        || candidate.training_started_at_ms >= candidate.training_finished_at_ms
        || candidate.training_finished_at_ms >= observation.started_at_ms
        || observation.started_at_ms < policy.opens_at_ms
        || observation.started_at_ms >= observation.finished_at_ms
        || observation.finished_at_ms > policy.deadline_at_ms
    {
        return Err(DifferentiationErrorV1::Chronology);
    }
    if observation.arms.len() != ARMS.len() {
        return Err(DifferentiationErrorV1::MissingComparator);
    }
    if candidate.training_task_ids.is_empty()
        || candidate.training_task_ids.len() > MAX_TASKS
        || observation
            .arms
            .iter()
            .any(|arm| arm.outcomes.len() > MAX_TASKS)
        || observation.migration.outcomes.len() > MAX_TASKS
    {
        return Err(DifferentiationErrorV1::Bounds);
    }
    let expected = plan.task_ids();
    let mut binding = DigestTranscript::new(b"hepta.differentiation.study.v1\0");
    binding.digest(plan.plan_digest);
    binding.digest(demand.receipt_digest);
    binding.id(&candidate.namespace);
    for digest in [
        candidate.parent_artifact_digest,
        candidate.artifact_digest,
        candidate.topology_digest,
        candidate.capability_digest,
        candidate.state_schema_digest,
        candidate.training_evidence_digest,
    ] {
        require_digest(digest)?;
        binding.digest(digest);
    }
    for value in [
        candidate.parent_generation.get(),
        candidate.generation.get(),
        candidate.training_started_at_ms,
        candidate.training_finished_at_ms,
        observation.started_at_ms,
        observation.finished_at_ms,
        candidate.training_task_ids.len() as u64,
    ] {
        binding.number(value);
    }
    let mut training_tasks = BTreeSet::new();
    for task in &candidate.training_task_ids {
        if !training_tasks.insert(task) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
        if expected.contains(task) {
            return Err(DifferentiationErrorV1::DataLeakage);
        }
    }
    for task in training_tasks {
        binding.id(task);
    }
    let mut arms = BTreeMap::new();
    for arm in &observation.arms {
        if arms.insert(arm.arm, arm).is_some() {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
    }
    let mut evidence = demand.source_evidence.clone();
    for source in [
        plan.plan_digest,
        demand.receipt_digest,
        candidate.training_evidence_digest,
    ] {
        if !evidence.insert(source) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
    }
    let mut scores = BTreeMap::new();
    let mut net_scores = BTreeMap::new();
    let mut pending = false;
    let mut over_budget = false;
    let mut total_cost = 0_u64;
    for kind in ARMS {
        let arm = arms
            .get(&kind)
            .ok_or(DifferentiationErrorV1::MissingComparator)?;
        if arm.parent_artifact_digest != request.parent.artifact_digest
            || (kind == DifferentiationArmV1::UnchangedParent
                && arm.artifact_digest != request.parent.artifact_digest)
            || (kind == DifferentiationArmV1::Candidate
                && arm.artifact_digest != candidate.artifact_digest)
            || request.arm_protocols.get(&kind) != Some(&arm.protocol_digest)
        {
            return Err(DifferentiationErrorV1::ParentBinding);
        }
        binding.number(kind as u64);
        for digest in [
            arm.protocol_digest,
            arm.parent_artifact_digest,
            arm.artifact_digest,
            arm.evidence_digest,
        ] {
            require_digest(digest)?;
            binding.digest(digest);
        }
        if !evidence.insert(arm.evidence_digest) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
        let (panel, has_pending) =
            measure_panel(&expected, &arm.outcomes, &mut evidence, &mut binding)?;
        pending |= has_pending;
        let mut cost = 0_u64;
        for reading in [
            &arm.costs.training,
            &arm.costs.evaluation,
            &arm.costs.inference,
            &arm.costs.routing,
            &arm.costs.storage,
            &arm.costs.migration,
        ] {
            require_digest(reading.evidence_digest)?;
            if !evidence.insert(reading.evidence_digest) {
                return Err(DifferentiationErrorV1::DuplicateIdentity);
            }
            cost = cost
                .checked_add(reading.units)
                .ok_or(DifferentiationErrorV1::Arithmetic)?;
            binding.number(reading.units);
            binding.digest(reading.evidence_digest);
        }
        total_cost = total_cost
            .checked_add(cost)
            .ok_or(DifferentiationErrorV1::Arithmetic)?;
        over_budget |= cost > policy.maximum_cost_per_arm;
        let penalty = i128::from(cost)
            .checked_mul(i128::from(policy.cost_penalty_ppm_per_unit))
            .ok_or(DifferentiationErrorV1::Arithmetic)?;
        let net = i128::from(sum_scores(&request.new_task_ids, &panel)?)
            .checked_sub(penalty)
            .ok_or(DifferentiationErrorV1::Arithmetic)?;
        net_scores.insert(kind, net);
        scores.insert(kind, panel);
    }
    let migration = &observation.migration;
    if migration.candidate_artifact_digest != candidate.artifact_digest
        || migration.migration_plan_digest != request.migration_plan_digest
        || migration.rollback_plan_digest != request.rollback_plan_digest
    {
        return Err(DifferentiationErrorV1::PlanBinding);
    }
    for digest in [
        migration.candidate_artifact_digest,
        migration.migration_plan_digest,
        migration.rollback_plan_digest,
        migration.predecessor_checkpoint_digest,
        migration.restored_checkpoint_digest,
        migration.evidence_digest,
    ] {
        require_digest(digest)?;
        binding.digest(digest);
    }
    for value in [
        migration.remaining_predecessor_writers,
        migration.unresolved_effects,
        migration.replayed_external_effects,
    ] {
        binding.number(u64::from(value));
    }
    if !evidence.insert(migration.evidence_digest) {
        return Err(DifferentiationErrorV1::DuplicateIdentity);
    }
    let (migrated, migration_pending) =
        measure_panel(&expected, &migration.outcomes, &mut evidence, &mut binding)?;
    pending |= migration_pending;
    let parent_scores = scores
        .get(&DifferentiationArmV1::UnchangedParent)
        .ok_or(DifferentiationErrorV1::MissingComparator)?;
    let candidate_scores = scores
        .get(&DifferentiationArmV1::Candidate)
        .ok_or(DifferentiationErrorV1::MissingComparator)?;
    let mut retention_ok = true;
    let mut migration_quality_ok = retains(
        &request.new_task_ids,
        &migrated,
        candidate_scores,
        policy.maximum_migration_regression_ppm,
    )?;
    for panel in &request.retention_panels {
        retention_ok &= retains(
            &panel.task_ids,
            candidate_scores,
            parent_scores,
            policy.maximum_retention_regression_ppm,
        )? && retains(
            &panel.task_ids,
            &migrated,
            parent_scores,
            policy.maximum_retention_regression_ppm,
        )?;
        migration_quality_ok &= retains(
            &panel.task_ids,
            &migrated,
            candidate_scores,
            policy.maximum_migration_regression_ppm,
        )?;
    }
    let migration_ok = migration.predecessor_checkpoint_digest == request.parent.checkpoint_digest
        && migration.restored_checkpoint_digest == request.parent.checkpoint_digest
        && migration.remaining_predecessor_writers == 0
        && migration.unresolved_effects == 0
        && migration.replayed_external_effects == 0
        && migration_quality_ok;
    let required_gain = i128::from(policy.minimum_net_gain_ppm_per_task)
        .checked_mul(request.new_task_ids.len() as i128)
        .ok_or(DifferentiationErrorV1::Arithmetic)?;
    let candidate_net = net_scores
        .get(&DifferentiationArmV1::Candidate)
        .ok_or(DifferentiationErrorV1::MissingComparator)?;
    let mut improves = true;
    for (kind, net) in &net_scores {
        if *kind != DifferentiationArmV1::Candidate {
            improves &= candidate_net
                .checked_sub(*net)
                .ok_or(DifferentiationErrorV1::Arithmetic)?
                >= required_gain;
        }
    }
    use DifferentiationConclusionV1::Hold;
    use DifferentiationHoldReasonV1 as Reason;
    let conclusion = if !demand.persistent {
        Hold(Reason::InsufficientPersistentDemand)
    } else if pending {
        Hold(Reason::PendingOutcomes)
    } else if over_budget || total_cost > policy.maximum_total_study_cost {
        Hold(Reason::BudgetExceeded)
    } else if !retention_ok {
        Hold(Reason::RetentionRegression)
    } else if !migration_ok {
        Hold(Reason::MigrationUnverified)
    } else if !improves {
        Hold(Reason::NoMeasuredNetGain)
    } else {
        DifferentiationConclusionV1::RecommendForOwnerReview
    };
    match conclusion {
        Hold(reason) => {
            binding.number(0);
            binding.number(reason as u64);
        }
        DifferentiationConclusionV1::RecommendForOwnerReview => {
            binding.number(1);
        }
    }
    binding.number(0); // DENY_ALL; a study receipt is never adoption authority.
    Ok(DifferentiationStudyReceiptV1 {
        plan_digest: plan.plan_digest,
        candidate_artifact_digest: candidate.artifact_digest,
        candidate_topology_digest: candidate.topology_digest,
        conclusion,
        receipt_digest: binding.finish(),
    })
}

fn measure_panel(
    expected: &BTreeSet<StableId>,
    outcomes: &[DifferentiationTaskObservationV1],
    evidence: &mut BTreeSet<Digest32>,
    binding: &mut DigestTranscript,
) -> Result<(BTreeMap<StableId, u32>, bool), DifferentiationErrorV1> {
    if outcomes.len() != expected.len() {
        return Err(DifferentiationErrorV1::Observation);
    }
    let mut rows: Vec<_> = outcomes.iter().collect();
    rows.sort_by(|a, b| a.task_id.cmp(&b.task_id));
    let mut scores = BTreeMap::new();
    let mut pending = false;
    binding.number(outcomes.len() as u64);
    for row in rows {
        if !expected.contains(&row.task_id)
            || u64::from(row.score_ppm) > PPM
            || (row.status != DifferentiationTaskStatusV1::Completed && row.score_ppm != 0)
        {
            return Err(DifferentiationErrorV1::Observation);
        }
        require_digest(row.evidence_digest)?;
        if scores.insert(row.task_id.clone(), row.score_ppm).is_some()
            || !evidence.insert(row.evidence_digest)
        {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
        pending |= row.status == DifferentiationTaskStatusV1::Pending;
        binding.id(&row.task_id);
        binding.number(row.status as u64);
        binding.number(u64::from(row.score_ppm));
        binding.digest(row.evidence_digest);
    }
    Ok((scores, pending))
}

fn sum_scores(
    ids: &[StableId],
    scores: &BTreeMap<StableId, u32>,
) -> Result<u64, DifferentiationErrorV1> {
    ids.iter().try_fold(0_u64, |sum, id| {
        let score = scores.get(id).ok_or(DifferentiationErrorV1::Observation)?;
        sum.checked_add(u64::from(*score))
            .ok_or(DifferentiationErrorV1::Arithmetic)
    })
}

fn retains(
    ids: &[StableId],
    scores: &BTreeMap<StableId, u32>,
    baseline: &BTreeMap<StableId, u32>,
    maximum_regression_ppm: u32,
) -> Result<bool, DifferentiationErrorV1> {
    // At most MAX_TASKS bounded ppm scores: both products fit u128 exactly.
    Ok(u128::from(sum_scores(ids, scores)?) * u128::from(PPM)
        >= u128::from(sum_scores(ids, baseline)?)
            * u128::from(PPM - u64::from(maximum_regression_ppm)))
}

#[cfg(test)]
#[path = "differentiation_study_tests.rs"]
mod tests;
