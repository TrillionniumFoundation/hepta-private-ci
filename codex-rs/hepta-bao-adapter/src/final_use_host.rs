//! Trusted host composition for the Bao final-use consumer.
//!
//! Product code enters the Bao secret-use boundary through this host rather
//! than passing an arbitrary closure directly to `BaoClient`. The signed
//! request's `consumer_id` must resolve to one statically registered callback,
//! the exact grant must have an independent operator approval, and revocation
//! updates are accepted only through an independently pinned signed feed.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::BaoAuthBusAdmission;
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoConsumptionOperationV1;
use crate::BaoConsumptionRecoveryActionV1;
use crate::BaoConsumptionStateV1;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;
use crate::DurableLeaseRegistryV1;
use crate::LeaseRegistryErrorV1;

#[path = "sqlite_product_runtime.rs"]
mod sqlite_product_runtime;
pub use sqlite_product_runtime::BaoRecoveryBatchReportV1;
pub use sqlite_product_runtime::BaoRecoveryWorkerMetricsV1;
pub use sqlite_product_runtime::BaoSqliteProductRuntimeConfigV1;
pub use sqlite_product_runtime::SqliteBaoProductRuntimeMetricsV1;
pub use sqlite_product_runtime::SqliteBaoProductRuntimeV1;

/// Independently approved operation inputs; dependencies remain host-owned.
#[derive(Clone, Copy)]
pub struct BaoApprovedReadV1<'a> {
    pub admission: &'a BaoAuthBusAdmission,
    pub grant: &'a SignedFinalUseGrant,
    pub approval: &'a SignedFinalUseApproval,
    pub request: &'a BaoReadRequest,
}

#[path = "consumer_registration.rs"]
mod consumer_registration;
pub use consumer_registration::BaoConsumerCallback;
pub use consumer_registration::BaoConsumerObservationV1;
pub use consumer_registration::BaoConsumerObserverCallback;
pub use consumer_registration::BaoOperationConsumerCallback;
pub use consumer_registration::BaoOperationConsumerPreparer;
pub use consumer_registration::BaoPreparedConsumerCallback;
pub use consumer_registration::RegisteredBaoConsumer;

const OPERATION_DURATION_SAMPLE_LIMIT: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoOperationLatencyMetricsV1 {
    pub attempts: u64,
    pub succeeded: u64,
    pub admission_rejected: u64,
    pub reconciliation_required: u64,
    pub awaiting_evidence: u64,
    pub awaiting_settlement: u64,
    pub terminal_failed: u64,
    pub identity_conflict: u64,
    pub capacity_rejected: u64,
    pub owner_busy: u64,
    pub commit_indeterminate: u64,
    pub durable_owner_failed: u64,
    pub external_control_failed: u64,
    pub last_duration_micros: u64,
    pub max_duration_micros: u64,
    pub p50_duration_micros: u64,
    pub p95_duration_micros: u64,
    pub p99_duration_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoOperationMetricsV1 {
    pub forward: BaoOperationLatencyMetricsV1,
    pub recovery: BaoOperationLatencyMetricsV1,
}

#[derive(Default)]
struct BaoOperationMetricSeriesV1 {
    attempts: u64,
    succeeded: u64,
    admission_rejected: u64,
    reconciliation_required: u64,
    awaiting_evidence: u64,
    awaiting_settlement: u64,
    terminal_failed: u64,
    identity_conflict: u64,
    capacity_rejected: u64,
    owner_busy: u64,
    commit_indeterminate: u64,
    durable_owner_failed: u64,
    external_control_failed: u64,
    last_duration_micros: u64,
    max_duration_micros: u64,
    duration_samples_micros: VecDeque<u64>,
}

impl BaoOperationMetricSeriesV1 {
    fn record(&mut self, started: Instant, error_class: Option<BaoProductErrorClassV1>) {
        self.attempts = self.attempts.saturating_add(1);
        match error_class {
            None => self.succeeded = self.succeeded.saturating_add(1),
            Some(BaoProductErrorClassV1::AdmissionRejected) => {
                self.admission_rejected = self.admission_rejected.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::ReconciliationRequired) => {
                self.reconciliation_required = self.reconciliation_required.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::AwaitingOriginalEvidence) => {
                self.awaiting_evidence = self.awaiting_evidence.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::AwaitingSettlement) => {
                self.awaiting_settlement = self.awaiting_settlement.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::HistoricalTerminalFailure) => {
                self.terminal_failed = self.terminal_failed.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::IdentityConflict) => {
                self.identity_conflict = self.identity_conflict.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::CapacityRejected) => {
                self.capacity_rejected = self.capacity_rejected.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::OwnerBusy) => {
                self.owner_busy = self.owner_busy.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::CommitIndeterminate) => {
                self.commit_indeterminate = self.commit_indeterminate.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::DurableOwnerFailure) => {
                self.durable_owner_failed = self.durable_owner_failed.saturating_add(1);
            }
            Some(BaoProductErrorClassV1::ExternalControlFailure) => {
                self.external_control_failed = self.external_control_failed.saturating_add(1);
            }
        }
        let micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        self.last_duration_micros = micros;
        self.max_duration_micros = self.max_duration_micros.max(micros);
        if self.duration_samples_micros.len() == OPERATION_DURATION_SAMPLE_LIMIT {
            self.duration_samples_micros.pop_front();
        }
        self.duration_samples_micros.push_back(micros);
    }

    fn snapshot(&self) -> BaoOperationLatencyMetricsV1 {
        let mut samples = self
            .duration_samples_micros
            .iter()
            .copied()
            .collect::<Vec<_>>();
        samples.sort_unstable();
        BaoOperationLatencyMetricsV1 {
            attempts: self.attempts,
            succeeded: self.succeeded,
            admission_rejected: self.admission_rejected,
            reconciliation_required: self.reconciliation_required,
            awaiting_evidence: self.awaiting_evidence,
            awaiting_settlement: self.awaiting_settlement,
            terminal_failed: self.terminal_failed,
            identity_conflict: self.identity_conflict,
            capacity_rejected: self.capacity_rejected,
            owner_busy: self.owner_busy,
            commit_indeterminate: self.commit_indeterminate,
            durable_owner_failed: self.durable_owner_failed,
            external_control_failed: self.external_control_failed,
            last_duration_micros: self.last_duration_micros,
            max_duration_micros: self.max_duration_micros,
            p50_duration_micros: operation_percentile(&samples, 50),
            p95_duration_micros: operation_percentile(&samples, 95),
            p99_duration_micros: operation_percentile(&samples, 99),
        }
    }
}

#[derive(Default)]
struct BaoOperationMetricsOwnerV1 {
    forward: BaoOperationMetricSeriesV1,
    recovery: BaoOperationMetricSeriesV1,
}

impl BaoOperationMetricsOwnerV1 {
    fn snapshot(&self) -> BaoOperationMetricsV1 {
        BaoOperationMetricsV1 {
            forward: self.forward.snapshot(),
            recovery: self.recovery.snapshot(),
        }
    }
}

fn operation_percentile(samples: &[u64], percentile: usize) -> u64 {
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

/// Host-selected composition of final-use authority, independent approval,
/// authenticated revocation distribution and a closed consumer registry.
pub struct BaoFinalUseHost {
    authority: FinalUseAuthority,
    approval_verifier: FinalUseApprovalVerifier,
    revocation_verifier: FinalUseRevocationFeedVerifier,
    clock: Arc<dyn AuthorityClock>,
    revocation_fresh_until_unix_ms: Mutex<u64>,
    consumers: BTreeMap<String, RegisteredBaoConsumer>,
    operation_metrics: Mutex<BaoOperationMetricsOwnerV1>,
}

impl fmt::Debug for BaoFinalUseHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoFinalUseHost")
            .field("authority", &self.authority)
            .field("approval_verifier", &self.approval_verifier)
            .field("revocation_verifier", &self.revocation_verifier)
            .field("consumer_count", &self.consumers.len())
            .finish()
    }
}

impl BaoFinalUseHost {
    pub fn new(
        authority: FinalUseAuthority,
        approval_verifier: FinalUseApprovalVerifier,
        revocation_verifier: FinalUseRevocationFeedVerifier,
        clock: Arc<dyn AuthorityClock>,
        consumers: impl IntoIterator<Item = RegisteredBaoConsumer>,
    ) -> Result<Self, BaoFinalUseHostError> {
        let mut registry = BTreeMap::new();
        for consumer in consumers {
            if registry.insert(consumer.id.clone(), consumer).is_some() {
                return Err(BaoFinalUseHostError::DuplicateConsumer);
            }
        }
        if registry.is_empty() {
            return Err(BaoFinalUseHostError::EmptyConsumerRegistry);
        }
        Ok(Self {
            authority,
            approval_verifier,
            revocation_verifier,
            clock,
            revocation_fresh_until_unix_ms: Mutex::new(0),
            consumers: registry,
            operation_metrics: Mutex::new(Default::default()),
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.consumers.len()
    }

    #[must_use]
    pub fn operation_metrics(&self) -> BaoOperationMetricsV1 {
        self.operation_metrics
            .lock()
            .map(|metrics| metrics.snapshot())
            .unwrap_or_else(|_| BaoOperationMetricsOwnerV1::default().snapshot())
    }

    fn record_forward_metric(
        &self,
        started: Instant,
        result: &Result<BaoSecretReceipt, BaoProductHostError>,
    ) {
        if let Ok(mut metrics) = self.operation_metrics.lock() {
            metrics.forward.record(
                started,
                result.as_ref().err().map(BaoProductHostError::class),
            );
        }
    }

    fn record_recovery_metric(
        &self,
        started: Instant,
        result: &Result<BaoSecretReceipt, BaoProductHostError>,
    ) {
        if let Ok(mut metrics) = self.operation_metrics.lock() {
            metrics.recovery.record(
                started,
                result.as_ref().err().map(BaoProductHostError::class),
            );
        }
    }

    fn ensure_revocation_fresh(&self) -> Result<(), BaoFinalUseHostError> {
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let fresh_until = *self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        if fresh_until == 0 || now_unix_ms >= fresh_until {
            return Err(BaoFinalUseHostError::StaleRevocationFeed);
        }
        Ok(())
    }

    fn approved_consumer(
        &self,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        consumer_id: &str,
    ) -> Result<BaoConsumerCallback, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        self.consumers
            .get(consumer_id)
            .map(|consumer| consumer.callback.clone())
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)
    }

    /// Apply one independently signed revocation head. The feed signature is
    /// checked before the durable authority owner sees the head; the authority
    /// itself enforces epoch/revision monotonicity and same-epoch superset rules.
    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<FinalUseRevocationReceipt, BaoFinalUseHostError> {
        // Publish the durable head and its freshness together. Concurrent feed
        // updates must not replace a newer head's deadline with an older one.
        let mut fresh_until = self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let receipt = self
            .revocation_verifier
            .apply(&self.authority, update, now_unix_ms)
            .map_err(BaoFinalUseHostError::Control)?;
        *fresh_until = receipt.valid_until_unix_ms();
        Ok(receipt)
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_host_tests.rs"]
mod tests;

#[path = "final_use_host_ingress.rs"]
mod final_use_host_ingress;
#[path = "final_use_host_recovery.rs"]
mod final_use_host_recovery;

#[path = "final_use_host_settlement.rs"]
mod final_use_host_settlement;
pub use final_use_host_settlement::BaoFinalUseHostError;
pub use final_use_host_settlement::BaoProductErrorClassV1;
pub use final_use_host_settlement::BaoProductHostError;
use final_use_host_settlement::abort_evidence;
use final_use_host_settlement::consumer_id;
use final_use_host_settlement::provider_failure_code;
use final_use_host_settlement::settle_terminal_row;
use final_use_host_settlement::validate_product_admission;
use final_use_host_settlement::validate_reservation;
