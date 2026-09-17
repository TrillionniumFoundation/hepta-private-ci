use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchObservation;
use crate::DurableOperationRecord;
use crate::DurableOperationStore;
use crate::EffectAdapter;
use crate::MAX_DURABLE_CLAIM_BATCH;
use crate::MAX_DURABLE_LEASE_MS;
use crate::OperationError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurableDispatcherConfig {
    pub batch_limit: u32,
    pub lease_ms: i64,
    pub pre_dispatch_retry_ms: i64,
}

impl Default for DurableDispatcherConfig {
    fn default() -> Self {
        Self {
            batch_limit: 64,
            lease_ms: 30_000,
            pre_dispatch_retry_ms: 1_000,
        }
    }
}

impl DurableDispatcherConfig {
    fn validate(self) -> Result<Self, OperationError> {
        if self.batch_limit == 0 || self.batch_limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(OperationError::InvalidTransition {
                from: "dispatcher",
                to: "invalid_batch_limit",
            });
        }
        if !(1..=MAX_DURABLE_LEASE_MS).contains(&self.lease_ms) {
            return Err(OperationError::InvalidTransition {
                from: "dispatcher",
                to: "invalid_lease_duration",
            });
        }
        if !(0..=MAX_DURABLE_LEASE_MS).contains(&self.pre_dispatch_retry_ms) {
            return Err(OperationError::InvalidTransition {
                from: "dispatcher",
                to: "invalid_retry_delay",
            });
        }
        Ok(self)
    }
}

pub trait FinalUseGrantProvider {
    fn grant_for(
        &mut self,
        operation: &DurableOperationRecord,
    ) -> Result<(SignedFinalUseGrant, FinalUseBinding), OperationError>;
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DispatchRunReport {
    pub discovered: u32,
    pub claimed: u32,
    pub terminal: u32,
    pub acknowledged: u32,
    pub indeterminate: u32,
    pub pre_dispatch_deferred: u32,
    pub stale_or_unavailable: u32,
}

/// Host-driven bounded dispatcher. It has no hidden daemon/global singleton.
/// The host decides cadence and separately schedules terminal reconciliation.
pub struct DurableDispatcher<'a> {
    store: &'a DurableOperationStore,
    authority: &'a FinalUseAuthority,
    config: DurableDispatcherConfig,
}

impl<'a> DurableDispatcher<'a> {
    pub fn new(
        store: &'a DurableOperationStore,
        authority: &'a FinalUseAuthority,
        config: DurableDispatcherConfig,
    ) -> Result<Self, OperationError> {
        Ok(Self {
            store,
            authority,
            config: config.validate()?,
        })
    }

    /// Execute one bounded destination-specific dispatch batch. Only rows that
    /// are safe to resend can enter this loop. Once `dispatch_with_final_use`
    /// arms an attempt, that row leaves the retryable query and can return only
    /// through reconciliation/terminal settlement.
    pub async fn run_once<P: FinalUseGrantProvider, A: EffectAdapter>(
        &self,
        destination_id: &StableId,
        worker_id: &StableId,
        writer_generation: Generation,
        grants: &mut P,
        adapter: &mut A,
    ) -> Result<DispatchRunReport, OperationError> {
        let ready = self
            .store
            .ready_outbox(destination_id, self.config.batch_limit)
            .await?;
        let mut report = DispatchRunReport {
            discovered: u32::try_from(ready.len()).unwrap_or(u32::MAX),
            ..DispatchRunReport::default()
        };
        for row in ready {
            let claim = match self
                .store
                .claim_outbox(
                    &row.scope_id,
                    &row.operation_id,
                    &row.destination_id,
                    worker_id.clone(),
                    writer_generation,
                    self.config.lease_ms,
                )
                .await
            {
                Ok(claim) => claim,
                Err(OperationError::StaleGeneration)
                | Err(OperationError::StaleLease)
                | Err(OperationError::LeaseUnavailable) => {
                    report.stale_or_unavailable = report.stale_or_unavailable.saturating_add(1);
                    continue;
                }
                Err(error) => return Err(error),
            };
            report.claimed = report.claimed.saturating_add(1);
            let (grant, binding) = match grants.grant_for(&claim.operation) {
                Ok(value) => value,
                Err(_) => {
                    // Grant acquisition is strictly pre-effect and therefore
                    // may be retried after a bounded delay.
                    self.store
                        .retry_claim(&claim.lease, self.config.pre_dispatch_retry_ms)
                        .await?;
                    report.pre_dispatch_deferred =
                        report.pre_dispatch_deferred.saturating_add(1);
                    continue;
                }
            };
            let dispatch_digest = dispatch_attempt_digest(&claim.operation, claim.lease.fence);
            match self
                .store
                .dispatch_with_final_use(
                    claim,
                    self.authority,
                    &grant,
                    &binding,
                    dispatch_digest,
                    adapter,
                )
                .await
            {
                Ok(DispatchObservation::Terminal { .. }) => {
                    report.terminal = report.terminal.saturating_add(1);
                }
                Ok(DispatchObservation::Acknowledged { .. }) => {
                    report.acknowledged = report.acknowledged.saturating_add(1);
                }
                Ok(DispatchObservation::Indeterminate { .. }) => {
                    report.indeterminate = report.indeterminate.saturating_add(1);
                }
                Err(OperationError::AuthorityRejected)
                | Err(OperationError::Unavailable(_))
                | Err(OperationError::StaleGeneration)
                | Err(OperationError::StaleLease)
                | Err(OperationError::LeaseUnavailable) => {
                    report.pre_dispatch_deferred =
                        report.pre_dispatch_deferred.saturating_add(1);
                }
                Err(error) => return Err(error),
            }
        }
        Ok(report)
    }
}

pub fn dispatch_attempt_digest(operation: &DurableOperationRecord, fence: u64) -> Digest32 {
    let intent = &operation.intent;
    let mut bytes = Vec::with_capacity(192);
    bytes.extend_from_slice(b"hepta.kernel.operations.dispatch-attempt.v1\0");
    extend_len_prefixed(&mut bytes, intent.scope_id.as_str().as_bytes());
    extend_len_prefixed(&mut bytes, intent.operation_id.as_str().as_bytes());
    extend_len_prefixed(&mut bytes, intent.destination_id.as_str().as_bytes());
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(&intent.writer_generation.get().to_be_bytes());
    bytes.extend_from_slice(&fence.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn extend_len_prefixed(bytes: &mut Vec<u8>, value: &[u8]) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
}
