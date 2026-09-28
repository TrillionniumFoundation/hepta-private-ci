// Bounded actionable owner metrics and fixed-bucket stage measurements.

use std::array;
use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use super::operational_state::OwnerOperationalGauges;

const BUCKETS_US: [u64; 16] = [
    50,
    100,
    250,
    500,
    1_000,
    2_500,
    5_000,
    10_000,
    25_000,
    50_000,
    100_000,
    250_000,
    500_000,
    1_000_000,
    5_000_000,
    u64::MAX,
];

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerStageV1 {
    PayloadValidationHash,
    RequestIdentityPersistence,
    RecoveryScan,
    PayloadWriteSync,
    RegistryWriteSync,
    CurrentSwitch,
    CheckpointAcknowledge,
    StartupRecovery,
    CurrentView,
    PinnedLoad,
    WithdrawalPersistence,
    DrainPersistence,
}

impl ArtifactOwnerStageV1 {
    const ALL: [Self; 12] = [
        Self::PayloadValidationHash,
        Self::RequestIdentityPersistence,
        Self::RecoveryScan,
        Self::PayloadWriteSync,
        Self::RegistryWriteSync,
        Self::CurrentSwitch,
        Self::CheckpointAcknowledge,
        Self::StartupRecovery,
        Self::CurrentView,
        Self::PinnedLoad,
        Self::WithdrawalPersistence,
        Self::DrainPersistence,
    ];

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::PayloadValidationHash => "payload_validation_hash",
            Self::RequestIdentityPersistence => "request_identity_persistence",
            Self::RecoveryScan => "recovery_scan",
            Self::PayloadWriteSync => "payload_write_sync",
            Self::RegistryWriteSync => "registry_write_sync",
            Self::CurrentSwitch => "current_switch",
            Self::CheckpointAcknowledge => "checkpoint_acknowledge",
            Self::StartupRecovery => "startup_recovery",
            Self::CurrentView => "current_view",
            Self::PinnedLoad => "pinned_load",
            Self::WithdrawalPersistence => "withdrawal_persistence",
            Self::DrainPersistence => "drain_persistence",
        }
    }
}
