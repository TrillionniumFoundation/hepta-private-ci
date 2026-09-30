//! Resource-metered canonical tabular fitting for owner-authenticated paths.
//!
//! This additive V2 fitter preserves the V1 artifact schema while preflighting
//! exact grid/sample bounds, estimated resident bytes, canonical-sort work, and
//! one absolute deadline. Global evidence uniqueness uses one sorted vector
//! rather than a tree plus duplicate per-node allocations.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::LearnedOperatorError;
use crate::OperatorResourceBudgetV1;
use crate::OperatorWorkErrorV1;
use crate::OperatorWorkMeter;
use crate::OperatorWorkSnapshotV1;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorCellV1;
use crate::TabularOperatorPlanV1;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;
use crate::sort_work;

const MAX_ACTIONS: usize = 128;
const MAX_CELLS: usize = 262_144;
const MAX_SAMPLES: usize = 1_000_000;
const MAX_SENSORS: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularFitReceiptV2 {
    pub artifact: TabularOperatorArtifactV1,
    pub work: OperatorWorkSnapshotV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BudgetedTabularFitErrorV2 {
    Work(OperatorWorkErrorV1),
    Domain(LearnedOperatorError),
}

impl fmt::Display for BudgetedTabularFitErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for BudgetedTabularFitErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Work(error) => Some(error),
            Self::Domain(error) => Some(error),
        }
    }
}

impl From<OperatorWorkErrorV1> for BudgetedTabularFitErrorV2 {
    fn from(value: OperatorWorkErrorV1) -> Self {
        Self::Work(value)
    }
}

impl From<LearnedOperatorError> for BudgetedTabularFitErrorV2 {
    fn from(value: LearnedOperatorError) -> Self {
        Self::Domain(value)
    }
}

#[derive(Default)]
struct CellAccumulator {
    count: usize,
    sum: i128,
    minimum: Option<FixedQ32>,
    maximum: Option<FixedQ32>,
    evidence: Vec<Digest32>,
}

pub fn fit_tabular_operator_bounded_v2(
    mut plan: TabularOperatorPlanV1,
    budget: OperatorResourceBudgetV1,
) -> Result<TabularFitReceiptV2, BudgetedTabularFitErrorV2> {
    for (label, digest) in [
        ("operator objective", plan.objective_digest),
        ("operator dataset", plan.dataset_digest),
        ("operator sensor core", plan.sensor_core_digest),
        ("operator training profile", plan.training_profile_digest),
    ] {
        require_digest(digest, label)?;
    }
    if plan.sensor_ids.is_empty()
        || plan.sensor_ids.len() > MAX_SENSORS
        || plan.action_ids.is_empty()
        || plan.action_ids.len() > MAX_ACTIONS
        || plan.minimum_samples_per_cell == 0
        || plan.minimum_samples_per_cell > MAX_SAMPLES
    {
        return Err(LearnedOperatorError::InvalidGrid.into());
    }
    let expected_cells = plan
        .sensor_ids
        .len()
        .checked_mul(plan.action_ids.len())
        .filter(|count| *count <= MAX_CELLS)
        .ok_or(LearnedOperatorError::InvalidGrid)?;
    let required_samples = expected_cells
        .checked_mul(plan.minimum_samples_per_cell)
        .ok_or(LearnedOperatorError::Arithmetic)?;
    if plan.samples.is_empty()
        || plan.samples.len() > MAX_SAMPLES
        || plan.samples.len() < required_samples
    {
        return Err(LearnedOperatorError::SampleLimit.into());
    }

    let mut meter = OperatorWorkMeter::new(budget)?;
    let sample_count = checked_u64(plan.samples.len())?;
    let cell_count = checked_u64(expected_cells)?;
    let sort_operations = checked_add(sort_work(plan.samples.len())?, sort_work(plan.samples.len())?)?;
    let loop_operations = checked_add(checked_mul(sample_count, 8)?, checked_mul(cell_count, 4)?)?;
    meter.preflight_operations(checked_add(sort_operations, loop_operations)?)?;
    meter.reserve_total_bytes(estimate_fit_bytes(&plan, expected_cells)?)?;

    normalize_ids(&mut plan.sensor_ids)?;
    normalize_ids(&mut plan.action_ids)?;
    plan.samples.sort_by_key(|sample| sample.sample_id.clone());
    meter.consume(sort_work(plan.samples.len())?)?;
    if let Some(adjacent) = plan
        .samples
        .windows(2)
        .find(|pair| pair[0].sample_id == pair[1].sample_id)
    {
        return Err(LearnedOperatorError::DuplicateIdentity(
            adjacent[0].sample_id.to_string(),
        )
        .into());
    }

    let mut evidence = plan
        .samples
        .iter()
        .map(|sample| sample.evidence_digest)
        .collect::<Vec<_>>();
    evidence.sort_unstable();
    meter.consume(sort_work(evidence.len())?)?;
    if evidence.iter().any(Digest32::is_zero) {
        return Err(LearnedOperatorError::EmptyDigest("operator training sample").into());
    }
    if evidence.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(LearnedOperatorError::DuplicateEvidence.into());
    }

    let sensors = plan.sensor_ids.iter().collect::<BTreeSet<_>>();
    let actions = plan.action_ids.iter().collect::<BTreeSet<_>>();
    let mut groups = BTreeMap::<(StableId, StableId), CellAccumulator>::new();
    let mut sample_binding = b"hepta.bellman-operator.tabular-samples.v1".to_vec();
    for (index, sample) in plan.samples.iter().enumerate() {
        if !sensors.contains(&sample.sensor_id) {
            return Err(LearnedOperatorError::UnknownSensor(
                sample.sensor_id.to_string(),
            )
            .into());
        }
        if !actions.contains(&sample.action_id) {
            return Err(LearnedOperatorError::UnknownAction(
                sample.action_id.to_string(),
            )
            .into());
        }
        let group = groups
            .entry((sample.sensor_id.clone(), sample.action_id.clone()))
            .or_default();
        group.count = group
            .count
            .checked_add(1)
            .ok_or(LearnedOperatorError::Arithmetic)?;
        group.sum = group
            .sum
            .checked_add(i128::from(sample.target.raw()))
            .ok_or(LearnedOperatorError::Arithmetic)?;
        group.minimum = Some(
            group
                .minimum
                .map_or(sample.target, |current| current.min(sample.target)),
        );
        group.maximum = Some(
            group
                .maximum
                .map_or(sample.target, |current| current.max(sample.target)),
        );
        group.evidence.push(sample.evidence_digest);
        push_id(&mut sample_binding, &sample.sample_id);
        push_id(&mut sample_binding, &sample.sensor_id);
        push_id(&mut sample_binding, &sample.action_id);
        sample_binding.extend_from_slice(&sample.target.raw().to_be_bytes());
        sample_binding.extend_from_slice(sample.evidence_digest.as_array());
        meter.consume(8)?;
        if index % 256 == 0 {
            meter.checkpoint()?;
        }
    }
    if groups.len() > expected_cells {
        return Err(LearnedOperatorError::InvalidGrid.into());
    }

    let mut cells = Vec::with_capacity(expected_cells);
    for sensor_id in &plan.sensor_ids {
        for action_id in &plan.action_ids {
            let key = (sensor_id.clone(), action_id.clone());
            let Some(mut group) = groups.remove(&key) else {
                return Err(LearnedOperatorError::MissingCell {
                    sensor: sensor_id.to_string(),
                    action: action_id.to_string(),
                }
                .into());
            };
            if group.count < plan.minimum_samples_per_cell {
                return Err(LearnedOperatorError::InsufficientCellSamples {
                    sensor: sensor_id.to_string(),
                    action: action_id.to_string(),
                }
                .into());
            }
            group.evidence.sort_unstable();
            meter.consume(sort_work(group.evidence.len())?)?;
            let mean_raw = round_ratio(
                group.sum,
                i128::try_from(group.count).map_err(|_| LearnedOperatorError::Arithmetic)?,
            )?;
            let mean_target = FixedQ32::from_raw(
                i64::try_from(mean_raw).map_err(|_| LearnedOperatorError::Arithmetic)?,
            );
            let minimum_target = group.minimum.ok_or(LearnedOperatorError::Arithmetic)?;
            let maximum_target = group.maximum.ok_or(LearnedOperatorError::Arithmetic)?;
            let evidence_digest = digest_cell(
                sensor_id,
                action_id,
                group.count,
                mean_target,
                minimum_target,
                maximum_target,
                &group.evidence,
            )?;
            cells.push(TabularOperatorCellV1 {
                sensor_id: sensor_id.clone(),
                action_id: action_id.clone(),
                sample_count: u32::try_from(group.count)
                    .map_err(|_| LearnedOperatorError::Arithmetic)?,
                mean_target,
                minimum_target,
                maximum_target,
                evidence_digest,
            });
            meter.consume(4)?;
        }
    }
    if !groups.is_empty() {
        return Err(LearnedOperatorError::InvalidGrid.into());
    }

    let sample_digest = Digest32::of_bytes(&sample_binding);
    let mut artifact_bytes = b"hepta.bellman-operator.tabular-artifact.v1".to_vec();
    push_id(&mut artifact_bytes, &plan.artifact_id);
    push_id(&mut artifact_bytes, &plan.producer_id);
    artifact_bytes.extend_from_slice(&plan.generation.get().to_be_bytes());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.sensor_core_digest,
        plan.training_profile_digest,
        sample_digest,
    ] {
        artifact_bytes.extend_from_slice(digest.as_array());
    }
    artifact_bytes.extend_from_slice(
        &u32::try_from(cells.len())
            .map_err(|_| LearnedOperatorError::Arithmetic)?
            .to_be_bytes(),
    );
    for cell in &cells {
        artifact_bytes.extend_from_slice(cell.evidence_digest.as_array());
    }
    let artifact = TabularOperatorArtifactV1 {
        artifact_id: plan.artifact_id,
        producer_id: plan.producer_id,
        generation: plan.generation,
        objective_digest: plan.objective_digest,
        dataset_digest: plan.dataset_digest,
        sensor_core_digest: plan.sensor_core_digest,
        training_profile_digest: plan.training_profile_digest,
        cells,
        artifact_digest: Digest32::of_bytes(&artifact_bytes),
        authority: AuthorityPosture::DENY_ALL,
    };
    let work = meter.finish()?;
    let mut receipt_bytes = b"hepta.bellman-operator.tabular-fit-receipt.v2\0".to_vec();
    receipt_bytes.extend_from_slice(artifact.artifact_digest.as_array());
    receipt_bytes.extend_from_slice(&work.operations.to_be_bytes());
    receipt_bytes.extend_from_slice(&work.estimated_bytes.to_be_bytes());
    Ok(TabularFitReceiptV2 {
        artifact,
        work,
        receipt_digest: Digest32::of_bytes(&receipt_bytes),
    })
}

fn estimate_fit_bytes(
    plan: &TabularOperatorPlanV1,
    expected_cells: usize,
) -> Result<u64, OperatorWorkErrorV1> {
    let mut id_bytes = 0_u64;
    for value in plan
        .sensor_ids
        .iter()
        .chain(&plan.action_ids)
        .chain(plan.samples.iter().flat_map(|sample| {
            [&sample.sample_id, &sample.sensor_id, &sample.action_id]
        }))
    {
        id_bytes = checked_add(id_bytes, checked_u64(value.as_str().len())?)?;
    }
    let samples = checked_u64(plan.samples.len())?;
    let cells = checked_u64(expected_cells)?;
    let sample_structs = checked_mul(
        samples,
        u64::try_from(std::mem::size_of::<crate::TabularOperatorSampleV1>())
            .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
    )?;
    let cell_structs = checked_mul(
        cells,
        u64::try_from(std::mem::size_of::<TabularOperatorCellV1>())
            .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
    )?;
    let evidence = checked_mul(samples, 64)?;
    let sample_binding = checked_mul(samples, 128)?;
    checked_add(
        checked_add(checked_add(id_bytes, sample_structs)?, cell_structs)?,
        checked_add(evidence, sample_binding)?,
    )
}

fn digest_cell(
    sensor_id: &StableId,
    action_id: &StableId,
    count: usize,
    mean: FixedQ32,
    minimum: FixedQ32,
    maximum: FixedQ32,
    evidence: &[Digest32],
) -> Result<Digest32, LearnedOperatorError> {
    let mut bytes = b"hepta.bellman-operator.tabular-cell.v1".to_vec();
    push_id(&mut bytes, sensor_id);
    push_id(&mut bytes, action_id);
    bytes.extend_from_slice(
        &u32::try_from(count)
            .map_err(|_| LearnedOperatorError::Arithmetic)?
            .to_be_bytes(),
    );
    for value in [mean, minimum, maximum] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(
        &u32::try_from(evidence.len())
            .map_err(|_| LearnedOperatorError::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in evidence {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn normalize_ids(values: &mut [StableId]) -> Result<(), LearnedOperatorError> {
    values.sort();
    if let Some(adjacent) = values.windows(2).find(|pair| pair[0] == pair[1]) {
        return Err(LearnedOperatorError::DuplicateIdentity(
            adjacent[0].to_string(),
        ));
    }
    Ok(())
}

fn round_ratio(numerator: i128, denominator: i128) -> Result<i128, LearnedOperatorError> {
    if denominator <= 0 {
        return Err(LearnedOperatorError::Arithmetic);
    }
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let twice = remainder
        .checked_abs()
        .and_then(|value| value.checked_mul(2))
        .ok_or(LearnedOperatorError::Arithmetic)?;
    if twice > denominator || (twice == denominator && quotient % 2 != 0) {
        quotient
            .checked_add(numerator.signum())
            .ok_or(LearnedOperatorError::Arithmetic)
    } else {
        Ok(quotient)
    }
}

fn require_digest(
    digest: Digest32,
    label: &'static str,
) -> Result<(), LearnedOperatorError> {
    if digest.is_zero() {
        return Err(LearnedOperatorError::EmptyDigest(label));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn plan() -> TabularOperatorPlanV1 {
        TabularOperatorPlanV1 {
            artifact_id: id("artifact"),
            producer_id: id("producer"),
            generation: Generation::new(1).unwrap(),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            sensor_core_digest: digest("sensor"),
            training_profile_digest: digest("training"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![id("sensor")],
            action_ids: vec![id("action")],
            samples: vec![crate::TabularOperatorSampleV1 {
                sample_id: id("sample"),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(7),
                evidence_digest: digest("evidence"),
            }],
        }
    }

    #[test]
    fn bounded_fit_matches_v1_artifact_identity() {
        let expected = crate::fit_tabular_operator(plan()).unwrap();
        let actual = fit_tabular_operator_bounded_v2(
            plan(),
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap();
        assert_eq!(actual.artifact, expected);
        assert!(actual.work.operations > 0);
    }

    #[test]
    fn byte_budget_rejects_before_fit() {
        let result = fit_tabular_operator_bounded_v2(
            plan(),
            OperatorResourceBudgetV1 {
                max_operations: 1_000,
                max_estimated_bytes: 1,
                max_elapsed_micros: 1_000_000,
            },
        );
        assert!(matches!(
            result,
            Err(BudgetedTabularFitErrorV2::Work(
                OperatorWorkErrorV1::ResourceExhausted { .. }
            ))
        ));
    }
}
