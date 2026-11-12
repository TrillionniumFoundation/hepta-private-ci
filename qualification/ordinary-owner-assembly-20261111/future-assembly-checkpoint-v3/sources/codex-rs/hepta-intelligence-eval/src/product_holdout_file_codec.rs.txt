//! Exact data encoding for a held final-holdout file. No signer or owner is
//! reconstructed by decoding these bytes; original runner validation still runs.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::FileError;
use super::MAX_MATERIAL_BYTES;
use crate::ClusterAssignment;
use crate::CrossFoldPlanReceiptV1;
use crate::HeldOutTarget;
use crate::OpeAction;
use crate::OpeRow;
use crate::OutcomeTrainingSample;
use crate::TemporalComparisonInputsV1;

const MAGIC: &[u8; 8] = b"HPFHMT01";
const MAX_ROWS: usize = 100_000;
const MAX_ACTIONS: usize = 128;
const MAX_IDS: usize = 1_000_000;

/// Encode actual supplied material. Hash the returned exact bytes into the
/// original plan before holdout observation. This pure codec creates neither
/// observations nor signatures, and grants no permission to release a file.
pub fn encode_file_final_holdout_material_v1(
    objective_digest: Digest32,
    dataset_digest: Digest32,
    final_holdout_window_id: &StableId,
    inputs: &TemporalComparisonInputsV1,
) -> Result<Vec<u8>, FileError> {
    if objective_digest.is_zero() || dataset_digest.is_zero() {
        return Err(FileError::Binding);
    }
    let mut writer = Writer(MAGIC.to_vec());
    writer.bytes(objective_digest.as_array())?;
    writer.bytes(dataset_digest.as_array())?;
    writer.id(final_holdout_window_id)?;
    writer.count(inputs.training.len(), MAX_ROWS)?;
    for row in &inputs.training {
        for id in [
            &row.decision_id,
            &row.principal_lineage,
            &row.episode_lineage,
            &row.window_id,
            &row.action_id,
        ] {
            writer.id(id)?;
        }
        writer.bytes(&row.outcome.raw().to_be_bytes())?;
        writer.bytes(&row.observed_at.to_be_bytes())?;
        writer.bytes(row.evidence_digest.as_array())?;
    }
    writer.count(inputs.targets.len(), MAX_ROWS)?;
    for row in &inputs.targets {
        for id in [
            &row.decision_id,
            &row.principal_lineage,
            &row.episode_lineage,
            &row.window_id,
        ] {
            writer.id(id)?;
        }
        writer.bytes(&row.decision_at.to_be_bytes())?;
        writer.ids(&row.actions, MAX_ACTIONS)?;
    }
    for rows in [&inputs.candidate_observations, &inputs.baseline_observations] {
        writer.count(rows.len(), MAX_ROWS)?;
        for row in rows {
            writer.id(&row.decision_id)?;
            writer.id(&row.chosen_action)?;
            writer.bytes(&[u8::from(row.complete_candidates)])?;
            writer.count(row.actions.len(), MAX_ACTIONS)?;
            for action in &row.actions {
                writer.id(&action.action_id)?;
                writer.bytes(&action.behavior_probability.raw().to_be_bytes())?;
                writer.bytes(&action.evaluation_probability.raw().to_be_bytes())?;
                writer.bytes(&action.predicted_outcome.raw().to_be_bytes())?;
            }
            match row.finalized_outcome {
                None => writer.bytes(&[0])?,
                Some(value) => {
                    writer.bytes(&[1])?;
                    writer.bytes(&value.raw().to_be_bytes())?;
                }
            }
            writer.bytes(&row.outcome_observed_at.to_be_bytes())?;
            writer.bytes(row.outcome_evidence.as_array())?;
            writer.bytes(row.outcome_model_evidence.as_array())?;
        }
    }
    writer.count(inputs.assignments.len(), MAX_ROWS)?;
    for row in &inputs.assignments {
        writer.id(&row.decision_id)?;
        writer.id(&row.cluster_id)?;
    }
    writer.ids(&inputs.snapshot_ids, MAX_IDS)?;
    writer.ids(&inputs.future_window_ids, MAX_IDS)?;
    Ok(writer.0)
}

pub(super) fn decode_original_material(
    bytes: &[u8],
    frozen: &CrossFoldPlanReceiptV1,
) -> Result<TemporalComparisonInputsV1, FileError> {
    if bytes.len() as u64 > MAX_MATERIAL_BYTES {
        return Err(FileError::Capacity);
    }
    let mut reader = Reader(bytes);
    if reader.take(8)? != MAGIC
        || reader.digest()? != frozen.objective_digest
        || reader.digest()? != frozen.dataset_digest
        || reader.id()? != frozen.final_holdout_window_id
    {
        return Err(FileError::Binding);
    }
    let count = reader.count(MAX_ROWS)?;
    let mut training = Vec::with_capacity(count);
    for _ in 0..count {
        training.push(OutcomeTrainingSample {
            decision_id: reader.id()?,
            principal_lineage: reader.id()?,
            episode_lineage: reader.id()?,
            window_id: reader.id()?,
            action_id: reader.id()?,
            outcome: reader.fixed()?,
            observed_at: reader.u64()?,
            evidence_digest: reader.digest()?,
        });
    }
    let count = reader.count(MAX_ROWS)?;
    let mut targets = Vec::with_capacity(count);
    for _ in 0..count {
        targets.push(HeldOutTarget {
            decision_id: reader.id()?,
            principal_lineage: reader.id()?,
            episode_lineage: reader.id()?,
            window_id: reader.id()?,
            decision_at: reader.u64()?,
            actions: reader.ids(MAX_ACTIONS)?,
        });
    }
    let candidate_observations = reader.observations()?;
    let baseline_observations = reader.observations()?;
    let count = reader.count(MAX_ROWS)?;
    let mut assignments = Vec::with_capacity(count);
    for _ in 0..count {
        assignments.push(ClusterAssignment {
            decision_id: reader.id()?,
            cluster_id: reader.id()?,
        });
    }
    let snapshot_ids = reader.ids(MAX_IDS)?;
    let future_window_ids = reader.ids(MAX_IDS)?;
    if !reader.0.is_empty() {
        return Err(FileError::Corrupt);
    }
    Ok(TemporalComparisonInputsV1 {
        training,
        targets,
        candidate_observations,
        baseline_observations,
        assignments,
        snapshot_ids,
        future_window_ids,
    })
}

struct Writer(Vec<u8>);

impl Writer {
    fn bytes(&mut self, bytes: &[u8]) -> Result<(), FileError> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|length| length as u64 > MAX_MATERIAL_BYTES)
        {
            return Err(FileError::Capacity);
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }

    fn count(&mut self, count: usize, limit: usize) -> Result<(), FileError> {
        if count > limit {
            return Err(FileError::Capacity);
        }
        self.bytes(&(count as u32).to_be_bytes())
    }

    fn id(&mut self, value: &StableId) -> Result<(), FileError> {
        let bytes = value.as_str().as_bytes();
        if bytes.is_empty() || bytes.len() > 128 {
            return Err(FileError::Binding);
        }
        self.bytes(&(bytes.len() as u16).to_be_bytes())?;
        self.bytes(bytes)
    }

    fn ids(&mut self, ids: &[StableId], limit: usize) -> Result<(), FileError> {
        self.count(ids.len(), limit)?;
        for id in ids {
            self.id(id)?;
        }
        Ok(())
    }
}

struct Reader<'a>(&'a [u8]);

impl Reader<'_> {
    fn take(&mut self, count: usize) -> Result<&[u8], FileError> {
        let (head, tail) = self.0.split_at_checked(count).ok_or(FileError::Corrupt)?;
        self.0 = tail;
        Ok(head)
    }

    fn u64(&mut self) -> Result<u64, FileError> {
        Ok(u64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| FileError::Corrupt)?,
        ))
    }

    fn fixed(&mut self) -> Result<FixedQ32, FileError> {
        Ok(FixedQ32::from_raw(i64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| FileError::Corrupt)?,
        )))
    }

    fn probability(&mut self) -> Result<ProbabilityQ32, FileError> {
        ProbabilityQ32::from_raw(self.u64()?).map_err(|_| FileError::Corrupt)
    }

    fn digest(&mut self) -> Result<Digest32, FileError> {
        Ok(Digest32::from_array(
            self.take(32)?.try_into().map_err(|_| FileError::Corrupt)?,
        ))
    }

    fn count(&mut self, limit: usize) -> Result<usize, FileError> {
        let count = u32::from_be_bytes(
            self.take(4)?.try_into().map_err(|_| FileError::Corrupt)?,
        ) as usize;
        if count > limit || count > self.0.len() {
            return Err(FileError::Capacity);
        }
        Ok(count)
    }

    fn id(&mut self) -> Result<StableId, FileError> {
        let count = u16::from_be_bytes(
            self.take(2)?.try_into().map_err(|_| FileError::Corrupt)?,
        ) as usize;
        if !(1..=128).contains(&count) {
            return Err(FileError::Corrupt);
        }
        let name = std::str::from_utf8(self.take(count)?).map_err(|_| FileError::Corrupt)?;
        StableId::new(name).map_err(|_| FileError::Corrupt)
    }

    fn ids(&mut self, limit: usize) -> Result<Vec<StableId>, FileError> {
        let count = self.count(limit)?;
        let mut ids = Vec::with_capacity(count);
        for _ in 0..count {
            ids.push(self.id()?);
        }
        Ok(ids)
    }

    fn observations(&mut self) -> Result<Vec<OpeRow>, FileError> {
        let count = self.count(MAX_ROWS)?;
        let mut rows = Vec::with_capacity(count);
        for _ in 0..count {
            let decision_id = self.id()?;
            let chosen_action = self.id()?;
            let complete_candidates = match self.take(1)?[0] {
                0 => false,
                1 => true,
                _ => return Err(FileError::Corrupt),
            };
            let action_count = self.count(MAX_ACTIONS)?;
            let mut actions = Vec::with_capacity(action_count);
            for _ in 0..action_count {
                actions.push(OpeAction {
                    action_id: self.id()?,
                    behavior_probability: self.probability()?,
                    evaluation_probability: self.probability()?,
                    predicted_outcome: self.fixed()?,
                });
            }
            let finalized_outcome = match self.take(1)?[0] {
                0 => None,
                1 => Some(self.fixed()?),
                _ => return Err(FileError::Corrupt),
            };
            rows.push(OpeRow {
                decision_id,
                chosen_action,
                complete_candidates,
                actions,
                finalized_outcome,
                outcome_observed_at: self.u64()?,
                outcome_evidence: self.digest()?,
                outcome_model_evidence: self.digest()?,
            });
        }
        Ok(rows)
    }
}
