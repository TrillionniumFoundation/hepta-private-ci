//! Composition-aware shared encoder residency seam.
//!
//! This module is intentionally not wired into the production model loader yet.
//! It makes the resource claim explicit and testable: a frozen encoder is keyed
//! by its full preprocessing/runtime identity and can fan out to many private
//! Cell heads. A head never changes the encoder key or its bytes.

use std::collections::BTreeMap;
use std::fmt;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct CompositionKey {
    pub encoder_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub normalization_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
}

impl CompositionKey {
    pub fn validate(&self) -> Result<(), CompositionError> {
        for (name, value) in [
            ("encoder_digest", &self.encoder_digest),
            ("tokenizer_digest", &self.tokenizer_digest),
            ("preprocessor_digest", &self.preprocessor_digest),
            ("normalization_digest", &self.normalization_digest),
            ("quantization_digest", &self.quantization_digest),
            ("runtime_digest", &self.runtime_digest),
            ("device_digest", &self.device_digest),
        ] {
            if value.is_empty() || value.len() > 256 || value.contains('\n') {
                return Err(CompositionError::InvalidIdentity(name));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellHeadManifest {
    pub cell_id: String,
    pub head_digest: String,
    pub private_memory_bytes: u64,
    pub maximum_tokens: u32,
}

impl CellHeadManifest {
    fn validate(&self) -> Result<(), CompositionError> {
        if self.cell_id.is_empty() || self.cell_id.len() > 128 || self.cell_id.contains('\n') {
            return Err(CompositionError::InvalidIdentity("cell_id"));
        }
        if self.head_digest.is_empty() || self.head_digest.len() > 256 || self.head_digest.contains('\n') {
            return Err(CompositionError::InvalidIdentity("head_digest"));
        }
        if self.private_memory_bytes == 0 {
            return Err(CompositionError::InvalidMemory("private head"));
        }
        if self.maximum_tokens == 0 {
            return Err(CompositionError::InvalidTokens);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ResidentEncoder {
    key: CompositionKey,
    shared_memory_bytes: u64,
    references: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct BoundCell {
    key: CompositionKey,
    head: CellHeadManifest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionReceipt {
    pub cell_id: String,
    pub encoder_loaded: bool,
    pub shared_memory_bytes: u64,
    pub private_head_memory_bytes: u64,
    pub active_cells: usize,
    pub resident_encoders: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompositionError {
    InvalidIdentity(&'static str),
    InvalidMemory(&'static str),
    InvalidTokens,
    EncoderCapacity,
    CellCapacity,
    CellAlreadyBound,
    CellNotBound,
    EncoderIdentityMismatch,
    CellKeyMismatch,
    DuplicateCellInFanout,
}

impl fmt::Display for CompositionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CompositionError {}

#[derive(Clone, Debug)]
pub struct SharedEncoderPool {
    max_encoders: usize,
    max_cells: usize,
    encoders: BTreeMap<CompositionKey, ResidentEncoder>,
    cells: BTreeMap<String, BoundCell>,
}

impl SharedEncoderPool {
    pub fn new(max_encoders: usize, max_cells: usize) -> Result<Self, CompositionError> {
        if max_encoders == 0 {
            return Err(CompositionError::EncoderCapacity);
        }
        if max_cells == 0 {
            return Err(CompositionError::CellCapacity);
        }
        Ok(Self {
            max_encoders,
            max_cells,
            encoders: BTreeMap::new(),
            cells: BTreeMap::new(),
        })
    }

    pub fn attach_cell(
        &mut self,
        key: CompositionKey,
        head: CellHeadManifest,
        shared_memory_bytes: u64,
    ) -> Result<CompositionReceipt, CompositionError> {
        key.validate()?;
        head.validate()?;
        if shared_memory_bytes == 0 {
            return Err(CompositionError::InvalidMemory("shared encoder"));
        }
        if self.cells.contains_key(&head.cell_id) {
            return Err(CompositionError::CellAlreadyBound);
        }
        if self.cells.len() >= self.max_cells {
            return Err(CompositionError::CellCapacity);
        }

        let encoder_loaded = match self.encoders.get_mut(&key) {
            Some(encoder) => {
                if encoder.shared_memory_bytes != shared_memory_bytes {
                    return Err(CompositionError::EncoderIdentityMismatch);
                }
                encoder.references += 1;
                false
            }
            None => {
                if self.encoders.len() >= self.max_encoders {
                    return Err(CompositionError::EncoderCapacity);
                }
                self.encoders.insert(
                    key.clone(),
                    ResidentEncoder {
                        key: key.clone(),
                        shared_memory_bytes,
                        references: 1,
                    },
                );
                true
            }
        };
        self.cells.insert(
            head.cell_id.clone(),
            BoundCell {
                key: key.clone(),
                head: head.clone(),
            },
        );
        Ok(self.receipt_for(&key, &head.cell_id, encoder_loaded))
    }

    pub fn detach_cell(&mut self, cell_id: &str) -> Result<CompositionReceipt, CompositionError> {
        let cell = self.cells.remove(cell_id).ok_or(CompositionError::CellNotBound)?;
        let key = cell.key.clone();
        let encoder = self.encoders.get_mut(&key).ok_or(CompositionError::CellKeyMismatch)?;
        encoder.references = encoder.references.saturating_sub(1);
        let shared_memory_bytes = encoder.shared_memory_bytes;
        if encoder.references == 0 {
            self.encoders.remove(&key);
        }
        Ok(CompositionReceipt {
            cell_id: cell_id.to_owned(),
            encoder_loaded: false,
            shared_memory_bytes,
            private_head_memory_bytes: cell.head.private_memory_bytes,
            active_cells: self.cells.len(),
            resident_encoders: self.encoders.len(),
        })
    }

    pub fn fanout(
        &self,
        key: &CompositionKey,
        cell_ids: &[String],
    ) -> Result<CompositionReceipt, CompositionError> {
        key.validate()?;
        if cell_ids.is_empty() {
            return Err(CompositionError::CellCapacity);
        }
        let encoder = self.encoders.get(key).ok_or(CompositionError::CellKeyMismatch)?;
        let mut seen = std::collections::BTreeSet::new();
        let mut private_head_memory_bytes = 0_u64;
        for cell_id in cell_ids {
            if !seen.insert(cell_id) {
                return Err(CompositionError::DuplicateCellInFanout);
            }
            let cell = self.cells.get(cell_id).ok_or(CompositionError::CellNotBound)?;
            if &cell.key != key {
                return Err(CompositionError::CellKeyMismatch);
            }
            private_head_memory_bytes = private_head_memory_bytes
                .checked_add(cell.head.private_memory_bytes)
                .ok_or(CompositionError::InvalidMemory("fanout total"))?;
        }
        Ok(CompositionReceipt {
            cell_id: format!("fanout:{}", cell_ids.len()),
            encoder_loaded: false,
            shared_memory_bytes: encoder.shared_memory_bytes,
            private_head_memory_bytes,
            active_cells: cell_ids.len(),
            resident_encoders: self.encoders.len(),
        })
    }

    pub fn resident_encoder_count(&self) -> usize {
        self.encoders.len()
    }

    pub fn active_cell_count(&self) -> usize {
        self.cells.len()
    }

    pub fn total_resident_memory_bytes(&self) -> u64 {
        self.encoders.values().map(|item| item.shared_memory_bytes).sum::<u64>()
            + self.cells.values().map(|item| item.head.private_memory_bytes).sum::<u64>()
    }

    fn receipt_for(&self, key: &CompositionKey, cell_id: &str, encoder_loaded: bool) -> CompositionReceipt {
        let encoder = self.encoders.get(key).expect("attached encoder must be resident");
        let head = self.cells.get(cell_id).expect("attached head must be bound");
        CompositionReceipt {
            cell_id: cell_id.to_owned(),
            encoder_loaded,
            shared_memory_bytes: encoder.shared_memory_bytes,
            private_head_memory_bytes: head.head.private_memory_bytes,
            active_cells: self.cells.len(),
            resident_encoders: self.encoders.len(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(device: &str) -> CompositionKey {
        CompositionKey {
            encoder_digest: "encoder-v1".into(),
            tokenizer_digest: "tokenizer-v1".into(),
            preprocessor_digest: "preprocessor-v1".into(),
            normalization_digest: "normalization-v1".into(),
            quantization_digest: "quantization-v1".into(),
            runtime_digest: "runtime-v1".into(),
            device_digest: device.into(),
        }
    }

    fn head(cell_id: &str, bytes: u64) -> CellHeadManifest {
        CellHeadManifest {
            cell_id: cell_id.into(),
            head_digest: format!("head-{cell_id}"),
            private_memory_bytes: bytes,
            maximum_tokens: 128,
        }
    }

    #[test]
    fn shared_encoder_loads_once_and_heads_fan_out() {
        let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
        let first = pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        let second = pool.attach_cell(key("cuda-0"), head("cell-b", 20), 100).expect("second");
        assert!(first.encoder_loaded);
        assert!(!second.encoder_loaded);
        assert_eq!(pool.resident_encoder_count(), 1);
        assert_eq!(pool.total_resident_memory_bytes(), 140);
        let fanout = pool.fanout(&key("cuda-0"), &["cell-a".into(), "cell-b".into()]).expect("fanout");
        assert_eq!(fanout.shared_memory_bytes, 100);
        assert_eq!(fanout.private_head_memory_bytes, 40);
    }

    #[test]
    fn encoder_identity_includes_runtime_and_device() {
        let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
        pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        let second = pool.attach_cell(key("cuda-1"), head("cell-b", 20), 100).expect("second");
        assert!(second.encoder_loaded);
        assert_eq!(pool.resident_encoder_count(), 2);
    }

    #[test]
    fn mismatched_shared_bytes_are_rejected() {
        let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
        pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        assert_eq!(
            pool.attach_cell(key("cuda-0"), head("cell-b", 20), 101),
            Err(CompositionError::EncoderIdentityMismatch)
        );
    }

    #[test]
    fn detached_last_cell_releases_encoder() {
        let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
        pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        pool.attach_cell(key("cuda-0"), head("cell-b", 20), 100).expect("second");
        pool.detach_cell("cell-a").expect("detach first");
        assert_eq!(pool.resident_encoder_count(), 1);
        pool.detach_cell("cell-b").expect("detach last");
        assert_eq!(pool.resident_encoder_count(), 0);
        assert_eq!(pool.active_cell_count(), 0);
    }

    #[test]
    fn fanout_rejects_cross_device_cell() {
        let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
        pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        pool.attach_cell(key("cuda-1"), head("cell-b", 20), 100).expect("second");
        assert_eq!(
            pool.fanout(&key("cuda-0"), &["cell-a".into(), "cell-b".into()]),
            Err(CompositionError::CellKeyMismatch)
        );
    }

    #[test]
    fn capacity_is_fail_closed() {
        let mut pool = SharedEncoderPool::new(1, 1).expect("pool");
        pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100).expect("first");
        assert_eq!(
            pool.attach_cell(key("cuda-1"), head("cell-b", 20), 100),
            Err(CompositionError::CellCapacity)
        );
        assert_eq!(
            pool.attach_cell(key("cuda-0"), head("cell-c", 20), 100),
            Err(CompositionError::CellCapacity)
        );
    }
}
