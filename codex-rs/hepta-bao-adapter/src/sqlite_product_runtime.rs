//! Product composition for the async SQLite Bao owner.
//!
//! This is the normal durable ingress/recovery surface for selected product
//! hosts. The JSON owner remains a bounded migration/reference oracle. Recovery
//! workers lease rows through the SQLite queue and never redispatch a secret
//! read or re-enter a consumer.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use super::*;
use crate::SqliteBaoOwnerErrorV1;
use crate::SqliteBaoOwnerMetricsV1;
use crate::SqliteBaoOwnerV1;
use crate::SqliteConsumptionRecordV1;
use crate::SqliteReconciliationClaimV1;

const MAX_RUNTIME_LEASE_MS: u64 = 5 * 60 * 1_000;
const WORKER_DURATION_SAMPLE_LIMIT: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoSqliteProductRuntimeConfigV1 {
    pub forward_executor_id: String,
    pub recovery_worker_id: String,
    pub forward_execution_lease_ms: u64,
    pub recovery_lease_ms: u64,
    pub recovery_batch_limit: u32,
    pub recovery_retry_base_ms: u64,
    pub recovery_retry_max_ms: u64,
}

impl Default for BaoSqliteProductRuntimeConfigV1 {
    fn default() -> Self {
        Self {
            forward_executor_id: "secrets.heptabao.forward".to_owned(),
            recovery_worker_id: "secrets.heptabao.recovery".to_owned(),
            forward_execution_lease_ms: 180_000,
            recovery_lease_ms: 60_000,
            recovery_batch_limit: 32,
            recovery_retry_base_ms: 1_000,
            recovery_retry_max_ms: 60_000,
        }
    }
}

impl BaoSqliteProductRuntimeConfigV1 {
    fn validate(&self) -> Result<(), BaoFinalUseHostError> {
        if !consumer_id(&self.forward_executor_id)
            || !consumer_id(&self.recovery_worker_id)
            || self.forward_executor_id == self.recovery_worker_id
            || self.forward_execution_lease_ms == 0
            || self.forward_execution_lease_ms > MAX_RUNTIME_LEASE_MS
            || self.recovery_lease_ms == 0
            || self.recovery_lease_ms > MAX_RUNTIME_LEASE_MS
            || self.recovery_batch_limit == 0
            || self.recovery_batch_limit > 1_024
            || self.recovery_retry_base_ms == 0
            || self.recovery_retry_base_ms > self.recovery_retry_max_ms
        {
            return Err(BaoFinalUseHostError::InvalidRuntimeConfiguration);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoRecoveryBatchReportV1 {
    pub claimed: u64,
    pub succeeded: u64,
    pub terminal_failed: u64,
    pub rescheduled: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoRecoveryWorkerMetricsV1 {
    pub batches: u64,
    pub claimed: u64,
    pub succeeded: u64,
    pub terminal_failed: u64,
    pub rescheduled: u64,
    pub awaiting_original_evidence: u64,
    pub awaiting_settlement: u64,
    pub identity_conflicts: u64,
    pub owner_failures: u64,
    pub last_batch_duration_micros: u64,
    pub max_batch_duration_micros: u64,
    pub p50_batch_duration_micros: u64,
    pub p95_batch_duration_micros: u64,
    pub p99_batch_duration_micros: u64,
}

#[derive(Default)]
struct BaoRecoveryWorkerMetricsOwnerV1 {
    batches: u64,
    claimed: u64,
    succeeded: u64,
    terminal_failed: u64,
    rescheduled: u64,
    awaiting_original_evidence: u64,
    awaiting_settlement: u64,
    identity_conflicts: u64,
    owner_failures: u64,
    batch_duration_samples_micros: VecDeque<u64>,
    last_batch_duration_micros: u64,
    max_batch_duration_micros: u64,
}

impl BaoRecoveryWorkerMetricsOwnerV1 {
    fn record(
        &mut self,
        started: Instant,
        report: &BaoRecoveryBatchReportV1,
        classes: &[BaoProductErrorClassV1],
    ) {
        self.batches = self.batches.saturating_add(1);
        self.claimed = self.claimed.saturating_add(report.claimed);
        self.succeeded = self.succeeded.saturating_add(report.succeeded);
        self.terminal_failed = self.terminal_failed.saturating_add(report.terminal_failed);
        self.rescheduled = self.rescheduled.saturating_add(report.rescheduled);
        for class in classes {
            match class {
                BaoProductErrorClassV1::AwaitingOriginalEvidence => {
                    self.awaiting_original_evidence =
                        self.awaiting_original_evidence.saturating_add(1);
                }
                BaoProductErrorClassV1::AwaitingSettlement => {
                    self.awaiting_settlement = self.awaiting_settlement.saturating_add(1);
                }
                BaoProductErrorClassV1::IdentityConflict => {
                    self.identity_conflicts = self.identity_conflicts.saturating_add(1);
                }
                BaoProductErrorClassV1::DurableOwnerFailure
                | BaoProductErrorClassV1::CommitIndeterminate
                | BaoProductErrorClassV1::OwnerBusy
                | BaoProductErrorClassV1::CapacityRejected => {
                    self.owner_failures = self.owner_failures.saturating_add(1);
                }
                BaoProductErrorClassV1::AdmissionRejected
                | BaoProductErrorClassV1::ReconciliationRequired
                | BaoProductErrorClassV1::HistoricalTerminalFailure
                | BaoProductErrorClassV1::ExternalControlFailure => {}
            }
        }
        let micros = elapsed_micros(started);
        self.last_batch_duration_micros = micros;
        self.max_batch_duration_micros = self.max_batch_duration_micros.max(micros);
        if self.batch_duration_samples_micros.len() == WORKER_DURATION_SAMPLE_LIMIT {
            self.batch_duration_samples_micros.pop_front();
        }
        self.batch_duration_samples_micros.push_back(micros);
    }

    fn snapshot(&self) -> BaoRecoveryWorkerMetricsV1 {
        let mut samples = self
            .batch_duration_samples_micros
            .iter()
            .copied()
            .collect::<Vec<_>>();
        samples.sort_unstable();
        BaoRecoveryWorkerMetricsV1 {
            batches: self.batches,
            claimed: self.claimed,
            succeeded: self.succeeded,
            terminal_failed: self.terminal_failed,
            rescheduled: self.rescheduled,
            awaiting_original_evidence: self.awaiting_original_evidence,
            awaiting_settlement: self.awaiting_settlement,
            identity_conflicts: self.identity_conflicts,
            owner_failures: self.owner_failures,
            last_batch_duration_micros: self.last_batch_duration_micros,
            max_batch_duration_micros: self.max_batch_duration_micros,
            p50_batch_duration_micros: operation_percentile(&samples, 50),
            p95_batch_duration_micros: operation_percentile(&samples, 95),
            p99_batch_duration_micros: operation_percentile(&samples, 99),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteBaoProductRuntimeMetricsV1 {
    pub operations: BaoOperationMetricsV1,
    pub owner: SqliteBaoOwnerMetricsV1,
    pub recovery_worker: BaoRecoveryWorkerMetricsV1,
}

pub struct SqliteBaoProductRuntimeV1 {
    host: Arc<BaoFinalUseHost>,
    owner: Arc<SqliteBaoOwnerV1>,
    config: BaoSqliteProductRuntimeConfigV1,
    recovery_metrics: Mutex<BaoRecoveryWorkerMetricsOwnerV1>,
}

impl std::fmt::Debug for SqliteBaoProductRuntimeV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SqliteBaoProductRuntimeV1")
            .field("owner_fenced", &self.owner.is_fenced())
            .field("recovery_batch_limit", &self.config.recovery_batch_limit)
            .finish_non_exhaustive()
    }
}

impl SqliteBaoProductRuntimeV1 {
    pub fn new(
        host: Arc<BaoFinalUseHost>,
        owner: Arc<SqliteBaoOwnerV1>,
        config: BaoSqliteProductRuntimeConfigV1,
    ) -> Result<Self, BaoFinalUseHostError> {
        config.validate()?;
        if owner.is_fenced() {
            return Err(BaoFinalUseHostError::Unavailable);
        }
        Ok(Self {
            host,
            owner,
            config,
            recovery_metrics: Mutex::new(Default::default()),
        })
    }

    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let started = Instant::now();
        let result = self
            .host
            .consume_kv_v2_with_authbus_sqlite(
                client,
                authbus,
                &self.owner,
                &self.config.forward_executor_id,
                self.config.forward_execution_lease_ms,
                read,
                evidence,
            )
            .await;
        self.host.record_forward_metric(started, &result);
        result
    }

    pub async fn reconcile_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let terminal = self
            .owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if let Some(result) = historical_result(terminal.operation) {
            return result;
        }
        let now_unix_ms = self.host.product_now()?;
        let mut claim = self
            .owner
            .claim_reconciliation_operation(
                &self.config.recovery_worker_id,
                operation_id,
                now_unix_ms,
                self.config.recovery_lease_ms,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        let started = Instant::now();
        let result = self
            .host
            .reconcile_sqlite_claim(authbus, &self.owner, &claim, evidence)
            .await;
        self.host.record_recovery_metric(started, &result);
        if result.is_err() {
            self.reschedule_claim(&mut claim, result.as_ref().unwrap_err())
                .await?;
        }
        result
    }

    pub async fn reconcile_due<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        evidence: &mut E,
    ) -> Result<BaoRecoveryBatchReportV1, BaoProductHostError> {
        let batch_started = Instant::now();
        let now_unix_ms = self.host.product_now()?;
        let claims = self
            .owner
            .claim_due_reconciliation(
                &self.config.recovery_worker_id,
                now_unix_ms,
                self.config.recovery_lease_ms,
                self.config.recovery_batch_limit,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        let mut report = BaoRecoveryBatchReportV1 {
            claimed: u64::try_from(claims.len()).unwrap_or(u64::MAX),
            succeeded: 0,
            terminal_failed: 0,
            rescheduled: 0,
        };
        let mut classes = Vec::new();
        for mut claim in claims {
            let started = Instant::now();
            let result = self
                .host
                .reconcile_sqlite_claim(authbus, &self.owner, &claim, evidence)
                .await;
            self.host.record_recovery_metric(started, &result);
            match &result {
                Ok(_) => report.succeeded = report.succeeded.saturating_add(1),
                Err(BaoProductHostError::TerminalFailure(Box::new(_))) => {
                    report.terminal_failed = report.terminal_failed.saturating_add(1);
                    classes.push(BaoProductErrorClassV1::HistoricalTerminalFailure);
                }
                Err(error) => {
                    classes.push(error.class());
                    self.reschedule_claim(&mut claim, error).await?;
                    report.rescheduled = report.rescheduled.saturating_add(1);
                }
            }
        }
        if let Ok(mut metrics) = self.recovery_metrics.lock() {
            metrics.record(batch_started, &report, &classes);
        }
        Ok(report)
    }

    pub async fn metrics(&self) -> Result<SqliteBaoProductRuntimeMetricsV1, BaoProductHostError> {
        let now_unix_ms = self.host.product_now()?;
        let owner = self
            .owner
            .metrics(now_unix_ms)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        let recovery_worker = self
            .recovery_metrics
            .lock()
            .map(|metrics| metrics.snapshot())
            .unwrap_or_else(|_| BaoRecoveryWorkerMetricsOwnerV1::default().snapshot());
        Ok(SqliteBaoProductRuntimeMetricsV1 {
            operations: self.host.operation_metrics(),
            owner,
            recovery_worker,
        })
    }

    async fn reschedule_claim(
        &self,
        claim: &mut SqliteReconciliationClaimV1,
        error: &BaoProductHostError,
    ) -> Result<(), BaoProductHostError> {
        let latest = match self
            .owner
            .consumption_result(&claim.record.operation.operation_id)
            .await
        {
            Ok(record) => record,
            Err(SqliteBaoOwnerErrorV1::OperationNotFound) => return Ok(()),
            Err(error) => return Err(BaoProductHostError::SqliteStore(error)),
        };
        if latest.operation.state.is_terminal() {
            return Ok(());
        }
        claim.record = latest;
        let observed_at_unix_ms = self.host.product_now()?;
        let delay = retry_delay_ms(
            self.config.recovery_retry_base_ms,
            self.config.recovery_retry_max_ms,
            claim.attempt_count,
        );
        let next_attempt_at_unix_ms =
            observed_at_unix_ms
                .checked_add(delay)
                .ok_or(BaoProductHostError::SqliteStore(
                    SqliteBaoOwnerErrorV1::CapacityExceeded,
                ))?;
        let error_sha256 = recovery_error_digest(error.class());
        self.owner
            .record_claimed_reconciliation_failure(
                claim,
                observed_at_unix_ms,
                next_attempt_at_unix_ms,
                error_sha256,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        Ok(())
    }
}

impl BaoFinalUseHost {
    fn product_now(&self) -> Result<u64, BaoProductHostError> {
        self.clock
            .now_unix_ms()
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Trust(error)))
    }

    async fn consume_kv_v2_with_authbus_sqlite<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        owner: &Arc<SqliteBaoOwnerV1>,
        execution_owner: &str,
        execution_lease_ms: u64,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let BaoApprovedReadV1 {
            admission,
            grant,
            approval,
            request,
        } = read;
        validate_product_admission(admission).map_err(BaoProductHostError::Host)?;
        self.approved_consumer(grant, approval, &request.consumer_id)
            .map_err(BaoProductHostError::Host)?;
        let registration = self
            .consumers
            .get(&request.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        let configuration = registration
            .configuration_sha256
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if request.consumer_configuration_sha256 != Some(configuration) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let callback = registration
            .operation_callback
            .clone()
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        let binding = client
            .binding(request)
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Client(error)))?;
        let effect = client
            .authbus_effect_digest(request, &admission.operation_id)
            .map_err(|error| BaoProductHostError::Host(BaoFinalUseHostError::Client(error)))?;
        let semantics = serde_json::to_vec(&(
            "hepta.bao.durable-product.v2",
            effect.as_array(),
            admission.policy_revision,
            admission.quota_key.as_str(),
            admission.expected_quota_revision,
            admission.amount,
            admission.expires_at_ms,
            grant,
            approval,
            configuration,
        ))
        .map_err(|_| BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::InvalidInput))?;
        let semantic_sha256 = Digest32::of_bytes(&semantics).into_array();
        let operation_id = admission.operation_id.as_str().to_owned();
        let operation = BaoConsumptionOperationV1 {
            operation_id: operation_id.clone(),
            semantic_sha256,
            effect_sha256: effect.into_array(),
            request_sha256: binding.request_sha256,
            consumer_id: request.consumer_id.clone(),
            consumer_configuration_sha256: configuration,
            amount: admission.amount,
            reservation_id: None,
            state: BaoConsumptionStateV1::Claimed,
            receipt: None,
            created_revision: 0,
            updated_revision: 0,
            terminal_kind: None,
            terminal_code: None,
            terminal_evidence_sha256: None,
            terminal_observed_cost: None,
        };
        let now_unix_ms = self.product_now()?;
        let execution = owner
            .claim_consumption_for_execution(
                operation,
                now_unix_ms,
                execution_owner,
                execution_lease_ms,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if !execution.claim.inserted {
            return historical_result_or_pending(execution.claim.record.operation);
        }
        let execution_claim = execution.execution.ok_or(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::CorruptState("new forward operation has no execution lease"),
        ))?;

        let result = self
            .execute_claimed_sqlite_consumption(
                client,
                authbus,
                owner,
                &operation_id,
                semantic_sha256,
                callback,
                admission,
                grant,
                request,
                evidence,
            )
            .await;
        release_execution_claim_if_pending(owner, &execution_claim).await;
        result
    }

    #[allow(clippy::too_many_arguments)]
    async fn execute_claimed_sqlite_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        owner: &Arc<SqliteBaoOwnerV1>,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        callback: BaoOperationConsumerCallback,
        admission: &BaoAuthBusAdmission,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let reserved_owner = Arc::clone(owner);
        let reserved_clock = Arc::clone(&self.clock);
        let reserved_operation = operation_id.to_owned();
        let fenced_owner = Arc::clone(owner);
        let fenced_clock = Arc::clone(&self.clock);
        let fenced_operation = operation_id.to_owned();
        let provider_owner = Arc::clone(owner);
        let provider_clock = Arc::clone(&self.clock);
        let provider_operation = operation_id.to_owned();
        let preparation_owner = Arc::clone(owner);
        let preparation_clock = Arc::clone(&self.clock);
        let preparation_operation = operation_id.to_owned();
        let success_owner = Arc::clone(owner);
        let success_clock = Arc::clone(&self.clock);
        let success_operation = operation_id.to_owned();

        let saga_result = crate::authbus_saga::consume_kv_v2_with_authbus_saga(
            client,
            authbus,
            crate::BaoAuthorizedReadV1 {
                admission,
                authority: &self.authority,
                grant,
                request,
            },
            evidence,
            crate::authbus_saga::BaoAuthBusSagaHooks {
                reserved: move |reservation: &QuotaReservation| {
                    let owner = Arc::clone(&reserved_owner);
                    let clock = Arc::clone(&reserved_clock);
                    let operation_id = reserved_operation.clone();
                    let reservation = reservation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_reserved(
                                &operation_id,
                                current.revision,
                                reservation.reservation_id.as_str().to_owned(),
                                reservation_evidence(b"hepta.bao.sqlite.reserved.v1", &reservation),
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                dispatch_fenced: move |reservation: &QuotaReservation| {
                    let owner = Arc::clone(&fenced_owner);
                    let clock = Arc::clone(&fenced_clock);
                    let operation_id = fenced_operation.clone();
                    let reservation = reservation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_dispatch_fenced(
                                &operation_id,
                                current.revision,
                                reservation_evidence(
                                    b"hepta.bao.sqlite.dispatch-fenced.v1",
                                    &reservation,
                                ),
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                provider_terminal: move |error: BaoClientError, terminal: Digest32| {
                    let owner = Arc::clone(&provider_owner);
                    let clock = Arc::clone(&provider_clock);
                    let operation_id = provider_operation.clone();
                    async move {
                        let code =
                            provider_failure_code(error).ok_or(BaoAuthBusError::Evidence(
                                "nonterminal provider error classified terminal",
                            ))?;
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_provider_failed(
                                &operation_id,
                                current.revision,
                                code.to_owned(),
                                terminal.into_array(),
                                current.operation.amount,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                prepare_delivery: move |receipt: &BaoSecretReceipt| {
                    let owner = Arc::clone(&preparation_owner);
                    let clock = Arc::clone(&preparation_clock);
                    let operation_id = preparation_operation.clone();
                    let receipt = receipt.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        let digest = receipt
                            .evidence_digest()
                            .map_err(|_| BaoAuthBusError::Evidence("receipt encoding failed"))?;
                        owner
                            .prepare_consumption_delivery(
                                &operation_id,
                                current.revision,
                                receipt,
                                digest,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
                consumer: move |secret: &[u8], _receipt: &BaoSecretReceipt| {
                    self.ensure_revocation_fresh().map_err(|_| ())?;
                    callback(operation_id, semantic_sha256, secret)
                },
                consumer_succeeded: move |_receipt: &BaoSecretReceipt| {
                    let owner = Arc::clone(&success_owner);
                    let clock = Arc::clone(&success_clock);
                    let operation_id = success_operation.clone();
                    async move {
                        let current = owner.consumption_result(&operation_id).await?;
                        owner
                            .mark_consumption_succeeded(
                                &operation_id,
                                current.revision,
                                clock_now_for_saga(&clock)?,
                            )
                            .await?;
                        Ok(())
                    }
                },
            },
        )
        .await;

        match saga_result {
            Ok(receipt) => {
                let current = owner
                    .consumption_result(operation_id)
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                owner
                    .settle_consumption_terminal(
                        operation_id,
                        current.revision,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                Ok(receipt)
            }
            Err(error @ BaoAuthBusError::Provider(_)) => {
                let current = owner
                    .consumption_result(operation_id)
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                if current.operation.state == BaoConsumptionStateV1::ProviderFailed {
                    let terminal = owner
                        .settle_consumption_terminal(
                            operation_id,
                            current.revision,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                    Err(BaoProductHostError::TerminalFailure(Box::new(
                        terminal.operation,
                    )))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
            Err(error @ BaoAuthBusError::Indeterminate { .. }) => {
                self.mark_sqlite_indeterminate(owner, operation_id, &error)
                    .await?;
                Err(BaoProductHostError::AuthBus(error))
            }
            Err(error) => {
                if let Some(terminal) = self
                    .close_unreserved_sqlite_failure(authbus, owner, operation_id, &error)
                    .await?
                {
                    Err(BaoProductHostError::TerminalFailure(Box::new(terminal)))
                } else {
                    Err(BaoProductHostError::AuthBus(error))
                }
            }
        }
    }

    async fn mark_sqlite_indeterminate(
        &self,
        owner: &SqliteBaoOwnerV1,
        operation_id: &str,
        _error: &BaoAuthBusError,
    ) -> Result<(), BaoProductHostError> {
        let current = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if current
            .operation
            .state
            .allows_transition_to(BaoConsumptionStateV1::Indeterminate)
        {
            owner
                .mark_consumption_indeterminate(
                    operation_id,
                    current.revision,
                    Digest32::of_bytes(b"hepta.bao.sqlite.indeterminate.v1").into_array(),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        Ok(())
    }

    async fn close_unreserved_sqlite_failure(
        &self,
        authbus: &AuthBusAuthorityHost,
        owner: &SqliteBaoOwnerV1,
        operation_id: &str,
        error: &BaoAuthBusError,
    ) -> Result<Option<BaoConsumptionOperationV1>, BaoProductHostError> {
        let row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if row.operation.state != BaoConsumptionStateV1::Claimed {
            return Ok(None);
        }
        let stable_operation = StableId::new(operation_id.to_owned()).map_err(|_| {
            BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                "invalid durable operation identifier",
            ))
        })?;
        if authbus
            .seal_unreserved_operation(
                &stable_operation,
                Digest32::from_array(row.operation.effect_sha256),
            )
            .await
            .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            .is_some()
        {
            return Ok(None);
        }
        let evidence = Digest32::of_bytes(
            format!("hepta.bao.sqlite.pre-reservation.v1:{operation_id}:{error:?}").as_bytes(),
        )
        .into_array();
        let terminal = owner
            .abort_consumption_before_reservation(
                operation_id,
                row.revision,
                evidence,
                self.product_now()?,
            )
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        Ok(Some(terminal.operation))
    }

    async fn reconcile_sqlite_claim<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        owner: &SqliteBaoOwnerV1,
        claim: &SqliteReconciliationClaimV1,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let operation_id = claim.record.operation.operation_id.as_str();
        let mut row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if let Some(result) = historical_result(row.operation.clone()) {
            return result;
        }
        let registration = self
            .consumers
            .get(&row.operation.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if registration.configuration_sha256 != Some(row.operation.consumer_configuration_sha256) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let stable_operation = StableId::new(operation_id.to_owned()).map_err(|_| {
            BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                "invalid durable operation identifier",
            ))
        })?;
        let reservation = match row.operation.reservation_id.as_deref() {
            Some(value) => {
                let reservation_id = StableId::new(value.to_owned()).map_err(|_| {
                    BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                        "invalid durable reservation identifier",
                    ))
                })?;
                Some(
                    authbus
                        .reservation(&reservation_id)
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
                )
            }
            None => authbus
                .seal_unreserved_operation(
                    &stable_operation,
                    Digest32::from_array(row.operation.effect_sha256),
                )
                .await
                .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
        };
        let Some(mut reservation) = reservation else {
            if matches!(
                row.operation.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) {
                let terminal_evidence = abort_evidence(&row.operation, "no_reservation", None);
                let terminal = owner
                    .abort_consumption_before_reservation(
                        operation_id,
                        row.revision,
                        terminal_evidence,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                return Err(BaoProductHostError::TerminalFailure(Box::new(
                    terminal.operation,
                )));
            }
            return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
        };
        validate_sqlite_reservation(&row.operation, &reservation)?;

        if matches!(
            row.operation.state,
            BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
        ) {
            row = owner
                .mark_consumption_reserved(
                    operation_id,
                    row.revision,
                    reservation.reservation_id.as_str().to_owned(),
                    reservation_evidence(b"hepta.bao.sqlite.recovery-reserved.v1", &reservation),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        if matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) && matches!(
            row.operation.state,
            BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
        ) {
            row = owner
                .mark_consumption_dispatch_fenced(
                    operation_id,
                    row.revision,
                    reservation_evidence(
                        b"hepta.bao.sqlite.recovery-dispatch-fenced.v1",
                        &reservation,
                    ),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        if reservation.state == ReservationState::Indeterminate
            && row
                .operation
                .state
                .allows_transition_to(BaoConsumptionStateV1::Indeterminate)
        {
            row = owner
                .mark_consumption_indeterminate(
                    operation_id,
                    row.revision,
                    reservation_evidence(
                        b"hepta.bao.sqlite.recovery-indeterminate.v1",
                        &reservation,
                    ),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }

        match reservation.state {
            ReservationState::Held => {
                if !matches!(
                    row.operation.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    return Err(BaoProductHostError::SqliteStore(
                        SqliteBaoOwnerErrorV1::ObservationMismatch,
                    ));
                }
                let time = authbus
                    .observe_trusted_time_attestation(
                        &evidence
                            .trusted_time()
                            .map_err(BaoProductHostError::AuthBus)?,
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?;
                reservation = if time.wall_time_ms() >= reservation.expires_at_ms {
                    authbus
                        .reconcile_expired_reservation(
                            &reservation.reservation_id,
                            reservation.revision,
                            time,
                        )
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                } else {
                    authbus
                        .cancel_reservation(&reservation.reservation_id, reservation.revision, time)
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                };
                let code = reservation_terminal_abort_code(reservation.state)?;
                let terminal_evidence = abort_evidence(&row.operation, code, Some(&reservation));
                let terminal = owner
                    .abort_consumption_before_dispatch(
                        operation_id,
                        row.revision,
                        code,
                        terminal_evidence,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                return Err(BaoProductHostError::TerminalFailure(Box::new(
                    terminal.operation,
                )));
            }
            ReservationState::Cancelled
            | ReservationState::Expired
            | ReservationState::Released => {
                if matches!(
                    row.operation.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let code = reservation_terminal_abort_code(reservation.state)?;
                    let terminal_evidence =
                        abort_evidence(&row.operation, code, Some(&reservation));
                    let terminal = owner
                        .abort_consumption_before_dispatch(
                            operation_id,
                            row.revision,
                            code,
                            terminal_evidence,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                    return Err(BaoProductHostError::TerminalFailure(Box::new(
                        terminal.operation,
                    )));
                }
            }
            ReservationState::DispatchAttempted
            | ReservationState::Indeterminate
            | ReservationState::Settled => {}
        }

        row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if matches!(
            row.operation.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) && row.operation.receipt.is_some()
        {
            let observer = registration
                .observer
                .as_ref()
                .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
            match observer(operation_id, row.operation.semantic_sha256) {
                Ok(BaoConsumerObservationV1::Succeeded) => {
                    row = owner
                        .mark_consumption_succeeded(operation_id, row.revision, self.product_now()?)
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                }
                Ok(BaoConsumerObservationV1::NotAppliedWithEvidence { evidence_sha256 }) => {
                    row = owner
                        .mark_consumption_not_applied(
                            operation_id,
                            row.revision,
                            evidence_sha256,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                }
                Ok(BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown)
                | Err(()) => {
                    return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
                }
            }
        }

        match row.operation.state {
            BaoConsumptionStateV1::ConsumerSucceeded
            | BaoConsumptionStateV1::ProviderFailed
            | BaoConsumptionStateV1::ConsumerNotApplied => {
                settle_sqlite_terminal_row(self, authbus, owner, row, reservation, evidence).await
            }
            BaoConsumptionStateV1::Succeeded => {
                row.operation
                    .receipt
                    .ok_or(BaoProductHostError::SqliteStore(
                        SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
                    ))
            }
            BaoConsumptionStateV1::Failed => Err(BaoProductHostError::TerminalFailure(Box::new(
                row.operation,
            ))),
            _ => Err(BaoProductHostError::OutcomePending(Box::new(row.operation))),
        }
    }
}

async fn settle_sqlite_terminal_row<E: BaoAuthBusEvidenceProvider>(
    host: &BaoFinalUseHost,
    authbus: &AuthBusAuthorityHost,
    owner: &SqliteBaoOwnerV1,
    row: SqliteConsumptionRecordV1,
    reservation: QuotaReservation,
    evidence: &mut E,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    let terminal = Digest32::from_array(row.operation.terminal_evidence_sha256.ok_or(
        BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
            "terminal evidence is missing",
        )),
    )?);
    let (status, observed_cost, success) = match row.operation.state {
        BaoConsumptionStateV1::ConsumerSucceeded => {
            (SettlementStatus::Completed, row.operation.amount, true)
        }
        BaoConsumptionStateV1::ProviderFailed => (
            SettlementStatus::Completed,
            row.operation
                .terminal_observed_cost
                .ok_or(BaoProductHostError::SqliteStore(
                    SqliteBaoOwnerErrorV1::CorruptState("provider terminal cost is missing"),
                ))?,
            false,
        ),
        BaoConsumptionStateV1::ConsumerNotApplied => (SettlementStatus::Rejected, 0, false),
        _ => {
            return Err(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::InvalidTransition,
            ));
        }
    };
    let expected_terminal_state = match status {
        SettlementStatus::Completed => ReservationState::Settled,
        SettlementStatus::Rejected => ReservationState::Released,
    };
    if matches!(
        reservation.state,
        ReservationState::Settled | ReservationState::Released
    ) {
        if reservation.state != expected_terminal_state
            || reservation.terminal_evidence != Some(terminal)
            || reservation.observed_cost != Some(observed_cost)
        {
            return Err(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::ObservationMismatch,
            ));
        }
    } else {
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
        }
        crate::https_consumer::settle_observed(
            authbus,
            evidence,
            &reservation,
            status,
            observed_cost,
            terminal,
            if success {
                row.operation.receipt.clone()
            } else {
                None
            },
        )
        .await
        .map_err(BaoProductHostError::AuthBus)?;
    }
    let terminal_row = owner
        .settle_consumption_terminal(
            &row.operation.operation_id,
            row.revision,
            host.product_now()?,
        )
        .await
        .map_err(BaoProductHostError::SqliteStore)?;
    if success {
        terminal_row
            .operation
            .receipt
            .ok_or(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
            ))
    } else {
        Err(BaoProductHostError::TerminalFailure(Box::new(
            terminal_row.operation,
        )))
    }
}

fn historical_result(
    operation: BaoConsumptionOperationV1,
) -> Option<Result<BaoSecretReceipt, BaoProductHostError>> {
    match operation.state.recovery_action() {
        BaoConsumptionRecoveryActionV1::ReturnHistoricalSuccess => {
            Some(operation.receipt.ok_or(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
            )))
        }
        BaoConsumptionRecoveryActionV1::ReturnHistoricalFailure => Some(Err(
            BaoProductHostError::TerminalFailure(Box::new(operation)),
        )),
        BaoConsumptionRecoveryActionV1::SealOrBindReservation
        | BaoConsumptionRecoveryActionV1::CancelOrExpireReservation
        | BaoConsumptionRecoveryActionV1::BindLegacyReservation
        | BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome
        | BaoConsumptionRecoveryActionV1::SettleTerminalEvidence => None,
    }
}

fn historical_result_or_pending(
    operation: BaoConsumptionOperationV1,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    historical_result(operation.clone())
        .unwrap_or_else(|| Err(BaoProductHostError::OutcomePending(Box::new(operation))))
}

async fn release_execution_claim_if_pending(
    owner: &SqliteBaoOwnerV1,
    claim: &SqliteReconciliationClaimV1,
) {
    if let Ok(record) = owner
        .consumption_result(&claim.record.operation.operation_id)
        .await
        && !record.operation.state.is_terminal()
    {
        let _ = owner
            .release_reconciliation_claim(
                &claim.worker_id,
                &claim.record.operation.operation_id,
                claim.claim_generation,
            )
            .await;
    }
}

fn validate_sqlite_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), BaoProductHostError> {
    if reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::ObservationMismatch,
        ));
    }
    Ok(())
}

fn reservation_terminal_abort_code(
    state: ReservationState,
) -> Result<&'static str, BaoProductHostError> {
    match state {
        ReservationState::Expired => Ok("reservation_expired"),
        ReservationState::Cancelled => Ok("reservation_cancelled"),
        ReservationState::Released => Ok("reservation_released"),
        ReservationState::Held
        | ReservationState::DispatchAttempted
        | ReservationState::Indeterminate
        | ReservationState::Settled => Err(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::ObservationMismatch,
        )),
    }
}

fn reservation_evidence(label: &[u8], reservation: &QuotaReservation) -> [u8; 32] {
    let mut bytes = Vec::with_capacity(256);
    push_evidence_part(&mut bytes, label);
    push_evidence_part(&mut bytes, reservation.reservation_id.as_str().as_bytes());
    push_evidence_part(&mut bytes, reservation.operation_id.as_str().as_bytes());
    push_evidence_part(&mut bytes, reservation.effect_digest.as_array());
    push_evidence_part(&mut bytes, &reservation.revision.to_be_bytes());
    push_evidence_part(&mut bytes, format!("{:?}", reservation.state).as_bytes());
    Digest32::of_bytes(&bytes).into_array()
}

fn push_evidence_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn clock_now_for_saga(clock: &Arc<dyn AuthorityClock>) -> Result<u64, BaoAuthBusError> {
    clock
        .now_unix_ms()
        .map_err(|_| BaoAuthBusError::Evidence("product authority clock unavailable"))
}

fn recovery_error_digest(class: BaoProductErrorClassV1) -> [u8; 32] {
    Digest32::of_bytes(format!("hepta.bao.recovery-error.v1:{class:?}").as_bytes()).into_array()
}

fn retry_delay_ms(base: u64, maximum: u64, attempt_count: u64) -> u64 {
    let exponent = u32::try_from(attempt_count.min(31)).unwrap_or(31);
    base.checked_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .unwrap_or(u64::MAX)
        .min(maximum)
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn runtime_configuration_is_bounded_and_has_distinct_workers() {
        assert!(
            BaoSqliteProductRuntimeConfigV1::default()
                .validate()
                .is_ok()
        );
        let mut invalid = BaoSqliteProductRuntimeConfigV1::default();
        invalid.recovery_worker_id = invalid.forward_executor_id.clone();
        assert_eq!(
            invalid.validate(),
            Err(BaoFinalUseHostError::InvalidRuntimeConfiguration)
        );
        invalid = BaoSqliteProductRuntimeConfigV1::default();
        invalid.recovery_batch_limit = 1_025;
        assert_eq!(
            invalid.validate(),
            Err(BaoFinalUseHostError::InvalidRuntimeConfiguration)
        );
    }

    #[test]
    fn retry_backoff_is_bounded() {
        assert_eq!(retry_delay_ms(1_000, 60_000, 0), 1_000);
        assert_eq!(retry_delay_ms(1_000, 60_000, 3), 8_000);
        assert_eq!(retry_delay_ms(1_000, 60_000, 63), 60_000);
    }
}
