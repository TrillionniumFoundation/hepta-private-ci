//! Bounded persisted world-model candidates and once-validated inference.
//!
//! Raw `TabularWorldModelV1` values are candidate data, not authenticated
//! runtime objects. Prediction is exposed through `LoadedWorldModelV1`, which
//! requires an independently selected payload pin and validates the complete
//! canonical transition structure once before lookup.

use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::world_model::TabularWorldModelV1;
use crate::world_model::TransitionBranchV1;
use crate::world_model::TransitionEstimateV1;
use crate::world_model::WorldModelPredictionV1;

const MAGIC: &[u8; 8] = b"HEPTWM01";
const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_ESTIMATES: usize = 16_384;
const MAX_BRANCHES_PER_ESTIMATE: usize = 1_024;
const MAX_TOTAL_SAMPLES: u64 = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelPayloadPinV1 {
    pub payload_digest: Digest32,
    pub model_digest: Digest32,
    pub dataset_digest: Digest32,
    pub model_id: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorldModelPayloadError {
    Bounds,
    Encoding,
    Binding,
    Structure,
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
pub struct LoadedWorldModelV1 {
    model: TabularWorldModelV1,
}

impl LoadedWorldModelV1 {
    /// Verify an independently selected payload pin before decoding or use.
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
        validate(&model)?;
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

/// Encode candidate bytes for the artifact owner's create-only store.
/// Encoding does not select, approve, activate, or promote the candidate.
pub fn encode_world_model_payload_v1(
    model: &TabularWorldModelV1,
) -> Result<Vec<u8>, WorldModelPayloadError> {
    validate(model)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    put_id(&mut bytes, &model.model_id)?;
    bytes.extend_from_slice(model.dataset_digest.as_array());
    bytes.extend_from_slice(model.model_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(model.estimates.len())
            .map_err(|_| WorldModelPayloadError::Bounds)?
            .to_be_bytes(),
    );
    for estimate in &model.estimates {
        put_id(&mut bytes, &estimate.state_id)?;
        put_id(&mut bytes, &estimate.action_id)?;
        bytes.extend_from_slice(&estimate.sample_count.to_be_bytes());
        bytes.extend_from_slice(&estimate.mean_outcome.raw().to_be_bytes());
        bytes.extend_from_slice(estimate.estimate_digest.as_array());
        bytes.extend_from_slice(
            &u32::try_from(estimate.branches.len())
                .map_err(|_| WorldModelPayloadError::Bounds)?
                .to_be_bytes(),
        );
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

fn validate(model: &TabularWorldModelV1) -> Result<(), WorldModelPayloadError> {
    if model.authority.grants_any() {
        return Err(WorldModelPayloadError::Authority);
    }
    if model.dataset_digest.is_zero() || model.model_digest.is_zero() {
        return Err(WorldModelPayloadError::Binding);
    }
    if model.estimates.is_empty() || model.estimates.len() > MAX_ESTIMATES {
        return Err(WorldModelPayloadError::Bounds);
    }
    if model.estimates.windows(2).any(|pair| {
        (&pair[0].state_id, &pair[0].action_id) >= (&pair[1].state_id, &pair[1].action_id)
    }) {
        return Err(WorldModelPayloadError::Structure);
    }

    let mut total_samples = 0_u64;
    for estimate in &model.estimates {
        if estimate.sample_count == 0
            || estimate.estimate_digest.is_zero()
            || !(-FixedQ32::ONE.raw()..=FixedQ32::ONE.raw())
                .contains(&estimate.mean_outcome.raw())
            || estimate.branches.is_empty()
            || estimate.branches.len() > MAX_BRANCHES_PER_ESTIMATE
        {
            return Err(WorldModelPayloadError::Structure);
        }
        if estimate
            .branches
            .windows(2)
            .any(|pair| pair[0].next_state_id >= pair[1].next_state_id)
        {
            return Err(WorldModelPayloadError::Structure);
        }
        let mut count_sum = 0_u64;
        let mut probability_sum = 0_u64;
        for branch in &estimate.branches {
            if branch.count == 0 || branch.probability.raw() == 0 {
                return Err(WorldModelPayloadError::Structure);
            }
            count_sum = count_sum
                .checked_add(u64::from(branch.count))
                .ok_or(WorldModelPayloadError::Bounds)?;
            probability_sum = probability_sum
                .checked_add(branch.probability.raw())
                .ok_or(WorldModelPayloadError::Bounds)?;
        }
        if count_sum != u64::from(estimate.sample_count)
            || probability_sum != ProbabilityQ32::ONE.raw()
        {
            return Err(WorldModelPayloadError::Structure);
        }
        total_samples = total_samples
            .checked_add(u64::from(estimate.sample_count))
            .ok_or(WorldModelPayloadError::Bounds)?;
    }
    if total_samples > MAX_TOTAL_SAMPLES {
        return Err(WorldModelPayloadError::Bounds);
    }

    let mut model_bytes = b"hepta.bellman-operator.tabular-world-model.v1".to_vec();
    push_id_u32(&mut model_bytes, &model.model_id)?;
    model_bytes.extend_from_slice(model.dataset_digest.as_array());
    model_bytes.extend_from_slice(
        &u32::try_from(model.estimates.len())
            .map_err(|_| WorldModelPayloadError::Bounds)?
            .to_be_bytes(),
    );
    for estimate in &model.estimates {
        model_bytes.extend_from_slice(estimate.estimate_digest.as_array());
    }
    if Digest32::of_bytes(&model_bytes) != model.model_digest {
        return Err(WorldModelPayloadError::Binding);
    }
    Ok(())
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), WorldModelPayloadError> {
    let raw = id.as_str().as_bytes();
    let length = u16::try_from(raw.len()).map_err(|_| WorldModelPayloadError::Bounds)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_id_u32(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), WorldModelPayloadError> {
    let raw = id.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| WorldModelPayloadError::Bounds)?;
    bytes.extend_from_slice(&length.to_be_bytes());
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
    if !(1..=128).contains(&size) {
        return Err(WorldModelPayloadError::Bounds);
    }
    StableId::new(
        std::str::from_utf8(take(bytes, size)?)
            .map_err(|_| WorldModelPayloadError::Encoding)?,
    )
    .map_err(|_| WorldModelPayloadError::Encoding)
}

fn decode(mut bytes: &[u8]) -> Result<TabularWorldModelV1, WorldModelPayloadError> {
    if take(&mut bytes, MAGIC.len())? != MAGIC {
        return Err(WorldModelPayloadError::Encoding);
    }
    let model_id = read_id(&mut bytes)?;
    let dataset_digest = Digest32::from_array(word(&mut bytes)?);
    let model_digest = Digest32::from_array(word(&mut bytes)?);
    let estimate_count = u32::from_be_bytes(word(&mut bytes)?) as usize;
    if estimate_count == 0 || estimate_count > MAX_ESTIMATES {
        return Err(WorldModelPayloadError::Bounds);
    }
    let mut estimates = Vec::with_capacity(estimate_count);
    for _ in 0..estimate_count {
        let state_id = read_id(&mut bytes)?;
        let action_id = read_id(&mut bytes)?;
        let sample_count = u32::from_be_bytes(word(&mut bytes)?);
        let mean_outcome = FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?));
        let estimate_digest = Digest32::from_array(word(&mut bytes)?);
        let branch_count = u32::from_be_bytes(word(&mut bytes)?) as usize;
        if branch_count == 0 || branch_count > MAX_BRANCHES_PER_ESTIMATE {
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
    Ok(TabularWorldModelV1 {
        model_id,
        dataset_digest,
        estimates,
        model_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::world_model::WorldModelSampleV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn sample(name: &str, next: &str, outcome: i64) -> WorldModelSampleV1 {
        WorldModelSampleV1 {
            sample_id: id(name),
            state_id: id("state-a"),
            action_id: id("action-a"),
            next_state_id: id(next),
            outcome: FixedQ32::from_raw(outcome),
            evidence_digest: digest(&format!("evidence-{name}")),
        }
    }

    fn payload() -> (Vec<u8>, WorldModelPayloadPinV1) {
        let model = crate::world_model::fit_transition_model(
            id("world-model"),
            digest("dataset"),
            vec![sample("sample-a", "state-b", 10), sample("sample-b", "state-c", 20)],
        )
        .expect("fit");
        let bytes = encode_world_model_payload_v1(&model).expect("encode");
        let pin = WorldModelPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&bytes),
            model_digest: model.model_digest,
            dataset_digest: model.dataset_digest,
            model_id: model.model_id.clone(),
        };
        (bytes, pin)
    }

    #[test]
    fn pinned_world_model_loads_once_and_predicts() {
        let (bytes, pin) = payload();
        let loaded = LoadedWorldModelV1::from_pinned_payload(&bytes, &pin).expect("load");
        let prediction = loaded
            .predict(&id("state-a"), &id("action-a"))
            .expect("predict");
        assert!(prediction.synthetic);
        assert!(!prediction.authority.grants_any());
        assert_eq!(prediction.branches.len(), 2);
    }

    #[test]
    fn pinned_world_model_rejects_payload_drift() {
        let (mut bytes, pin) = payload();
        let last = bytes.last_mut().expect("payload byte");
        *last ^= 1;
        assert_eq!(
            LoadedWorldModelV1::from_pinned_payload(&bytes, &pin),
            Err(WorldModelPayloadError::Binding)
        );
    }

    #[test]
    fn pinned_world_model_rejects_wrong_selected_identity() {
        let (bytes, mut pin) = payload();
        pin.dataset_digest = digest("different-dataset");
        assert_eq!(
            LoadedWorldModelV1::from_pinned_payload(&bytes, &pin),
            Err(WorldModelPayloadError::Binding)
        );
    }
}
