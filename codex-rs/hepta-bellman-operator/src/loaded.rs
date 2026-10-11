//! Bounded persisted tabular candidates and once-validated inference.
//!
//! This owner-local payload is not a selection record. The artifact owner must
//! verify current lineage/revocations and supply an independently selected pin.
//! The training digest includes evidence unavailable in these sufficient
//! statistics: it is retained, not spuriously "recomputed" from the cells.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorCellV1;
use crate::TabularOperatorPredictionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTTB01";
const MAX_BYTES: usize = 64 * 1024 * 1024;
const MAX_CELLS: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularPayloadPinV1 {
    pub payload_digest: Digest32,
    pub artifact_digest: Digest32,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub sensor_core_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub generation: Generation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TabularPayloadError {
    Bounds,
    Encoding,
    Binding,
    Grid,
    Authority,
    UnsupportedCell,
}
impl fmt::Display for TabularPayloadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for TabularPayloadError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoadedTabularOperatorV1 {
    artifact: TabularOperatorArtifactV1,
}

impl LoadedTabularOperatorV1 {
    /// Verify a host-selected pin before decoding or permitting predictions.
    /// A pin computed from untrusted payload bytes is not independent admission.
    pub fn from_pinned_payload(
        bytes: &[u8],
        pin: &TabularPayloadPinV1,
    ) -> Result<Self, TabularPayloadError> {
        if bytes.len() > MAX_BYTES {
            return Err(TabularPayloadError::Bounds);
        }
        if pin.payload_digest.is_zero() || Digest32::of_bytes(bytes) != pin.payload_digest {
            return Err(TabularPayloadError::Binding);
        }
        let artifact = decode(bytes)?;
        if artifact.generation != pin.generation
            || artifact.artifact_digest != pin.artifact_digest
            || artifact.objective_digest != pin.objective_digest
            || artifact.dataset_digest != pin.dataset_digest
            || artifact.sensor_core_digest != pin.sensor_core_digest
            || artifact.training_profile_digest != pin.training_profile_digest
        {
            return Err(TabularPayloadError::Binding);
        }
        validate(&artifact)?;
        Ok(Self { artifact })
    }

    /// The immutable training identity, for binding an existing registry manifest.
    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact.artifact_id
    }

    /// The immutable loaded value validates O(n) once, then looks up in O(log n).
    pub fn predict(
        &self,
        sensor: &StableId,
        action: &StableId,
    ) -> Result<TabularOperatorPredictionV1, TabularPayloadError> {
        let index = self
            .artifact
            .cells
            .binary_search_by(|cell| (&cell.sensor_id, &cell.action_id).cmp(&(sensor, action)))
            .map_err(|_| TabularPayloadError::UnsupportedCell)?;
        let cell = &self.artifact.cells[index];
        Ok(TabularOperatorPredictionV1 {
            artifact_id: self.artifact.artifact_id.clone(),
            sensor_id: cell.sensor_id.clone(),
            action_id: cell.action_id.clone(),
            value: cell.mean_target,
            cell_evidence_digest: cell.evidence_digest,
            learned: true,
            synthetic: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// Encode candidate bytes for the existing artifact owner's create-only store.
/// This function performs no storage, training, approval or activation.
pub fn encode_tabular_payload_v1(
    artifact: &TabularOperatorArtifactV1,
) -> Result<Vec<u8>, TabularPayloadError> {
    validate(artifact)?;
    let size = 8
        + 2
        + artifact.artifact_id.as_str().len()
        + 2
        + artifact.producer_id.as_str().len()
        + 8
        + 5 * 32
        + 4
        + artifact
            .cells
            .iter()
            .map(|cell| {
                2 + cell.sensor_id.as_str().len()
                    + 2
                    + cell.action_id.as_str().len()
                    + 4
                    + 3 * 8
                    + 32
            })
            .sum::<usize>();
    if size > MAX_BYTES {
        return Err(TabularPayloadError::Bounds);
    }
    let mut bytes = Vec::with_capacity(size);
    bytes.extend_from_slice(MAGIC);
    put_id(&mut bytes, &artifact.artifact_id);
    put_id(&mut bytes, &artifact.producer_id);
    bytes.extend_from_slice(&artifact.generation.get().to_be_bytes());
    for digest in [
        artifact.artifact_digest,
        artifact.objective_digest,
        artifact.dataset_digest,
        artifact.sensor_core_digest,
        artifact.training_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(artifact.cells.len() as u32).to_be_bytes());
    for cell in &artifact.cells {
        put_id(&mut bytes, &cell.sensor_id);
        put_id(&mut bytes, &cell.action_id);
        bytes.extend_from_slice(&cell.sample_count.to_be_bytes());
        for number in [cell.mean_target, cell.minimum_target, cell.maximum_target] {
            bytes.extend_from_slice(&number.raw().to_be_bytes());
        }
        bytes.extend_from_slice(cell.evidence_digest.as_array());
    }
    Ok(bytes)
}

fn validate(artifact: &TabularOperatorArtifactV1) -> Result<(), TabularPayloadError> {
    if artifact.authority.grants_any() {
        return Err(TabularPayloadError::Authority);
    }
    if [
        artifact.artifact_digest,
        artifact.objective_digest,
        artifact.dataset_digest,
        artifact.sensor_core_digest,
        artifact.training_profile_digest,
    ]
    .into_iter()
    .any(Digest32::is_zero)
    {
        return Err(TabularPayloadError::Binding);
    }
    if artifact.cells.is_empty() || artifact.cells.len() > MAX_CELLS {
        return Err(TabularPayloadError::Bounds);
    }
    if artifact.cells.windows(2).any(|pair| {
        (&pair[0].sensor_id, &pair[0].action_id) >= (&pair[1].sensor_id, &pair[1].action_id)
    }) {
        return Err(TabularPayloadError::Grid);
    }
    let mut sensors = BTreeMap::<&StableId, usize>::new();
    let mut actions = BTreeSet::new();
    let mut samples = 0_u64;
    for cell in &artifact.cells {
        if cell.sample_count == 0
            || cell.evidence_digest.is_zero()
            || cell.minimum_target > cell.mean_target
            || cell.mean_target > cell.maximum_target
        {
            return Err(TabularPayloadError::Grid);
        }
        *sensors.entry(&cell.sensor_id).or_default() += 1;
        actions.insert(&cell.action_id);
        samples += u64::from(cell.sample_count);
    }
    if sensors.len() > 4096
        || actions.len() > 128
        || samples > 1_000_000
        || sensors.values().any(|count| *count != actions.len())
    {
        return Err(TabularPayloadError::Grid);
    }
    Ok(())
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
fn take<'a>(bytes: &mut &'a [u8], count: usize) -> Result<&'a [u8], TabularPayloadError> {
    let (head, tail) = bytes
        .split_at_checked(count)
        .ok_or(TabularPayloadError::Encoding)?;
    *bytes = tail;
    Ok(head)
}
fn word<const N: usize>(bytes: &mut &[u8]) -> Result<[u8; N], TabularPayloadError> {
    take(bytes, N)?
        .try_into()
        .map_err(|_| TabularPayloadError::Encoding)
}
fn read_id(bytes: &mut &[u8]) -> Result<StableId, TabularPayloadError> {
    let size = usize::from(u16::from_be_bytes(word(bytes)?));
    if !(1..=128).contains(&size) {
        return Err(TabularPayloadError::Bounds);
    }
    StableId::new(
        std::str::from_utf8(take(bytes, size)?).map_err(|_| TabularPayloadError::Encoding)?,
    )
    .map_err(|_| TabularPayloadError::Encoding)
}
fn decode(mut bytes: &[u8]) -> Result<TabularOperatorArtifactV1, TabularPayloadError> {
    if take(&mut bytes, 8)? != MAGIC {
        return Err(TabularPayloadError::Encoding);
    }
    let artifact_id = read_id(&mut bytes)?;
    let producer_id = read_id(&mut bytes)?;
    let generation = Generation::new(u64::from_be_bytes(word(&mut bytes)?))
        .map_err(|_| TabularPayloadError::Encoding)?;
    let mut digests = [Digest32::ZERO; 5];
    for digest in &mut digests {
        *digest = Digest32::from_array(word(&mut bytes)?);
    }
    let count = u32::from_be_bytes(word(&mut bytes)?) as usize;
    // Each cell needs at least two one-byte IDs plus numeric fields and digest.
    if count == 0 || count > MAX_CELLS || count > bytes.len() / 66 {
        return Err(TabularPayloadError::Bounds);
    }
    let mut cells = Vec::with_capacity(count);
    for _ in 0..count {
        cells.push(TabularOperatorCellV1 {
            sensor_id: read_id(&mut bytes)?,
            action_id: read_id(&mut bytes)?,
            sample_count: u32::from_be_bytes(word(&mut bytes)?),
            mean_target: FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?)),
            minimum_target: FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?)),
            maximum_target: FixedQ32::from_raw(i64::from_be_bytes(word(&mut bytes)?)),
            evidence_digest: Digest32::from_array(word(&mut bytes)?),
        });
    }
    if !bytes.is_empty() {
        return Err(TabularPayloadError::Encoding);
    }
    Ok(TabularOperatorArtifactV1 {
        artifact_id,
        producer_id,
        generation,
        artifact_digest: digests[0],
        objective_digest: digests[1],
        dataset_digest: digests[2],
        sensor_core_digest: digests[3],
        training_profile_digest: digests[4],
        cells,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "loaded_tests.rs"]
mod tests;
