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
    pub weights_digest: String,
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
            ("weights_digest", &self.weights_digest),
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
pub struct CompositionManifestV1 {
    pub cell_id: String,
    pub encoder_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub normalization_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub head_digest: String,
    pub private_memory_bytes: u64,
    pub maximum_tokens: u32,
}

impl CompositionManifestV1 {
    pub fn validate(&self) -> Result<(), CompositionError> {
        self.key().validate()?;
        self.head().validate()
    }

    pub fn key(&self) -> CompositionKey {
        CompositionKey {
            encoder_digest: self.encoder_digest.clone(),
            weights_digest: self.weights_digest.clone(),
            tokenizer_digest: self.tokenizer_digest.clone(),
            preprocessor_digest: self.preprocessor_digest.clone(),
            normalization_digest: self.normalization_digest.clone(),
            quantization_digest: self.quantization_digest.clone(),
            runtime_digest: self.runtime_digest.clone(),
            device_digest: self.device_digest.clone(),
        }
    }

    pub fn head(&self) -> CellHeadManifest {
        CellHeadManifest {
            cell_id: self.cell_id.clone(),
            head_digest: self.head_digest.clone(),
            private_memory_bytes: self.private_memory_bytes,
            maximum_tokens: self.maximum_tokens,
        }
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


    pub fn private_memory_bytes(&self) -> u64 {
        self.private_memory_bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ResidentEncoder {
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
    InvalidRequest,
    DriverFailure(&'static str),
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


    pub fn attach_manifest(
        &mut self,
        manifest: CompositionManifestV1,
    ) -> Result<CompositionReceipt, CompositionError> {
        manifest.validate()?;
        self.attach_cell(manifest.key(), manifest.head(), manifest.private_memory_bytes)
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
        self.receipt_for(&key, &head.cell_id, encoder_loaded)
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


    pub fn key_for_cell(&self, cell_id: &str) -> Result<CompositionKey, CompositionError> {
        self.cells
            .get(cell_id)
            .map(|cell| cell.key.clone())
            .ok_or(CompositionError::CellNotBound)
    }

    pub fn head_for_cell(&self, cell_id: &str) -> Result<CellHeadManifest, CompositionError> {
        self.cells
            .get(cell_id)
            .map(|cell| cell.head.clone())
            .ok_or(CompositionError::CellNotBound)
    }

    pub fn encoder_reference_count(&self, key: &CompositionKey) -> Result<usize, CompositionError> {
        self.encoders
            .get(key)
            .map(|encoder| encoder.references)
            .ok_or(CompositionError::CellKeyMismatch)
    }

    fn receipt_for(
        &self,
        key: &CompositionKey,
        cell_id: &str,
        encoder_loaded: bool,
    ) -> Result<CompositionReceipt, CompositionError> {
        let encoder = self.encoders.get(key).ok_or(CompositionError::CellKeyMismatch)?;
        let head = self.cells.get(cell_id).ok_or(CompositionError::CellNotBound)?;
        Ok(CompositionReceipt {
            cell_id: cell_id.to_owned(),
            encoder_loaded,
            shared_memory_bytes: encoder.shared_memory_bytes,
            private_head_memory_bytes: head.head.private_memory_bytes,
            active_cells: self.cells.len(),
            resident_encoders: self.encoders.len(),
        })
    }
}


#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionRequest {
    pub cell_id: String,
    pub input_digest: String,
    pub maximum_tokens: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionRunObservation {
    pub output_digest: String,
    pub consumed_tokens: u32,
}

pub trait CompositionDriver {
    type Handle: Clone;

    fn load_encoder(&mut self, key: &CompositionKey) -> Result<Self::Handle, CompositionError>;
    fn unload_encoder(
        &mut self,
        key: &CompositionKey,
        handle: Self::Handle,
    ) -> Result<(), CompositionError>;
    fn run_head(
        &mut self,
        handle: &Self::Handle,
        head: &CellHeadManifest,
        request: &CompositionRequest,
    ) -> Result<CompositionRunObservation, CompositionError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompositionExecutionObservation {
    pub cell_id: String,
    pub output_digest: String,
    pub consumed_tokens: u32,
    pub shared_memory_bytes: u64,
    pub private_head_memory_bytes: u64,
}

pub struct CompositionWorker<D: CompositionDriver> {
    pool: SharedEncoderPool,
    driver: D,
    handles: BTreeMap<CompositionKey, D::Handle>,
}

impl<D: CompositionDriver> CompositionWorker<D> {
    pub fn new(pool: SharedEncoderPool, driver: D) -> Self {
        Self {
            pool,
            driver,
            handles: BTreeMap::new(),
        }
    }

    pub fn attach_cell(
        &mut self,
        key: CompositionKey,
        head: CellHeadManifest,
        shared_memory_bytes: u64,
    ) -> Result<CompositionReceipt, CompositionError> {
        let cell_id = head.cell_id.clone();
        let receipt = self.pool.attach_cell(key.clone(), head, shared_memory_bytes)?;
        if receipt.encoder_loaded {
            match self.driver.load_encoder(&key) {
                Ok(handle) => {
                    self.handles.insert(key, handle);
                }
                Err(error) => {
                    let _ = self.pool.detach_cell(&cell_id);
                    return Err(error);
                }
            }
        }
        Ok(receipt)
    }

    pub fn detach_cell(&mut self, cell_id: &str) -> Result<CompositionReceipt, CompositionError> {
        let key = self.pool.key_for_cell(cell_id)?;
        let references = self.pool.encoder_reference_count(&key)?;
        if references == 1 {
            let handle = self
                .handles
                .remove(&key)
                .ok_or(CompositionError::DriverFailure("missing encoder handle"))?;
            if let Err(error) = self.driver.unload_encoder(&key, handle.clone()) {
                self.handles.insert(key, handle);
                return Err(error);
            }
        }
        self.pool.detach_cell(cell_id)
    }

    pub fn run(
        &mut self,
        request: CompositionRequest,
    ) -> Result<CompositionExecutionObservation, CompositionError> {
        if request.cell_id.is_empty()
            || request.input_digest.is_empty()
            || request.maximum_tokens == 0
        {
            return Err(CompositionError::InvalidRequest);
        }
        let key = self.pool.key_for_cell(&request.cell_id)?;
        let head = self.pool.head_for_cell(&request.cell_id)?;
        if request.maximum_tokens > head.maximum_tokens {
            return Err(CompositionError::InvalidTokens);
        }
        let handle = self
            .handles
            .get(&key)
            .ok_or(CompositionError::DriverFailure("missing encoder handle"))?;
        let observed = self.driver.run_head(handle, &head, &request)?;
        if observed.consumed_tokens > request.maximum_tokens {
            return Err(CompositionError::InvalidTokens);
        }
        Ok(CompositionExecutionObservation {
            cell_id: request.cell_id,
            output_digest: observed.output_digest,
            consumed_tokens: observed.consumed_tokens,
            shared_memory_bytes: self
                .pool
                .fanout(&key, &[head.cell_id.clone()])?
                .shared_memory_bytes,
            private_head_memory_bytes: head.private_memory_bytes,
        })
    }

    pub fn resident_encoder_count(&self) -> usize {
        self.pool.resident_encoder_count()
    }

    pub fn active_cell_count(&self) -> usize {
        self.pool.active_cell_count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(device: &str) -> CompositionKey {
        CompositionKey {
            encoder_digest: "encoder-v1".into(),
            weights_digest: "weights-v1".into(),
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


    #[derive(Default)]
    struct WorkerDriver {
        loads: usize,
        unloads: usize,
        runs: usize,
    }

    impl CompositionDriver for WorkerDriver {
        type Handle = String;

        fn load_encoder(&mut self, key: &CompositionKey) -> Result<Self::Handle, CompositionError> {
            self.loads += 1;
            Ok(format!("encoder:{}", key.device_digest))
        }

        fn unload_encoder(
            &mut self,
            _key: &CompositionKey,
            _handle: Self::Handle,
        ) -> Result<(), CompositionError> {
            self.unloads += 1;
            Ok(())
        }

        fn run_head(
            &mut self,
            handle: &Self::Handle,
            head: &CellHeadManifest,
            request: &CompositionRequest,
        ) -> Result<CompositionRunObservation, CompositionError> {
            self.runs += 1;
            assert!(handle.starts_with("encoder:"));
            assert_eq!(head.cell_id, request.cell_id);
            Ok(CompositionRunObservation {
                output_digest: format!("output:{}", request.input_digest),
                consumed_tokens: request.maximum_tokens,
            })
        }
    }

    #[test]
    fn composition_worker_loads_once_and_unloads_after_last_cell() {
        let pool = SharedEncoderPool::new(2, 8).expect("pool");
        let mut worker = CompositionWorker::new(pool, WorkerDriver::default());
        worker
            .attach_cell(key("cuda-0"), head("cell-a", 20), 100)
            .expect("first");
        worker
            .attach_cell(key("cuda-0"), head("cell-b", 20), 100)
            .expect("second");
        assert_eq!(worker.driver.loads, 1);
        let observed = worker
            .run(CompositionRequest {
                cell_id: "cell-b".into(),
                input_digest: "input-1".into(),
                maximum_tokens: 16,
            })
            .expect("run");
        assert_eq!(observed.shared_memory_bytes, 100);
        assert_eq!(worker.driver.runs, 1);
        worker.detach_cell("cell-a").expect("detach first");
        assert_eq!(worker.driver.unloads, 0);
        worker.detach_cell("cell-b").expect("detach last");
        assert_eq!(worker.driver.unloads, 1);
        assert_eq!(worker.resident_encoder_count(), 0);
    }


    fn manifest(cell_id: &str, weights: &str) -> CompositionManifestV1 {
        CompositionManifestV1 {
            cell_id: cell_id.into(),
            encoder_digest: "encoder-v1".into(),
            weights_digest: weights.into(),
            tokenizer_digest: "tokenizer-v1".into(),
            preprocessor_digest: "preprocessor-v1".into(),
            normalization_digest: "normalization-v1".into(),
            quantization_digest: "quantization-v1".into(),
            runtime_digest: "runtime-v1".into(),
            device_digest: "cuda-0".into(),
            head_digest: format!("head-{cell_id}"),
            private_memory_bytes: 20,
            maximum_tokens: 128,
        }
    }

    #[test]
    fn manifest_bridge_binds_base_weights_and_private_head() {
        let mut worker = CompositionWorker::new(
            SharedEncoderPool::new(2, 8).expect("pool"),
            WorkerDriver::default(),
        );
        worker.attach_manifest(manifest("cell-a", "weights-v1")).expect("manifest");
        worker.attach_manifest(manifest("cell-b", "weights-v1")).expect("manifest");
        assert_eq!(worker.driver.loads, 1);
        assert_eq!(worker.active_cell_count(), 2);
        worker.attach_manifest(manifest("cell-c", "weights-v2")).expect("new weights");
        assert_eq!(worker.driver.loads, 2);
        assert_eq!(worker.resident_encoder_count(), 2);
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
