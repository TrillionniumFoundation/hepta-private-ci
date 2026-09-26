//! Idempotent entry points for time-dependent durable owner operations.
//!
//! Capacity observation and expiry reconciliation depend on owner time. A retry
//! after an indeterminate commit must therefore look up the durable operation
//! ID before observing the clock or host again.

use crate::DurableFleetError;
use crate::DurableFleetMutationReceiptV1;
use crate::DurableFleetOwner;
use crate::FleetCapacityObserverV1;
use crate::FleetOperationKindV1;

pub fn refresh_capacity_idempotent<O: FleetCapacityObserverV1>(
    owner: &mut DurableFleetOwner,
    operation_id: &str,
    observer: &O,
) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
    if let Some(receipt) = retained_operation(owner, operation_id)? {
        require_kind(
            operation_id,
            &receipt,
            FleetOperationKindV1::CapacityObservation,
        )?;
        return Ok(receipt);
    }
    owner.refresh_capacity(operation_id, observer)
}

pub fn reconcile_expired_idempotent(
    owner: &mut DurableFleetOwner,
    operation_id: &str,
) -> Result<DurableFleetMutationReceiptV1, DurableFleetError> {
    if let Some(receipt) = retained_operation(owner, operation_id)? {
        require_kind(
            operation_id,
            &receipt,
            FleetOperationKindV1::ExpiryReconciliation,
        )?;
        return Ok(receipt);
    }
    owner.reconcile_expired(operation_id)
}

fn retained_operation(
    owner: &mut DurableFleetOwner,
    operation_id: &str,
) -> Result<Option<DurableFleetMutationReceiptV1>, DurableFleetError> {
    validate_operation_id(operation_id)?;
    owner.metrics()?;
    let Some(operation) = owner
        .state()
        .fleet_operation_receipts
        .iter()
        .find(|candidate| candidate.operation_id == operation_id)
        .cloned()
    else {
        return Ok(None);
    };
    Ok(Some(DurableFleetMutationReceiptV1 {
        generation: operation.committed_generation,
        state_sha256: owner.state().content_sha256.clone(),
        operation,
    }))
}

fn require_kind(
    operation_id: &str,
    receipt: &DurableFleetMutationReceiptV1,
    expected: FleetOperationKindV1,
) -> Result<(), DurableFleetError> {
    if receipt.operation.operation_kind != expected {
        return Err(DurableFleetError::OperationConflict(
            operation_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_operation_id(value: &str) -> Result<(), DurableFleetError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(DurableFleetError::InvalidOperationId);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CAPACITY_OBSERVATION_SCHEMA_VERSION;
    use crate::CapacityObservationError;
    use crate::FleetClock;
    use crate::FleetClockError;
    use crate::ResourceVectorV1;
    use crate::TrustedCapacityObservationV1;
    use std::sync::Arc;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    #[derive(Debug)]
    struct ManualClock(AtomicU64);

    impl ManualClock {
        fn set(&self, now_ms: u64) {
            self.0.store(now_ms, Ordering::SeqCst);
        }
    }

    impl FleetClock for ManualClock {
        fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }

    #[derive(Debug)]
    struct ClockObserver(Arc<ManualClock>);

    impl FleetCapacityObserverV1 for ClockObserver {
        fn observe(
            &self,
            _now_ms: u64,
        ) -> Result<TrustedCapacityObservationV1, CapacityObservationError> {
            let now_ms = self
                .0
                .now_unix_ms()
                .map_err(|_| CapacityObservationError::InvalidObservation)?;
            Ok(TrustedCapacityObservationV1 {
                schema_version: CAPACITY_OBSERVATION_SCHEMA_VERSION,
                observer_id: "command-port-test".into(),
                host_id: "host-one".into(),
                failure_domain_id: "rack-one".into(),
                host_generation: 1,
                observed_at_ms: now_ms,
                valid_until_ms: now_ms + 10_000,
                memory_pressure_basis_points: 0,
                capacity: ResourceVectorV1::physical(1_000, 1 << 20, 0),
            })
        }
    }

    #[test]
    fn retry_returns_committed_capacity_operation_before_reobserving_time() {
        let directory = tempfile::tempdir().expect("tempdir");
        let state_root = directory.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let clock = Arc::new(ManualClock(AtomicU64::new(1_000)));
        let observer = ClockObserver(Arc::clone(&clock));
        let mut owner = DurableFleetOwner::open_supervisor_state_root(
            &state_root,
            clock.clone(),
        )
        .expect("owner");
        let first = refresh_capacity_idempotent(
            &mut owner,
            "capacity-operation",
            &observer,
        )
        .expect("first refresh");
        clock.set(2_000);
        let retry = refresh_capacity_idempotent(
            &mut owner,
            "capacity-operation",
            &observer,
        )
        .expect("idempotent retry");
        assert_eq!(retry.generation, first.generation);
        assert_eq!(retry.operation.operation_digest, first.operation.operation_digest);
    }
}
