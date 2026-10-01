//! Durable metadata-only SecretLease lifecycle owner.
//!
//! This module deliberately stores no secret value. Provider effects are
//! represented as observations so a timeout or crash remains `Unknown` until a
//! trusted reconciler observes the original operation. The Unix storage profile
//! is single-writer: an advisory lock fences parallel owners, replacement is
//! synchronized before success, and a post-replacement durability failure
//! fences the open writer until it is reopened.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use serde::Deserialize;
use serde::Serialize;

#[path = "consumption_lifecycle.rs"]
mod consumption;
pub use consumption::BaoConsumptionOperationV1;
pub use consumption::BaoConsumptionPhaseV1;
pub use consumption::BaoConsumptionRecoveryActionV1;
pub use consumption::BaoConsumptionStateV1;
pub use consumption::BaoSecretReceipt;
pub use consumption::BaoSecretTelemetryV1;

const LEGACY_SCHEMA_VERSION: u32 = 1;
const INTERMEDIATE_SCHEMA_VERSION: u32 = 2;
const PREVIOUS_SCHEMA_VERSION: u32 = 3;
const SCHEMA_VERSION: u32 = 4;
const MAX_RECORDS: usize = 65_536;
const MAX_METADATA_BYTES: usize = 16 * 1024;
const MAX_STORE_BYTES: usize = 8 * 1024 * 1024;
const CONTROL_RESERVE_BYTES: usize = 64 * 1024;
const CONSUMPTION_FUTURE_RESERVE_BYTES: usize = 4096;
const COMMIT_DURATION_SAMPLE_LIMIT: usize = 256;
const INITIALIZED_MARKER: &[u8] = b"hepta.secret-lease-registry.initialized.v1\n";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationKindV1 {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationStateV1 {
    Prepared,
    Unknown,
    Applied,
    Denied,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseStateV1 {
    Active,
    RenewUnknown,
    RevokeUnknown,
    Revoked,
    Expired,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadataV1 {
    pub lease_id: String,
    pub secret_reference_id: String,
    pub consumer_id: String,
    pub scope_sha256: [u8; 32],
    pub provider_metadata_sha256: [u8; 32],
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub generation: u64,
    pub state: SecretLeaseStateV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseOperationV1 {
    pub operation_id: String,
    pub kind: LeaseOperationKindV1,
    pub semantic_sha256: [u8; 32],
    pub lease_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_generation: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_at_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resulting_generation: Option<u64>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub legacy_binding_incomplete: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result_lease: Option<SecretLeaseMetadataV1>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result_observation: Option<ProviderLeaseObservationV1>,
    pub state: LeaseOperationStateV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseOperationResultV1 {
    pub operation: LeaseOperationV1,
    pub lease: Option<SecretLeaseMetadataV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProviderLeaseObservationV1 {
    IssueApplied {
        lease: SecretLeaseMetadataV1,
    },
    RenewApplied {
        lease_id: String,
        observed_at_unix_ms: u64,
        expires_at_unix_ms: u64,
        renewable: bool,
        provider_metadata_sha256: [u8; 32],
    },
    RevokeApplied {
        lease_id: String,
        observed_at_unix_ms: u64,
        provider_metadata_sha256: [u8; 32],
    },
    Denied,
    NotApplied,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredRegistryV1 {
    schema_version: u32,
    #[serde(default)]
    revision: u64,
    #[serde(default)]
    time_frontier_unix_ms: u64,
    operations: BTreeMap<String, LeaseOperationV1>,
    leases: BTreeMap<String, SecretLeaseMetadataV1>,
    #[serde(default)]
    consumptions: BTreeMap<String, BaoConsumptionOperationV1>,
}

trait LeaseRegistryPersistenceV1: Send + Sync {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
    fn sync_parent(&self, parent: &Path) -> io::Result<()>;
}

#[derive(Debug)]
struct FsLeaseRegistryPersistenceV1;

impl LeaseRegistryPersistenceV1 for FsLeaseRegistryPersistenceV1 {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut options = private_file_options();
        let mut file = options.write(true).create_new(true).open(path)?;
        file.write_all(bytes)?;
        file.sync_all()
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        fs::rename(from, to)
    }

    fn sync_parent(&self, parent: &Path) -> io::Result<()> {
        File::open(parent)?.sync_all()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseRegistryCommitMetricsV1 {
    pub attempts: u64,
    pub confirmed_commits: u64,
    pub rejected_commits: u64,
    pub unavailable_commits: u64,
    pub indeterminate_commits: u64,
    pub writer_fence_events: u64,
    pub attempted_bytes: u64,
    pub confirmed_bytes: u64,
    pub last_duration_micros: u64,
    pub max_duration_micros: u64,
    pub p50_duration_micros: u64,
    pub p95_duration_micros: u64,
    pub p99_duration_micros: u64,
}

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LeaseRegistryMigrationSnapshotV1 {
    pub schema_version: u32,
    pub revision: u64,
    pub time_frontier_unix_ms: u64,
    pub operations: Vec<LeaseOperationV1>,
    pub leases: Vec<SecretLeaseMetadataV1>,
    pub consumptions: Vec<BaoConsumptionOperationV1>,
}

impl std::fmt::Debug for LeaseRegistryMigrationSnapshotV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LeaseRegistryMigrationSnapshotV1")
            .field("schema_version", &self.schema_version)
            .field("revision", &self.revision)
            .field("time_frontier_unix_ms", &self.time_frontier_unix_ms)
            .field("operation_count", &self.operations.len())
            .field("lease_count", &self.leases.len())
            .field("consumption_count", &self.consumptions.len())
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LeaseRegistryDiagnosticsV1 {
    pub schema_version: u32,
    pub revision: u64,
    pub lease_operation_count: usize,
    pub lease_count: usize,
    pub consumption_count: usize,
    pub consumption_by_state: BTreeMap<BaoConsumptionStateV1, usize>,
    pub pending_by_recovery_action: BTreeMap<BaoConsumptionRecoveryActionV1, usize>,
    pub pending_quota_amount: u64,
    pub post_dispatch_without_receipt: usize,
    pub observer_pending: usize,
    pub settlement_pending: usize,
    pub oldest_pending_age_revisions: u64,
    pub encoded_bytes: usize,
    pub lease_future_reserve_bytes: usize,
    pub consumption_future_reserve_bytes: usize,
    pub max_store_bytes: usize,
    pub available_bytes: usize,
    pub fenced: bool,
    pub commit_metrics: LeaseRegistryCommitMetricsV1,
}

#[derive(Default)]
struct LeaseRegistryRuntimeMetricsV1 {
    attempts: u64,
    confirmed_commits: u64,
    rejected_commits: u64,
    unavailable_commits: u64,
    indeterminate_commits: u64,
    writer_fence_events: u64,
    attempted_bytes: u64,
    confirmed_bytes: u64,
    last_duration_micros: u64,
    max_duration_micros: u64,
    duration_samples_micros: VecDeque<u64>,
}

impl LeaseRegistryRuntimeMetricsV1 {
    fn record_duration(&mut self, started: Instant) {
        let micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        self.last_duration_micros = micros;
        self.max_duration_micros = self.max_duration_micros.max(micros);
        if self.duration_samples_micros.len() == COMMIT_DURATION_SAMPLE_LIMIT {
            self.duration_samples_micros.pop_front();
        }
        self.duration_samples_micros.push_back(micros);
    }

    fn snapshot(&self) -> LeaseRegistryCommitMetricsV1 {
        let mut samples = self
            .duration_samples_micros
            .iter()
            .copied()
            .collect::<Vec<_>>();
        samples.sort_unstable();
        LeaseRegistryCommitMetricsV1 {
            attempts: self.attempts,
            confirmed_commits: self.confirmed_commits,
            rejected_commits: self.rejected_commits,
            unavailable_commits: self.unavailable_commits,
            indeterminate_commits: self.indeterminate_commits,
            writer_fence_events: self.writer_fence_events,
            attempted_bytes: self.attempted_bytes,
            confirmed_bytes: self.confirmed_bytes,
            last_duration_micros: self.last_duration_micros,
            max_duration_micros: self.max_duration_micros,
            p50_duration_micros: percentile(&samples, 50),
            p95_duration_micros: percentile(&samples, 95),
            p99_duration_micros: percentile(&samples, 99),
        }
    }
}

fn percentile(samples: &[u64], percentile: usize) -> u64 {
    if samples.is_empty() {
        return 0;
    }
    let last = samples.len() - 1;
    let index = last
        .checked_mul(percentile)
        .and_then(|value| value.checked_add(99))
        .map(|value| value / 100)
        .unwrap_or(last)
        .min(last);
    samples[index]
}

pub struct DurableLeaseRegistryV1 {
    executions: crate::operation_execution::OperationExecutionSet,
    path: PathBuf,
    lock: File,
    state: StoredRegistryV1,
    persistence: Arc<dyn LeaseRegistryPersistenceV1>,
    fenced: bool,
    runtime_metrics: LeaseRegistryRuntimeMetricsV1,
}

impl std::fmt::Debug for DurableLeaseRegistryV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DurableLeaseRegistryV1")
            .field("path", &self.path)
            .field("schema_version", &self.state.schema_version)
            .field("revision", &self.state.revision)
            .field("operation_count", &self.state.operations.len())
            .field("lease_count", &self.state.leases.len())
            .field("consumption_count", &self.state.consumptions.len())
            .field("fenced", &self.fenced)
            .field("commit_attempts", &self.runtime_metrics.attempts)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseRegistryErrorV1 {
    InvalidInput,
    CapacityExceeded,
    OperationConflict,
    OperationNotFound,
    LeaseNotFound,
    InvalidTransition,
    ObservationMismatch,
    CorruptState,
    WriterBusy,
    CommitIndeterminate,
    Fenced,
    UnsupportedPlatform,
    LegacyRequalificationRequired,
    Unavailable,
}

impl std::fmt::Display for LeaseRegistryErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LeaseRegistryErrorV1 {}

impl Drop for DurableLeaseRegistryV1 {
    fn drop(&mut self) {
        let _ = File::unlock(&self.lock);
    }
}

#[cfg(all(test, unix))]
#[path = "lease_lifecycle_tests.rs"]
mod tests;

#[path = "lease_registry_diagnostics.rs"]
mod lease_registry_diagnostics;
#[path = "lease_registry_mutations.rs"]
mod lease_registry_mutations;
#[path = "lease_registry_reconciliation.rs"]
mod lease_registry_reconciliation;
#[path = "lease_registry_storage.rs"]
mod lease_registry_storage;

#[path = "lease_registry_pending.rs"]
mod lease_registry_pending;
use lease_registry_pending::ensure_operation_capacity;
use lease_registry_pending::has_pending_kind;
use lease_registry_pending::has_pending_mutation;
use lease_registry_pending::latest_observed_at;
use lease_registry_pending::new_operation;
use lease_registry_pending::restore_after_negative_observation;

#[path = "lease_registry_validation.rs"]
mod lease_registry_validation;
use lease_registry_validation::migrate_state;
use lease_registry_validation::validate_new_active_lease;
use lease_registry_validation::validate_state;

#[path = "lease_registry_encoding.rs"]
mod lease_registry_encoding;
use lease_registry_encoding::PersistFailure;
use lease_registry_encoding::encode_state;
use lease_registry_encoding::future_reserve_bytes;
use lease_registry_encoding::identifier;
use lease_registry_encoding::parent_directory;
use lease_registry_encoding::persist_bytes;
use lease_registry_encoding::prepare_parent;
use lease_registry_encoding::private_file_options;
use lease_registry_encoding::reject_existing_symlink;
use lease_registry_encoding::remove_if_present;
use lease_registry_encoding::sibling_with_suffix;
use lease_registry_encoding::stamp_consumption_revisions;
use lease_registry_encoding::validate_private_file;
