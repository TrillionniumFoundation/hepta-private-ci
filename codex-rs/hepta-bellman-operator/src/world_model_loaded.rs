//! Authenticated persisted loading for the deterministic tabular world model.
//!
//! Public `TabularWorldModelV1` values are mutable caller-owned Rust values.
//! Repeated prediction should instead use this once-validated private wrapper,
//! admitted from immutable bytes plus an independently held host pin.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::TabularWorldModelV1;
use crate::TransitionBranchV1;
use crate::TransitionEstimateV1;
use crate::WorldModelPredictionV1;
use crate::world_model::MAX_BRANCHES_PER_STATE_ACTION;
use crate::world_model::MAX_SAMPLES;
use crate::world_model::MAX_STATE_ACTIONS;
use crate::world_model::validate_world_model_structure;

const MAGIC: &[u8; 8] = b"HEPTWM01";
const MAX_BYTES: usize = 64 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularWorldModelPinV1 {
    pub payload_digest: Digest32,
    pub model_digest: Digest32,
    pub dataset_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorldModelPayloadError {
    Bounds,
    Encoding,
    Binding,
    InvalidModel,
    UnsupportedStateAction,
}

impl fmt::Display for WorldModelPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WorldModelPayloadError {}

#[derive(Clone, Debug)]
pub struct LoadedTabularWorldModelV1 {
    model: TabularWorldModelV1,
}

impl LoadedTabularWorldModelV1 {
    pub fn from_pinned_payload(
        payload: &[u8],
        pin: &TabularWorldModelPinV1,
    ) -> Result<Self, WorldModelPayloadError> {
        if payload.is_empty() || payload.len() > MAX_BYTES {
            return Err(WorldModelPayloadError::Bounds);
        }
        if pin.payload_digest.is_zero()
            || pin.model_digest.is_zero()
            || pin.dataset_digest.is_zero()
            || Digest32::of_bytes(payload) != pin.payload_digest
        {
            return Err(WorldModelPayloadError::Binding);
        }
        let model = decode(payload)?;
        validate_world_model_structure(&model)
            .map_err(|_| WorldModelPayloadError::InvalidModel)?;
        if model.model_digest != pin.model_digest || model.dataset_digest != pin.dataset_digest {
            return Err(WorldModelPayloadError::Binding);
        }
        Ok(Self { model })
    }

    pub fn model_id(&self) -> &StableId {
        &self.model.model_id
    }

    pub fn model_digest(&self) -> Digest32 {
        self.model.model_digest
    }

    pub fn dataset_digest(&self) -> Digest32 {
        self.model.dataset_digest
    }

    pub fn predict(
        &self,
        state_id: &StableId,
        action_id: &StableId,
    ) -> Result<WorldModelPredictionV1, WorldModelPayloadError> {
        let index = self
            .model
            .estimates
            .binary_search_by(|estimate| {
                (&estimate.state_id, &estimate.action_id).cmp(&(state_id, action_id))
            })
            .map_err(|_| WorldModelPayloadError::UnsupportedStateAction)?;
        let estimate = &self.model.estimates[index];
        Ok(WorldModelPredictionV1 {
            model_id: self.model.model_id.clone(),
            dataset_digest: self.model.dataset_digest,
            state_id: estimate.state_id.clone(),
            action_id: estimate.action_id.clone(),
            mean_outcome: estimate.mean_outcome,
            branches: estimate.branches.clone(),
            estimate_digest: estimate.estimate_digest,
            synthetic: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

pub fn encode_world_model_payload_v1(
    model: &TabularWorldModelV1,
) -> Result<Vec<u8>, WorldModelPayloadError> {
    validate_world_model_structure(model).map_err(|_| WorldModelPayloadError::InvalidModel)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    put_id(&mut bytes, &model.model_id);
    bytes.extend_from_slice(model.dataset_digest.as_array());
    bytes.extend_from_slice(model.model_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(model.estimates.len())
            .map_err(|_| WorldModelPayloadError::Bounds)?
            .to_be_bytes(),
    );
    for estimate in &model.estimates {
        put_id(&mut bytes, &estimate.state_id);
        put_id(&mut bytes, &estimate.action_id);
        bytes.extend_from_slice(&estimate.sample_count.to_be_bytes());
        bytes.extend_from_slice(&estimate.mean_outcome.raw().to_be_bytes());
        bytes.extend_from_slice(estimate.estimate_digest.as_array());
        bytes.extend_from_slice(
            &u32::try_from(estimate.branches.len())
                .map_err(|_| WorldModelPayloadError::Bounds)?
                .to_be_bytes(),
        );
        for branch in &estimate.branches {
            put_id(&mut bytes, &branch.next_state_id);
            bytes.extend_from_slice(&branch.count.to_be_bytes());
            bytes.extend_from_slice(&branch.probability.raw().to_be_bytes());
        }
    }
    if bytes.len() > MAX_BYTES {
        return Err(WorldModelPayloadError::Bounds);
    }
    Ok(bytes)
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

fn take<'a>(
    bytes: &mut &'a [u8],
    count: usize,
) -> Result<&'a [u8], WorldModelPayloadError> {
    let (head, tail) = bytes
        .split_at_checked(count)
        .ok_or(WorldModelPayloadError::Encoding)?;
    *bytes = tail;
    Ok(head)
}

fn word<const N: usize>(bytes: &mut &[u8]) -> Result<[u8; N], WorldModelPayloadError> {
    take(bytes, N)?
        .try_into()
        .map_err(|_| WorldModelPayloadError::Encoding)
}

fn read_id(bytes: &mut &[u8]) -> Result<StableId, WorldModelPayloadError> {
    let size = usize::from(u16::from_be_bytes(word(bytes)?));
    if !(1..=128).contains(&size) {
        return Err(WorldModelPayloadError::Bounds);
    }
    StableId::new(
        std::str::from_utf8(take(bytes, size)?).map_err(|_| WorldModelPayloadError::Encoding)?,
    )
    .map_err(|_| WorldModelPayloadError::Encoding)
}

fn decode(mut bytes: &[u8]) -> Result<TabularWorldModelV1, WorldModelPayloadError> {
    if bytes.len() > MAX_BYTES || take(&mut bytes, 8)? != MAGIC {
        return Err(WorldModelPayloadError::Encoding);
    }
    let model_id = read_id(&mut bytes)?;
    let dataset_digest = Digest32::from_array(word(&mut bytes)?);
    let model_digest = Digest32::from_array(word(&mut bytes)?);
    let estimate_count = u32::from_be_bytes(word(&mut bytes)?) as usize;
    if estimate_count == 0 || estimate_count > MAX_STATE_ACTIONS {
        return Err(WorldModelPayloadError::Bounds);
    }

    let mut estimates = Vec::with_capacity(estimate_count);
    let mut total_samples = 0_u64;
    for _ in 0..estimate_count {
        let state_id = read_id(&mut bytes)?;
        let action_id = read_id(&mut bytes)?;
        let sample_count = u32::from_be_bytes(word(&mut bytes)?);
        if sample_count == 0 {
            return Err(WorldModelPayloadError::InvalidModel);
        }
        total_samples = total_samples
            .checked_add(u64::from(sample_count))
            .ok_or(WorldModelPayloadError::Bounds)?;
        if total_samples > MAX_SAMPLES as u64 {
            return Err(WorldModelPayloadError::Bounds);
        }
        let mean_outcome = FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?));
        let estimate_digest = Digest32::from_array(word(&mut bytes)?);
        let branch_count = u32::from_be_bytes(word(&mut bytes)?) as usize;
        if branch_count == 0 || branch_count > MAX_BRANCHES_PER_STATE_ACTION {
            return Err(WorldModelPayloadError::Bounds);
        }
        let mut branches = Vec::with_capacity(branch_count);
        for _ in 0..branch_count {
            let next_state_id = read_id(&mut bytes)?;
            let count = u32::from_be_bytes(word(&mut bytes)?);
            let probability = ProbabilityQ32::from_raw(u64::from_be_bytes(word(&mut bytes)?))
                .map_err(|_| WorldModelPayloadError::Encoding)?;
            branches.push(TransitionBranchV1 {
                next_state_id,
                count,
                probability,
            });
        }
        estimates.push(TransitionEstimateV1 {
            state_id,
            action_id,
            sample_count,
            mean_outcome,
            branches,
            estimate_digest,
        });
    }
    if !bytes.is_empty() {
        return Err(WorldModelPayloadError::Encoding);
    }
    let model = TabularWorldModelV1 {
        model_id,
        dataset_digest,
        estimates,
        model_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_world_model_structure(&model)
        .map_err(|_| WorldModelPayloadError::InvalidModel)?;
    Ok(model)
}

#[cfg(test)]
#[path = "world_model_loaded_tests.rs"]
mod tests;
