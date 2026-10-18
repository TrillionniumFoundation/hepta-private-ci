//! Advisory capacity and process-local latency/I/O diagnostics. No receipt,
//! checkpoint, semantic identity, authority decision or SLA depends on these.
use crate::NeuronIoMetricsV2;
use serde::Serialize;

const PPM: u128 = 1_000_000;
const WARNING_PPM: u32 = 800_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronStorageObservationV2 {
    pub file_bytes: Option<u64>,
    pub io: NeuronIoMetricsV2,
}

/// Process-local phase measurements for one guarded execution or one
/// reconciliation-only call. These values are diagnostics, never durable
/// identity or authorization evidence.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronRuntimeMeasurementV2 {
    pub total_micros: u64,
    pub returned_success: bool,
    pub recovery_only: bool,
    pub admission_micros: u64,
    pub local_reconciliation_micros: u64,
    pub provider_micros: u64,
    pub transition_micros: u64,
    pub receipt_encode_micros: u64,
    /// Nested within `receipt_encode_micros`: time spent constructing the
    /// immutable full-receipt byte vector, including the required checkpoint
    /// payload copy. It is not added again by `unclassified_micros`.
    pub full_receipt_materialize_micros: u64,
    pub store_commit_micros: u64,
    pub index_commit_micros: u64,
    pub witness_micros: u64,
    pub final_use_check_micros: u64,
    pub checkpoint_payload_bytes: u64,
    pub full_receipt_bytes: u64,
    pub store_before: NeuronStorageObservationV2,
    pub store_after: NeuronStorageObservationV2,
    pub index_before: NeuronStorageObservationV2,
    pub index_after: NeuronStorageObservationV2,
    pub witness_sync: Option<NeuronIoMetricsV2>,
}

impl NeuronRuntimeMeasurementV2 {
    #[must_use]
    pub fn store_io(&self) -> NeuronIoMetricsV2 {
        self.store_after.io.since(self.store_before.io)
    }

    #[must_use]
    pub fn index_io(&self) -> NeuronIoMetricsV2 {
        self.index_after.io.since(self.index_before.io)
    }

    /// Receipt preparation excluding the nested immutable full-receipt
    /// materialization/copy interval.
    #[must_use]
    pub fn receipt_encode_excluding_materialization_micros(&self) -> u64 {
        self.receipt_encode_micros
            .saturating_sub(self.full_receipt_materialize_micros)
    }

    /// Store work excluding measured file-sync time. This includes durable
    /// framing/checksums, cloning already-materialized immutable payloads and
    /// in-memory bookkeeping performed by the store.
    #[must_use]
    pub fn store_non_sync_micros(&self) -> u64 {
        self.store_commit_micros
            .saturating_sub(self.store_io().sync_micros)
    }

    /// Index work excluding measured file-sync time.
    #[must_use]
    pub fn index_non_sync_micros(&self) -> u64 {
        self.index_commit_micros
            .saturating_sub(self.index_io().sync_micros)
    }

    #[must_use]
    pub fn measured_sync_micros(&self) -> u64 {
        self.store_io()
            .sync_micros
            .saturating_add(self.index_io().sync_micros)
            .saturating_add(self.witness_sync.map_or(0, |value| value.sync_micros))
    }

    #[must_use]
    pub fn unclassified_micros(&self) -> u64 {
        let classified = self
            .admission_micros
            .saturating_add(self.local_reconciliation_micros)
            .saturating_add(self.provider_micros)
            .saturating_add(self.transition_micros)
            .saturating_add(self.receipt_encode_micros)
            .saturating_add(self.store_commit_micros)
            .saturating_add(self.index_commit_micros)
            .saturating_add(self.witness_micros)
            .saturating_add(self.final_use_check_micros);
        self.total_micros.saturating_sub(classified)
    }
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
    #[must_use]
    pub fn effective_bytes(self) -> u64 {
        self.file_bytes.saturating_add(self.reserved_bytes)
    }

    #[must_use]
    pub fn remaining_records(self) -> usize {
        self.record_limit.saturating_sub(self.records)
    }

    #[must_use]
    pub fn remaining_bytes(self) -> u64 {
        self.byte_limit.saturating_sub(self.effective_bytes())
    }

    /// Maximum of record and byte utilization, in parts per million. Invalid
    /// zero limits fail closed as fully utilized; valid stores never expose them.
    #[must_use]
    pub fn utilization_ppm(self) -> u32 {
        fn ratio(used: u128, limit: u128) -> u32 {
            if limit == 0 {
                return PPM as u32;
            }
            let value = used.saturating_mul(PPM) / limit;
            u32::try_from(value.min(PPM)).unwrap_or(PPM as u32)
        }
        ratio(self.records as u128, self.record_limit as u128).max(ratio(
            u128::from(self.effective_bytes()),
            u128::from(self.byte_limit),
        ))
    }

    /// Advisory 80% warning; actual key/payload-dependent admission remains the
    /// authority and may reject before this watermark. Never delete to recover.
    #[must_use]
    pub fn near_limit(self) -> bool {
        self.utilization_ppm() >= WARNING_PPM
    }

    /// A zero remaining record or byte budget requires explicit backpressure.
    /// Admission can still reject earlier for payload-specific reservations.
    #[must_use]
    pub fn exhausted(self) -> bool {
        self.remaining_records() == 0 || self.remaining_bytes() == 0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuronRuntimeCapacityV2 {
    pub generation: NeuronStorageCapacityV2,
    pub index: NeuronStorageCapacityV2,
    pub witness_records_remaining: Option<usize>,
}

impl NeuronRuntimeCapacityV2 {
    #[must_use]
    pub fn near_limit(self) -> bool {
        self.generation.near_limit() || self.index.near_limit()
    }

    #[must_use]
    pub fn requires_backpressure(self) -> bool {
        self.generation.exhausted()
            || self.index.exhausted()
            || self.witness_records_remaining == Some(0)
    }

    /// Stable advisory code for metrics and runbooks. Authoritative admission
    /// remains in the generation store, index and witness implementations.
    #[must_use]
    pub fn action_code(self) -> &'static str {
        if self.requires_backpressure() {
            "backpressure"
        } else if self.near_limit() {
            "schedule_generation_handoff"
        } else {
            "serve"
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capacity(
        records: usize,
        record_limit: usize,
        bytes: u64,
        byte_limit: u64,
    ) -> NeuronStorageCapacityV2 {
        NeuronStorageCapacityV2 {
            records,
            record_limit,
            file_bytes: bytes,
            byte_limit,
            reserved_bytes: 0,
        }
    }

    #[test]
    fn utilization_and_headroom_include_reserved_bytes() {
        let value = NeuronStorageCapacityV2 {
            records: 4,
            record_limit: 10,
            file_bytes: 60,
            byte_limit: 100,
            reserved_bytes: 20,
        };
        assert_eq!(value.effective_bytes(), 80);
        assert_eq!(value.remaining_records(), 6);
        assert_eq!(value.remaining_bytes(), 20);
        assert_eq!(value.utilization_ppm(), 800_000);
        assert!(value.near_limit());
        assert!(!value.exhausted());
    }

    #[test]
    fn arithmetic_saturates_and_zero_limits_fail_closed() {
        let value = NeuronStorageCapacityV2 {
            records: usize::MAX,
            record_limit: 0,
            file_bytes: u64::MAX,
            byte_limit: 0,
            reserved_bytes: u64::MAX,
        };
        assert_eq!(value.effective_bytes(), u64::MAX);
        assert_eq!(value.utilization_ppm(), 1_000_000);
        assert!(value.exhausted());
    }

    #[test]
    fn runtime_action_code_distinguishes_warning_and_backpressure() {
        let healthy = NeuronRuntimeCapacityV2 {
            generation: capacity(1, 10, 10, 100),
            index: capacity(1, 10, 10, 100),
            witness_records_remaining: Some(10),
        };
        assert_eq!(healthy.action_code(), "serve");

        let warning = NeuronRuntimeCapacityV2 {
            generation: capacity(8, 10, 10, 100),
            ..healthy
        };
        assert_eq!(warning.action_code(), "schedule_generation_handoff");

        let blocked = NeuronRuntimeCapacityV2 {
            witness_records_remaining: Some(0),
            ..healthy
        };
        assert_eq!(blocked.action_code(), "backpressure");
    }
}
