//! Advisory capacity and process-local latency/I/O diagnostics. No receipt,
//! checkpoint, semantic identity, authority decision or SLA depends on these.
use serde::Serialize;
use crate::NeuronIoMetricsV2;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronStorageObservationV2 {
    pub file_bytes: Option<u64>,
    pub io: NeuronIoMetricsV2,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronRuntimeMeasurementV2 {
    pub total_micros: u64,
    pub returned_success: bool,
    pub store_before: NeuronStorageObservationV2,
    pub store_after: NeuronStorageObservationV2,
    pub index_before: NeuronStorageObservationV2,
    pub index_after: NeuronStorageObservationV2,
    pub witness_sync: Option<NeuronIoMetricsV2>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronStorageCapacityV2 {
    pub records: usize,
    pub record_limit: usize,
    pub file_bytes: u64,
    pub byte_limit: u64,
    pub reserved_bytes: u64,
}

impl NeuronStorageCapacityV2 {
    /// Advisory 80% warning; actual key/payload-dependent admission remains the
    /// authority and may reject before this watermark. Never delete to recover.
    pub fn near_limit(&self) -> bool {
        (self.records as u128) * 5 >= (self.record_limit as u128) * 4
            || u128::from(self.file_bytes.saturating_add(self.reserved_bytes)) * 5
                >= u128::from(self.byte_limit) * 4
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronRuntimeCapacityV2 {
    pub generation: NeuronStorageCapacityV2,
    pub index: NeuronStorageCapacityV2,
    pub witness_records_remaining: Option<usize>,
}
