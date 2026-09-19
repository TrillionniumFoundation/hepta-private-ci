//! Independently pinned persisted world-model candidates.
//!
//! Raw `TabularWorldModelV1` values remain compatibility data structures. This
//! module serializes the complete prediction surface, binds it to a host-selected
//! payload digest, validates all retained statistics once, and keeps the admitted
//! model private for repeated inference.

use std::collections::BTreeMap;
use std::error::Error;
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

const MAGIC: &[u8; 8] = b"HEPTWM01";
const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_SAMPLES: u64 = 65_536;
const MAX_STATE_ACTIONS: usize = 16_384;
const MAX_BRANCHES_PER_STATE_ACTION: usize = 1_024;
const MAX_ID_BYTES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelPayloadPinV1 {
    pub payload_digest: Digest32,
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub dataset_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorldModelPayloadError {
    Bounds,
    Encoding,
    Binding,
    Grid,
    Authority,
    UnsupportedStateAction,
}

impl fmt::Display for WorldModelPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for WorldModelPayloadError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoadedTabularWorldModelV1 {
    model: TabularWorldModelV1,
}

impl LoadedTabularWorldModelV1 {
    /// Admit only bytes matching an independently selected host pin.
    ///
    /// Computing `pin.payload_digest` from these same untrusted bytes is not
    /// independent admission.
    pub fn from_pinned_payload(
        bytes: &[u8],
        pin: &WorldModelPayloadPinV1,
    ) -> Result<Self, WorldModelPayloadError> {
        if bytes.len() > MAX_BYTES {
            return Err(WorldModelPayloadError::Bounds);
        }
        if pin.payload_digest.is_zero() || Digest32::of_bytes(bytes) != pin.payload_digest {
            return Err(WorldModelPayloadError::Binding);
        }
        let model = decode(bytes)?;
        if model.model_id != pin.model_id
            || model.model_digest != pin.model_digest
            || model.dataset_digest != pin.dataset_digest
        {
            return Err(WorldModelPayloadError::Binding);
        }
        validate_world_model_v1(&model)?;
        Ok(Self { model })
    }

    #[must_use]
    pub fn model_id(&self) -> &StableId {
        &self.model.model_id
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

/// Encode a complete world-model prediction surface for create-only persistence.
///
/// Storage, selection, promotion and activation remain external owner actions.
pub fn encode_world_model_payload_v1(
    model: &TabularWorldModelV1,
) -> Result<Vec<u8>, WorldModelPayloadError> {
    validate_world_model_v1(model)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    put_id(&mut bytes, &model.model_id)?;
    bytes.extend_from_slice(model.dataset_digest.as_array());
    bytes.extend_from_slice(model.model_digest.as_array());
    bytes.extend_from_slice(&(model.estimates.len() as u32).to_be_bytes());
    for estimate in &model.estimates {
        put_id(&mut bytes, &estimate.state_id)?;
        put_id(&mut bytes, &estimate.action_id)?;
        bytes.extend_from_slice(&estimate.sample_count.to_be_bytes());
        bytes.extend_from_slice(&estimate.mean_outcome.raw().to_be_bytes());
        bytes.extend_from_slice(estimate.estimate_digest.as_array());
        bytes.extend_from_slice(&(estimate.branches.len() as u32).to_be_bytes());
        for branch in &estimate.branches {
            put_id(&mut bytes, &branch.next_state_id)?;
            bytes.extend_from_slice(&branch.count.to_be_bytes());
            bytes.extend_from_slice(&branch.probability.raw().to_be_bytes());
        }
    }
    if bytes.len() > MAX_BYTES {
        return Err(WorldModelPayloadError::Bounds);
    }
    Ok(bytes)
}

pub(crate) fn validate_world_model_v1(
    model: &TabularWorldModelV1,
) -> Result<(), WorldModelPayloadError> {
    if model.authority.grants_any() {
        return Err(WorldModelPayloadError::Authority);
    }
    if model.dataset_digest.is_zero() || model.model_digest.is_zero() {
        return Err(WorldModelPayloadError::Binding);
    }
    let expected_model_digest =
        crate::world_model::digest_world_model(&model.model_id, model.dataset_digest, &model.estimates)
            .map_err(|_| WorldModelPayloadError::Binding)?;
    if expected_model_digest != model.model_digest {
        return Err(WorldModelPayloadError::Binding);
    }
    if model.estimates.is_empty() || model.estimates.len() > MAX_STATE_ACTIONS {
        return Err(WorldModelPayloadError::Bounds);
    }
    if model.estimates.windows(2).any(|pair| {
        (&pair[0].state_id, &pair[0].action_id) >= (&pair[1].state_id, &pair[1].action_id)
    }) {
        return Err(WorldModelPayloadError::Grid);
    }

    let mut total_samples = 0_u64;
    for estimate in &model.estimates {
        if estimate.sample_count == 0
            || estimate.estimate_digest.is_zero()
            || !(-FixedQ32::ONE.raw()..=FixedQ32::ONE.raw())
                .contains(&estimate.mean_outcome.raw())
            || estimate.branches.is_empty()
            || estimate.branches.len() > MAX_BRANCHES_PER_STATE_ACTION
        {
            return Err(WorldModelPayloadError::Grid);
        }
        total_samples = total_samples
            .checked_add(u64::from(estimate.sample_count))
            .ok_or(WorldModelPayloadError::Bounds)?;
        if total_samples > MAX_SAMPLES {
            return Err(WorldModelPayloadError::Bounds);
        }
        if estimate
            .branches
            .windows(2)
            .any(|pair| &pair[0].next_state_id >= &pair[1].next_state_id)
        {
            return Err(WorldModelPayloadError::Grid);
        }

        let mut counts = BTreeMap::new();
        let mut count_sum = 0_u64;
        let mut probability_sum = 0_u64;
        for branch in &estimate.branches {
            if branch.count == 0 {
                return Err(WorldModelPayloadError::Grid);
            }
            count_sum = count_sum
                .checked_add(u64::from(branch.count))
                .ok_or(WorldModelPayloadError::Grid)?;
            probability_sum = probability_sum
                .checked_add(branch.probability.raw())
                .ok_or(WorldModelPayloadError::Grid)?;
            counts.insert(branch.next_state_id.clone(), branch.count);
        }
        if count_sum != u64::from(estimate.sample_count)
            || probability_sum != ProbabilityQ32::ONE.raw()
        {
            return Err(WorldModelPayloadError::Grid);
        }
        let expected = crate::world_model::exact_probabilities(estimate.sample_count, counts)
            .map_err(|_| WorldModelPayloadError::Grid)?;
        if expected != estimate.branches {
            return Err(WorldModelPayloadError::Grid);
        }
    }
    Ok(())
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), WorldModelPayloadError> {
    let raw = id.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_ID_BYTES {
        return Err(WorldModelPayloadError::Bounds);
    }
    let size = u16::try_from(raw.len()).map_err(|_| WorldModelPayloadError::Bounds)?;
    bytes.extend_from_slice(&size.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
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
    if !(1..=MAX_ID_BYTES).contains(&size) {
        return Err(WorldModelPayloadError::Bounds);
    }
    StableId::new(
        std::str::from_utf8(take(bytes, size)?)
            .map_err(|_| WorldModelPayloadError::Encoding)?,
    )
    .map_err(|_| WorldModelPayloadError::Encoding)
}

fn decode(mut bytes: &[u8]) -> Result<TabularWorldModelV1, WorldModelPayloadError> {
    if bytes.len() > MAX_BYTES || take(&mut bytes, MAGIC.len())? != MAGIC {
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
    let mut total_branches = 0_u64;
    for _ in 0..estimate_count {
        let state_id = read_id(&mut bytes)?;
        let action_id = read_id(&mut bytes)?;
        let sample_count = u32::from_be_bytes(word(&mut bytes)?);
        total_samples = total_samples
            .checked_add(u64::from(sample_count))
            .ok_or(WorldModelPayloadError::Bounds)?;
        if sample_count == 0 || total_samples > MAX_SAMPLES {
            return Err(WorldModelPayloadError::Bounds);
        }
        let mean_outcome = FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?));
        let estimate_digest = Digest32::from_array(word(&mut bytes)?);
        let branch_count = u32::from_be_bytes(word(&mut bytes)?) as usize;
        if branch_count == 0
            || branch_count > MAX_BRANCHES_PER_STATE_ACTION
            || branch_count > sample_count as usize
        {
            return Err(WorldModelPayloadError::Bounds);
        }
        total_branches = total_branches
            .checked_add(branch_count as u64)
            .ok_or(WorldModelPayloadError::Bounds)?;
        if total_branches > MAX_SAMPLES {
            return Err(WorldModelPayloadError::Bounds);
        }
        let mut branches = Vec::with_capacity(branch_count);
        for _ in 0..branch_count {
            branches.push(TransitionBranchV1 {
                next_state_id: read_id(&mut bytes)?,
                count: u32::from_be_bytes(word(&mut bytes)?),
                probability: ProbabilityQ32::from_raw(u64::from_be_bytes(word(&mut bytes)?))
                    .map_err(|_| WorldModelPayloadError::Encoding)?,
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
    validate_world_model_v1(&model)?;
    Ok(model)
}

#[cfg(test)]
#[path = "loaded_world_model_tests.rs"]
mod tests;
