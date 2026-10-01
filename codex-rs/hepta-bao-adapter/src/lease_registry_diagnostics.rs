//! lease registry diagnostics implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    /// Process-local storage cost and recovery diagnostics. No secret digest or
    /// provider credential is exposed by this snapshot.
    pub fn diagnostics(&self) -> Result<LeaseRegistryDiagnosticsV1, LeaseRegistryErrorV1> {
        let encoded_bytes = serde_json::to_vec(&self.state)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?
            .len();
        let (lease_future_reserve_bytes, consumption_future_reserve_bytes) =
            future_reserve_bytes(&self.state)?;
        let required = encoded_bytes
            .saturating_add(lease_future_reserve_bytes)
            .saturating_add(consumption_future_reserve_bytes);
        let mut consumption_by_state = BTreeMap::new();
        let mut pending_by_recovery_action = BTreeMap::new();
        let mut pending_quota_amount = 0u64;
        let mut post_dispatch_without_receipt = 0usize;
        let mut observer_pending = 0usize;
        let mut settlement_pending = 0usize;
        let mut oldest_pending_revision = None::<u64>;
        for row in self.state.consumptions.values() {
            *consumption_by_state.entry(row.state).or_insert(0) += 1;
            if !row.state.is_terminal() {
                let recovery = row.state.recovery_action();
                *pending_by_recovery_action.entry(recovery).or_insert(0) += 1;
                if row.reservation_id.is_some() {
                    pending_quota_amount = pending_quota_amount.saturating_add(row.amount);
                }
                if row.state.has_dispatch_fence() && row.receipt.is_none() {
                    post_dispatch_without_receipt = post_dispatch_without_receipt.saturating_add(1);
                }
                if recovery == BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome
                    && row.receipt.is_some()
                {
                    observer_pending = observer_pending.saturating_add(1);
                }
                if recovery == BaoConsumptionRecoveryActionV1::SettleTerminalEvidence {
                    settlement_pending = settlement_pending.saturating_add(1);
                }
                let created = if row.created_revision == 0 {
                    self.state.revision
                } else {
                    row.created_revision
                };
                oldest_pending_revision = Some(
                    oldest_pending_revision
                        .map(|current| current.min(created))
                        .unwrap_or(created),
                );
            }
        }
        Ok(LeaseRegistryDiagnosticsV1 {
            schema_version: self.state.schema_version,
            revision: self.state.revision,
            lease_operation_count: self.state.operations.len(),
            lease_count: self.state.leases.len(),
            consumption_count: self.state.consumptions.len(),
            consumption_by_state,
            pending_by_recovery_action,
            pending_quota_amount,
            post_dispatch_without_receipt,
            observer_pending,
            settlement_pending,
            oldest_pending_age_revisions: oldest_pending_revision
                .map(|revision| self.state.revision.saturating_sub(revision))
                .unwrap_or(0),
            encoded_bytes,
            lease_future_reserve_bytes,
            consumption_future_reserve_bytes,
            max_store_bytes: MAX_STORE_BYTES,
            available_bytes: MAX_STORE_BYTES.saturating_sub(required),
            fenced: self.fenced,
            commit_metrics: self.runtime_metrics.snapshot(),
        })
    }

    /// Immutable, metadata-only export used for one-time migration into the
    /// transactional owner. Map ordering is canonical; no provider token or
    /// secret value can enter this snapshot.
    pub fn migration_snapshot(
        &self,
    ) -> Result<LeaseRegistryMigrationSnapshotV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        validate_state(&self.state)?;
        Ok(LeaseRegistryMigrationSnapshotV1 {
            schema_version: self.state.schema_version,
            revision: self.state.revision,
            time_frontier_unix_ms: self.state.time_frontier_unix_ms,
            operations: self.state.operations.values().cloned().collect(),
            leases: self.state.leases.values().cloned().collect(),
            consumptions: self.state.consumptions.values().cloned().collect(),
        })
    }

    pub fn lease(&self, lease_id: &str) -> Option<&SecretLeaseMetadataV1> {
        self.state.leases.get(lease_id)
    }

    pub fn operation(&self, operation_id: &str) -> Option<&LeaseOperationV1> {
        self.state.operations.get(operation_id)
    }

    pub fn operation_result(
        &self,
        operation_id: &str,
    ) -> Result<LeaseOperationResultV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let operation = self
            .state
            .operations
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if operation.legacy_binding_incomplete {
            return Err(LeaseRegistryErrorV1::LegacyRequalificationRequired);
        }
        let lease = operation.result_lease.clone();
        Ok(LeaseOperationResultV1 { operation, lease })
    }
}
