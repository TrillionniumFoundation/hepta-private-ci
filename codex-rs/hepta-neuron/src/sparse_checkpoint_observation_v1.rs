//! Complete read-only state from the original sparse owner. A checksum proves
//! integrity only; protected original-owner transport must prove its origin.
use super::*;
use crate::JournalAnchor;
use crate::JournalScope;

const MAGIC: &[u8; 8] = b"HPTNSC01";
const DOMAIN: &[u8] = b"hepta.neuron.sparse-checkpoint-observation.v1";
const PREIMAGE_DOMAIN: &[u8] = b"hepta.neuron.sparse-checkpoint.q24.v1";
pub const MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1: usize = 16 * 1024;

impl SparseCheckpoint {
    /// Preserve the original whole digest preimage plus private replay body.
    /// This grants no execution, publication or acknowledgement authority.
    pub fn encode_observation_v1(&self) -> Result<Vec<u8>, SparseError> {
        if self.calculate_digest() != self.digest {
            return Err(SparseError::InvalidCheckpoint);
        }
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(self.body.as_array());
        bytes.extend_from_slice(self.digest.as_array());
        bytes.extend_from_slice(&self.canonical_preimage());
        let checksum = Digest32::of_parts(&[DOMAIN, &bytes]);
        bytes.extend_from_slice(checksum.as_array());
        if bytes.len() > MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1 {
            return Err(SparseError::InvalidCheckpoint);
        }
        Ok(bytes)
    }

    /// Validate all original state against independently selected full material
    /// and actual acknowledged anchor. `source_digest` is an integrity pin,
    /// never a replacement for protected exporter custody.
    pub fn decode_observation_v1(
        bytes: &[u8],
        source_digest: Digest32,
        config: &SparseConfig,
        scope: JournalScope,
        body: Digest32,
        anchor: JournalAnchor,
    ) -> Result<Self, SparseError> {
        let config_digest = config.digest()?;
        if bytes.len() > MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1
            || bytes.len() < 32
            || source_digest.is_zero()
            || Digest32::of_bytes(bytes) != source_digest
            || body.is_zero()
            || scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || anchor.sequence == 0
            || anchor.checkpoint_digest.is_zero()
        {
            return Err(SparseError::InvalidCheckpoint);
        }
        let end = bytes.len() - 32;
        if Digest32::of_parts(&[DOMAIN, &bytes[..end]]).as_array() != &bytes[end..] {
            return Err(SparseError::InvalidCheckpoint);
        }
        let mut reader = Reader {
            bytes: &bytes[..end],
            position: 0,
        };
        if reader.take(8)? != MAGIC {
            return Err(SparseError::InvalidCheckpoint);
        }
        let actual_body = reader.digest()?;
        let digest = reader.digest()?;
        if reader.take(PREIMAGE_DOMAIN.len())? != PREIMAGE_DOMAIN {
            return Err(SparseError::InvalidCheckpoint);
        }
        let actual_config = reader.digest()?;
        let actual_scope = reader.digest()?;
        let objective = reader.digest()?;
        let predecessor = reader.digest()?;
        let input = reader.digest()?;
        let sequence = reader.u64()?;
        let monotonic_micros = reader.u64()?;
        let value = Self {
            config: actual_config,
            scope: actual_scope,
            objective,
            body: actual_body,
            sequence,
            monotonic_micros,
            predecessor,
            input,
            temporal: reader.vector(config.width)?,
            activation: reader.vector(config.width)?,
            activity: reader.vector(config.width)?,
            threshold: reader.vector(config.width)?,
            eligibility: reader.vector(config.width)?,
            digest,
        };
        if reader.position != end
            || value.config != config_digest
            || value.scope != scope.scope_digest
            || value.objective != scope.objective_digest
            || value.body != body
            || value.sequence != anchor.sequence
            || value.digest != anchor.checkpoint_digest
            || value.calculate_digest() != value.digest
            || value.monotonic_micros == 0
            || value.input.is_zero()
            || (value.sequence == 1) != value.predecessor.is_zero()
            || value.temporal.iter().any(|v| !(-H..=H).contains(v))
            || value.activation.iter().any(|v| !(0..=H).contains(v))
            || value.activity.iter().any(|v| !(0..=Q).contains(v))
            || value
                .threshold
                .iter()
                .any(|v| !(config.threshold_min_q24..=config.threshold_max_q24).contains(v))
            || value
                .eligibility
                .iter()
                .any(|v| !(-ELIGIBILITY_L1..=ELIGIBILITY_L1).contains(v))
            || value.eligibility.iter().map(|v| v.abs()).sum::<i64>() > ELIGIBILITY_L1
        {
            return Err(SparseError::InvalidCheckpoint);
        }
        Ok(value)
    }
}

struct Reader<'a> {
    bytes: &'a [u8],
    position: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], SparseError> {
        let end = self
            .position
            .checked_add(count)
            .ok_or(SparseError::InvalidCheckpoint)?;
        let value = self
            .bytes
            .get(self.position..end)
            .ok_or(SparseError::InvalidCheckpoint)?;
        self.position = end;
        Ok(value)
    }
    fn digest(&mut self) -> Result<Digest32, SparseError> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| SparseError::InvalidCheckpoint)?,
        ))
    }
    fn u64(&mut self) -> Result<u64, SparseError> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| SparseError::InvalidCheckpoint)?,
        ))
    }
    fn vector(&mut self, width: usize) -> Result<Vec<i64>, SparseError> {
        if self.u64()? != width as u64 {
            return Err(SparseError::InvalidCheckpoint);
        }
        (0..width)
            .map(|_| {
                Ok(i64::from_be_bytes(
                    self.take(8)?
                        .try_into()
                        .map_err(|_| SparseError::InvalidCheckpoint)?,
                ))
            })
            .collect()
    }
}

#[cfg(test)]
#[path = "sparse_checkpoint_observation_v1_tests.rs"]
mod tests;
