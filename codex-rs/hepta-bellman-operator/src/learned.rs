//! Simplest-sufficient learned Bellman/operator candidate.
//!
//! This deterministic tabular learner fits the mean target for every cell of a
//! frozen sensor-by-action grid. It is intentionally simpler than a neural
//! operator and is preferred whenever it satisfies the same qualification
//! bounds. Missing cells and unsupported predictions fail closed. The artifact
//! remains synthetic, deny-all and qualification-only.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_ACTIONS: usize = 128;
const MAX_CELLS: usize = 262_144;
const MAX_SAMPLES: usize = 1_000_000;
const MAX_SENSORS: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularOperatorSampleV1 {
    pub sample_id: StableId,
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub target: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularOperatorPlanV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub sensor_core_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub minimum_samples_per_cell: usize,
    pub sensor_ids: Vec<StableId>,
    pub action_ids: Vec<StableId>,
    pub samples: Vec<TabularOperatorSampleV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularOperatorCellV1 {
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub sample_count: u32,
    pub mean_target: FixedQ32,
    pub minimum_target: FixedQ32,
    pub maximum_target: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularOperatorArtifactV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub sensor_core_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub cells: Vec<TabularOperatorCellV1>,
    pub artifact_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularOperatorPredictionV1 {
    pub artifact_id: StableId,
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub value: FixedQ32,
    pub cell_evidence_digest: Digest32,
    pub learned: bool,
    pub synthetic: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearnedOperatorError {
    EmptyDigest(&'static str),
    InvalidGrid,
    DuplicateIdentity(String),
    SampleLimit,
    UnknownSensor(String),
    UnknownAction(String),
    MissingCell { sensor: String, action: String },
    InsufficientCellSamples { sensor: String, action: String },
    UnsupportedCell,
    Arithmetic,
}

impl fmt::Display for LearnedOperatorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearnedOperatorError {}

#[derive(Default)]
struct CellAccumulator {
    count: usize,
    sum: i128,
    minimum: Option<FixedQ32>,
    maximum: Option<FixedQ32>,
    evidence: Vec<Digest32>,
}

pub fn fit_tabular_operator(
    mut plan: TabularOperatorPlanV1,
) -> Result<TabularOperatorArtifactV1, LearnedOperatorError> {
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
        return Err(LearnedOperatorError::InvalidGrid);
    }
    let expected_cells = plan
        .sensor_ids
        .len()
        .checked_mul(plan.action_ids.len())
        .filter(|count| *count <= MAX_CELLS)
        .ok_or(LearnedOperatorError::InvalidGrid)?;
    if plan.samples.is_empty() || plan.samples.len() > MAX_SAMPLES {
        return Err(LearnedOperatorError::SampleLimit);
    }
    normalize_ids(&mut plan.sensor_ids)?;
    normalize_ids(&mut plan.action_ids)?;
    plan.samples
        .sort_by_key(|sample| sample.sample_id.clone());
    if let Some(adjacent) = plan
        .samples
        .windows(2)
        .find(|adjacent| adjacent[0].sample_id == adjacent[1].sample_id)
    {
        return Err(LearnedOperatorError::DuplicateIdentity(
            adjacent[0].sample_id.to_string(),
        ));
    }

    let sensors = plan.sensor_ids.iter().collect::<BTreeSet<_>>();
    let actions = plan.action_ids.iter().collect::<BTreeSet<_>>();
    let mut groups: BTreeMap<(StableId, StableId), CellAccumulator> = BTreeMap::new();
    let mut sample_binding = b"hepta.bellman-operator.tabular-samples.v1".to_vec();
    for sample in &plan.samples {
        require_digest(sample.evidence_digest, "operator training sample")?;
        if !sensors.contains(&sample.sensor_id) {
            return Err(LearnedOperatorError::UnknownSensor(
                sample.sensor_id.to_string(),
            ));
        }
        if !actions.contains(&sample.action_id) {
            return Err(LearnedOperatorError::UnknownAction(
                sample.action_id.to_string(),
            ));
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
    }
    if groups.len() > expected_cells {
        return Err(LearnedOperatorError::InvalidGrid);
    }

    let mut cells = Vec::with_capacity(expected_cells);
    for sensor_id in &plan.sensor_ids {
        for action_id in &plan.action_ids {
            let key = (sensor_id.clone(), action_id.clone());
            let Some(mut group) = groups.remove(&key) else {
                return Err(LearnedOperatorError::MissingCell {
                    sensor: sensor_id.to_string(),
                    action: action_id.to_string(),
                });
            };
            if group.count < plan.minimum_samples_per_cell {
                return Err(LearnedOperatorError::InsufficientCellSamples {
                    sensor: sensor_id.to_string(),
                    action: action_id.to_string(),
                });
            }
            group.evidence.sort_unstable();
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
        }
    }
    if !groups.is_empty() {
        return Err(LearnedOperatorError::InvalidGrid);
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
    Ok(TabularOperatorArtifactV1 {
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
    })
}

pub fn predict_tabular_operator(
    artifact: &TabularOperatorArtifactV1,
    sensor_id: &StableId,
    action_id: &StableId,
) -> Result<TabularOperatorPredictionV1, LearnedOperatorError> {
    let cell = artifact
        .cells
        .iter()
        .find(|cell| &cell.sensor_id == sensor_id && &cell.action_id == action_id)
        .ok_or(LearnedOperatorError::UnsupportedCell)?;
    Ok(TabularOperatorPredictionV1 {
        artifact_id: artifact.artifact_id.clone(),
        sensor_id: cell.sensor_id.clone(),
        action_id: cell.action_id.clone(),
        value: cell.mean_target,
        cell_evidence_digest: cell.evidence_digest,
        learned: true,
        synthetic: true,
        authority: AuthorityPosture::DENY_ALL,
    })
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

fn normalize_ids(values: &mut Vec<StableId>) -> Result<(), LearnedOperatorError> {
    values.sort();
    if let Some(adjacent) = values
        .windows(2)
        .find(|adjacent| adjacent[0] == adjacent[1])
    {
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

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), LearnedOperatorError> {
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
#[path = "learned_tests.rs"]
mod tests;
