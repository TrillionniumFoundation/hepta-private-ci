//! Persistent demand checks. A positive assessment supports isolated research;
//! it is not independent acceptance or a runtime admission token.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::differentiation_types::DifferentiationDiagnosisV1;
use crate::differentiation_types::DifferentiationErrorV1;
use crate::differentiation_types::DifferentiationPlanV1;
use crate::differentiation_types::DifferentiationTriggerV1;
use crate::differentiation_types::DigestTranscript;
use crate::differentiation_types::MAX_TASKS;
use crate::differentiation_types::PPM;
use crate::differentiation_types::require_digest;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationDemandCaseV1 {
    pub task_id: StableId,
    pub error_ppm: u32,
    /// The registered diagnosis protocol defines this bounded diagnostic score.
    pub diagnosis_ppm: u32,
    pub observation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationDemandWindowV1 {
    pub window_id: StableId,
    pub starts_at_ms: u64,
    pub ends_at_ms: u64,
    pub parent_artifact_digest: Digest32,
    pub parent_generation: Generation,
    pub partition_id: StableId,
    pub diagnosis: DifferentiationDiagnosisV1,
    pub measurement_protocol_digest: Digest32,
    pub cases: Vec<DifferentiationDemandCaseV1>,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DifferentiationDemandAssessmentV1 {
    pub(super) plan_digest: Digest32,
    pub(super) receipt_digest: Digest32,
    pub(super) persistent: bool,
    pub(super) source_evidence: BTreeSet<Digest32>,
}

impl DifferentiationDemandAssessmentV1 {
    pub const fn digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub const fn supports_isolated_study(&self) -> bool {
        self.persistent
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl DifferentiationPlanV1 {
    pub(super) fn task_ids(&self) -> BTreeSet<StableId> {
        self.request
            .new_task_ids
            .iter()
            .chain(self.request.retention_panels.iter().flat_map(|p| &p.task_ids))
            .cloned()
            .collect()
    }
}

pub fn assess_differentiation_demand_v1(
    plan: &DifferentiationPlanV1,
    windows: &[DifferentiationDemandWindowV1],
) -> Result<DifferentiationDemandAssessmentV1, DifferentiationErrorV1> {
    let policy = &plan.request.demand;
    if windows.len() != usize::from(policy.required_windows) {
        return Err(DifferentiationErrorV1::WindowSequence);
    }
    let total_tasks = windows
        .iter()
        .try_fold(0_usize, |count, window| count.checked_add(window.cases.len()))
        .ok_or(DifferentiationErrorV1::Arithmetic)?;
    if total_tasks > MAX_TASKS {
        return Err(DifferentiationErrorV1::Bounds);
    }
    let evaluation_tasks = plan.task_ids();
    let mut task_ids = BTreeSet::new();
    let mut window_ids = BTreeSet::new();
    let mut evidence_ids = BTreeSet::new();
    let mut persistent = true;
    let mut starts_at_ms = policy.starts_at_ms;
    let mut binding = DigestTranscript::new(b"hepta.differentiation.demand.v1\0");
    binding.digest(plan.plan_digest);
    binding.number(windows.len() as u64);
    for window in windows {
        let ends_at_ms = starts_at_ms
            .checked_add(policy.window_width_ms)
            .ok_or(DifferentiationErrorV1::Arithmetic)?;
        if window.starts_at_ms != starts_at_ms || window.ends_at_ms != ends_at_ms {
            return Err(DifferentiationErrorV1::WindowSequence);
        }
        if window.parent_artifact_digest != plan.request.parent.artifact_digest
            || window.parent_generation != plan.request.parent.generation
        {
            return Err(DifferentiationErrorV1::ParentBinding);
        }
        if window.partition_id != plan.request.partition_id
            || window.diagnosis != policy.diagnosis
            || window.measurement_protocol_digest != policy.measurement_protocol_digest
        {
            return Err(DifferentiationErrorV1::PlanBinding);
        }
        require_digest(window.evidence_digest)?;
        if !window_ids.insert(&window.window_id) || !evidence_ids.insert(window.evidence_digest) {
            return Err(DifferentiationErrorV1::DuplicateIdentity);
        }
        binding.id(&window.window_id);
        binding.id(&window.partition_id);
        binding.digest(window.parent_artifact_digest);
        binding.digest(window.measurement_protocol_digest);
        binding.digest(window.evidence_digest);
        for value in [
            window.starts_at_ms,
            window.ends_at_ms,
            window.parent_generation.get(),
            window.diagnosis as u64,
            window.cases.len() as u64,
        ] {
            binding.number(value);
        }
        let mut cases: Vec<_> = window.cases.iter().collect();
        cases.sort_by(|a, b| a.task_id.cmp(&b.task_id));
        let mut error_sum = 0_u64;
        let mut diagnosis_sum = 0_u64;
        for case in cases {
            if u64::from(case.error_ppm) > PPM || u64::from(case.diagnosis_ppm) > PPM {
                return Err(DifferentiationErrorV1::Observation);
            }
            require_digest(case.observation_digest)?;
            if !task_ids.insert(case.task_id.clone())
                || !evidence_ids.insert(case.observation_digest)
            {
                return Err(DifferentiationErrorV1::DuplicateIdentity);
            }
            if evaluation_tasks.contains(&case.task_id) {
                return Err(DifferentiationErrorV1::DataLeakage);
            }
            error_sum = error_sum
                .checked_add(u64::from(case.error_ppm))
                .ok_or(DifferentiationErrorV1::Arithmetic)?;
            diagnosis_sum = diagnosis_sum
                .checked_add(u64::from(case.diagnosis_ppm))
                .ok_or(DifferentiationErrorV1::Arithmetic)?;
            binding.id(&case.task_id);
            binding.number(u64::from(case.error_ppm));
            binding.number(u64::from(case.diagnosis_ppm));
            binding.digest(case.observation_digest);
        }
        let count = window.cases.len() as u64;
        persistent &= count >= u64::from(policy.minimum_tasks_per_window)
            && (policy.trigger == DifferentiationTriggerV1::PersistentTaskPartition
                || error_sum >= u64::from(policy.minimum_error_ppm) * count)
            && diagnosis_sum >= u64::from(policy.minimum_diagnosis_ppm) * count;
        starts_at_ms = ends_at_ms;
    }
    binding.number(u64::from(u8::from(persistent)));
    Ok(DifferentiationDemandAssessmentV1 {
        plan_digest: plan.plan_digest,
        receipt_digest: binding.finish(),
        persistent,
        source_evidence: evidence_ids,
    })
}

#[cfg(test)]
#[path = "differentiation_demand_tests.rs"]
mod tests;
