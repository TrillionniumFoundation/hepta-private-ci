//! Full-candidate budget competition that only emits topology proposals.
//!
//! Costs are explicitly weighted measurement units, never claimed dollars or
//! FLOPs. Missing measurements and non-positive net benefit preserve NoChange.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::TopologyOperationV2;
use crate::TopologyProposalRequestV2;
use crate::TopologyProposalV2;
use crate::propose_topology_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryStructureRoleV1 {
    KeepFixed,
    Fixed,
    Split,
    Merge,
}

/// Runtime payload measurements count raw and decoded copies. `catalog_bytes`
/// and `route_bytes` are breakdowns already contained in artifacts/metadata.
/// Exclusive read compute excludes wakes and transport. Absent costs are
/// unknown; zero is permitted only when the producer actually measured zero.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryStructureCostV1 {
    pub artifact_bytes: u64,
    pub raw_cache_bytes: u64,
    pub resident_payload_bytes: u64,
    pub resident_metadata_bytes: u64,
    pub catalog_bytes: u64,
    pub route_bytes: u64,
    pub source_ledger_bytes: Option<u64>,
    pub search_wall_ns: Option<u64>,
    pub training_wall_ns: Option<u64>,
    pub replay_wall_ns: Option<u64>,
    pub read_compute_wall_ns: Option<u64>,
    pub wake_wall_ns: Option<u64>,
    pub communication_wall_ns: Option<u64>,
    pub communication_bytes: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryStructureMeasurementV1 {
    pub artifact_digest: Digest32,
    pub source_cut_digest: Digest32,
    pub task_set_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub role: MemoryStructureRoleV1,
    pub shards: u8,
    pub queries: u64,
    pub errors: u64,
    pub retention_queries: u64,
    pub retention_errors: u64,
    pub independent_evaluation: bool,
    pub cost: MemoryStructureCostV1,
}

/// Freeze this complete vector and fixed candidate inventory before evaluating
/// any candidate. Every fixed structure must receive the same data and limits.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryStructureBudgetV1 {
    pub required_fixed_shards: Vec<u8>,
    pub max_artifact_bytes: u64,
    pub max_resident_payload_bytes: u64,
    pub forecast_queries: u64,
    pub max_retention_error_permyriad: u64,
    pub error_weight: u64,
    pub byte_weight: u64,
    pub wall_ns_weight: u64,
    pub communication_byte_weight: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryStructureKeepReasonV1 {
    MissingMeasurements,
    MissingIndependentEvaluation,
    NoFeasibleFixed,
    NoPositiveNetBenefit,
    PositiveNetBenefit,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryStructureBudgetErrorV1 {
    InvalidInventory,
    IncomparableData,
    InvalidMeasurement,
    Arithmetic,
    ProposalBinding,
    Topology(String),
}

impl fmt::Display for MemoryStructureBudgetErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for MemoryStructureBudgetErrorV1 {}

/// Opaque result: callers cannot fabricate an accepted gate by setting fields.
/// A positive result is still only evidence for independent topology review.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryStructureDecisionV1 {
    keep_digest: Digest32,
    best_fixed: Option<Digest32>,
    proposed: Option<(Digest32, MemoryStructureRoleV1)>,
    evidence_digest: Digest32,
    reason: MemoryStructureKeepReasonV1,
    full_search_score: Option<u128>,
    best_fixed_score: Option<u128>,
}

impl MemoryStructureDecisionV1 {
    pub fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }
    pub fn best_fixed_digest(&self) -> Option<Digest32> {
        self.best_fixed
    }
    pub fn proposed_digest(&self) -> Option<Digest32> {
        self.proposed.map(|item| item.0)
    }
    pub fn reason(&self) -> MemoryStructureKeepReasonV1 {
        self.reason
    }
    pub fn full_search_score(&self) -> Option<u128> {
        self.full_search_score
    }
    pub fn best_fixed_score(&self) -> Option<u128> {
        self.best_fixed_score
    }
}

/// Compare structural candidates to the strongest feasible fixed candidate.
/// Adaptive cost charges all candidate artifacts/search/training/replay. The
/// fixed comparator is deliberately favored by charging only its own costs.
pub fn evaluate_memory_structure_v1(
    budget: &MemoryStructureBudgetV1,
    measurements: &[MemoryStructureMeasurementV1],
) -> Result<MemoryStructureDecisionV1, MemoryStructureBudgetErrorV1> {
    validate(budget, measurements)?;
    let keep = measurements
        .iter()
        .find(|item| item.role == MemoryStructureRoleV1::KeepFixed)
        .ok_or(MemoryStructureBudgetErrorV1::InvalidInventory)?;
    let mut result = MemoryStructureDecisionV1 {
        keep_digest: keep.artifact_digest,
        best_fixed: None,
        proposed: None,
        evidence_digest: evidence(budget, measurements),
        reason: MemoryStructureKeepReasonV1::NoPositiveNetBenefit,
        full_search_score: None,
        best_fixed_score: None,
    };
    if measurements.iter().any(|item| !item.independent_evaluation) {
        result.reason = MemoryStructureKeepReasonV1::MissingIndependentEvaluation;
        return Ok(result);
    }
    if measurements
        .iter()
        .any(|item| options(&item.cost).contains(&None))
    {
        result.reason = MemoryStructureKeepReasonV1::MissingMeasurements;
        return Ok(result);
    }
    let ledger = keep
        .cost
        .source_ledger_bytes
        .ok_or(MemoryStructureBudgetErrorV1::InvalidMeasurement)?;
    if measurements
        .iter()
        .any(|item| item.cost.source_ledger_bytes != Some(ledger))
    {
        return Err(MemoryStructureBudgetErrorV1::IncomparableData);
    }
    let mut all_upfront = weighted(ledger, budget.byte_weight)?;
    for item in measurements {
        all_upfront = add(all_upfront, upfront(budget, &item.cost)?)?;
    }
    let mut fixed = Vec::new();
    let mut adaptive = Vec::new();
    for item in measurements {
        if !feasible(budget, item) {
            continue;
        }
        let recurring = recurring(budget, item)?;
        match item.role {
            MemoryStructureRoleV1::KeepFixed | MemoryStructureRoleV1::Fixed => fixed.push((
                add(
                    add(
                        upfront(budget, &item.cost)?,
                        weighted(ledger, budget.byte_weight)?,
                    )?,
                    recurring,
                )?,
                item.artifact_digest,
            )),
            _ => adaptive.push((
                add(all_upfront, recurring)?,
                item.artifact_digest,
                item.role,
            )),
        }
    }
    fixed.sort();
    adaptive.sort_by_key(|item| (item.0, item.1));
    let Some((fixed_score, fixed_digest)) = fixed.first().copied() else {
        result.reason = MemoryStructureKeepReasonV1::NoFeasibleFixed;
        return Ok(result);
    };
    result.best_fixed = Some(fixed_digest);
    result.best_fixed_score = Some(fixed_score);
    if let Some((score, digest, role)) = adaptive.first().copied() {
        result.full_search_score = Some(score);
        if score < fixed_score {
            result.reason = MemoryStructureKeepReasonV1::PositiveNetBenefit;
            result.proposed = Some((digest, role));
        }
    }
    Ok(result)
}

/// Bind a measured decision to the existing proposal-only contract. On a
/// failed gate, even caller-supplied mutations are replaced by NoChange. On a
/// passing gate, activation still requires the independent release pipeline.
pub fn propose_memory_structure_v1(
    mut request: TopologyProposalRequestV2,
    decision: &MemoryStructureDecisionV1,
) -> Result<TopologyProposalV2, MemoryStructureBudgetErrorV1> {
    if request.selected_artifact_digest != decision.keep_digest
        || request.evaluation_digest != decision.evidence_digest
    {
        return Err(MemoryStructureBudgetErrorV1::ProposalBinding);
    }
    match decision.proposed {
        None => request.changes.clear(),
        Some((digest, role)) => {
            let operation = if role == MemoryStructureRoleV1::Split {
                TopologyOperationV2::Split
            } else {
                TopologyOperationV2::Merge
            };
            if request.changes.len() != 1
                || request.changes.iter().any(|change| {
                    change.operation != operation
                        || change.candidate_digest != Some(digest)
                        || change.predecessor_digest != Some(decision.keep_digest)
                        || change.resource_review_digest != decision.evidence_digest
                        || change.evidence_digest != decision.evidence_digest
                })
            {
                return Err(MemoryStructureBudgetErrorV1::ProposalBinding);
            }
        }
    }
    propose_topology_v2(request)
        .map_err(|error| MemoryStructureBudgetErrorV1::Topology(error.to_string()))
}

fn feasible(budget: &MemoryStructureBudgetV1, item: &MemoryStructureMeasurementV1) -> bool {
    item.cost.artifact_bytes <= budget.max_artifact_bytes
        && item.cost.resident_payload_bytes <= budget.max_resident_payload_bytes
        && u128::from(item.retention_errors) * 10_000
            <= u128::from(item.retention_queries) * u128::from(budget.max_retention_error_permyriad)
}

fn options(cost: &MemoryStructureCostV1) -> [Option<u64>; 8] {
    [
        cost.source_ledger_bytes,
        cost.search_wall_ns,
        cost.training_wall_ns,
        cost.replay_wall_ns,
        cost.read_compute_wall_ns,
        cost.wake_wall_ns,
        cost.communication_wall_ns,
        cost.communication_bytes,
    ]
}

fn upfront(
    budget: &MemoryStructureBudgetV1,
    cost: &MemoryStructureCostV1,
) -> Result<u128, MemoryStructureBudgetErrorV1> {
    let mut total = 0;
    for bytes in [
        cost.artifact_bytes,
        cost.raw_cache_bytes,
        cost.resident_payload_bytes,
        cost.resident_metadata_bytes,
    ] {
        total = add(total, weighted(bytes, budget.byte_weight)?)?;
    }
    for duration in [
        cost.search_wall_ns,
        cost.training_wall_ns,
        cost.replay_wall_ns,
    ] {
        total = add(
            total,
            weighted(
                duration.ok_or(MemoryStructureBudgetErrorV1::InvalidMeasurement)?,
                budget.wall_ns_weight,
            )?,
        )?;
    }
    Ok(total)
}

fn recurring(
    budget: &MemoryStructureBudgetV1,
    item: &MemoryStructureMeasurementV1,
) -> Result<u128, MemoryStructureBudgetErrorV1> {
    let mut total = weighted(item.errors, budget.error_weight)?;
    for duration in [
        item.cost.read_compute_wall_ns,
        item.cost.wake_wall_ns,
        item.cost.communication_wall_ns,
    ] {
        total = add(
            total,
            weighted(
                duration.ok_or(MemoryStructureBudgetErrorV1::InvalidMeasurement)?,
                budget.wall_ns_weight,
            )?,
        )?;
    }
    total = add(
        total,
        weighted(
            item.cost
                .communication_bytes
                .ok_or(MemoryStructureBudgetErrorV1::InvalidMeasurement)?,
            budget.communication_byte_weight,
        )?,
    )?;
    let forecast = total
        .checked_mul(u128::from(budget.forecast_queries))
        .ok_or(MemoryStructureBudgetErrorV1::Arithmetic)?;
    Ok(add(forecast, u128::from(item.queries - 1))? / u128::from(item.queries))
}

fn validate(
    budget: &MemoryStructureBudgetV1,
    items: &[MemoryStructureMeasurementV1],
) -> Result<(), MemoryStructureBudgetErrorV1> {
    let fixed: BTreeSet<_> = items
        .iter()
        .filter(|item| item.role == MemoryStructureRoleV1::Fixed)
        .map(|item| item.shards)
        .collect();
    if items.is_empty()
        || items.len() > 32
        || budget.required_fixed_shards.is_empty()
        || budget
            .required_fixed_shards
            .iter()
            .any(|count| !(1..=8).contains(count))
        || budget.required_fixed_shards != fixed.into_iter().collect::<Vec<_>>()
        || items
            .iter()
            .filter(|item| item.role == MemoryStructureRoleV1::KeepFixed)
            .count()
            != 1
        || budget.forecast_queries == 0
        || budget.error_weight == 0
        || budget.byte_weight == 0
        || budget.wall_ns_weight == 0
        || budget.communication_byte_weight == 0
        || budget.max_retention_error_permyriad > 10_000
    {
        return Err(MemoryStructureBudgetErrorV1::InvalidInventory);
    }
    let first = &items[0];
    let keep_shards = items
        .iter()
        .find(|item| item.role == MemoryStructureRoleV1::KeepFixed)
        .ok_or(MemoryStructureBudgetErrorV1::InvalidInventory)?
        .shards;
    let mut identities = BTreeSet::new();
    for item in items {
        if item.artifact_digest.is_zero()
            || !identities.insert(item.artifact_digest)
            || item.source_cut_digest.is_zero()
            || item.task_set_digest.is_zero()
            || item.training_profile_digest.is_zero()
            || !(1..=8).contains(&item.shards)
            || (item.role == MemoryStructureRoleV1::Split && item.shards <= keep_shards)
            || (item.role == MemoryStructureRoleV1::Merge && item.shards >= keep_shards)
            || item.queries == 0
            || item.errors > item.queries
            || item.retention_queries == 0
            || item.retention_errors > item.retention_queries
            || item.cost.artifact_bytes < item.cost.catalog_bytes
            || item.cost.artifact_bytes < item.cost.route_bytes
        {
            return Err(MemoryStructureBudgetErrorV1::InvalidMeasurement);
        }
        if item.source_cut_digest != first.source_cut_digest
            || item.task_set_digest != first.task_set_digest
            || item.training_profile_digest != first.training_profile_digest
            || item.queries != first.queries
            || item.retention_queries != first.retention_queries
        {
            return Err(MemoryStructureBudgetErrorV1::IncomparableData);
        }
    }
    Ok(())
}

fn weighted(value: u64, weight: u64) -> Result<u128, MemoryStructureBudgetErrorV1> {
    Ok(u128::from(value) * u128::from(weight))
}
fn add(left: u128, right: u128) -> Result<u128, MemoryStructureBudgetErrorV1> {
    left.checked_add(right)
        .ok_or(MemoryStructureBudgetErrorV1::Arithmetic)
}

fn evidence(budget: &MemoryStructureBudgetV1, items: &[MemoryStructureMeasurementV1]) -> Digest32 {
    let mut bytes = b"hepta.memory.structure-cost.v1".to_vec();
    for value in [
        budget.max_artifact_bytes,
        budget.max_resident_payload_bytes,
        budget.forecast_queries,
        budget.max_retention_error_permyriad,
        budget.error_weight,
        budget.byte_weight,
        budget.wall_ns_weight,
        budget.communication_byte_weight,
    ] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes.push(budget.required_fixed_shards.len() as u8);
    bytes.extend_from_slice(&budget.required_fixed_shards);
    for item in items {
        for digest in [
            item.artifact_digest,
            item.source_cut_digest,
            item.task_set_digest,
            item.training_profile_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&[
            item.role as u8,
            item.shards,
            u8::from(item.independent_evaluation),
        ]);
        for value in [
            item.queries,
            item.errors,
            item.retention_queries,
            item.retention_errors,
            item.cost.artifact_bytes,
            item.cost.raw_cache_bytes,
            item.cost.resident_payload_bytes,
            item.cost.resident_metadata_bytes,
            item.cost.catalog_bytes,
            item.cost.route_bytes,
        ] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        for value in options(&item.cost) {
            bytes.push(u8::from(value.is_some()));
            bytes.extend_from_slice(&value.unwrap_or_default().to_le_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "memory_budget_tests.rs"]
mod tests;
