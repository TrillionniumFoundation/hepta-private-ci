//! lease registry pending implementation.

use super::*;

pub(super) fn new_operation(
    operation_id: String,
    kind: LeaseOperationKindV1,
    semantic_sha256: [u8; 32],
    lease_id: Option<String>,
    expected_generation: Option<u64>,
) -> LeaseOperationV1 {
    LeaseOperationV1 {
        operation_id,
        kind,
        semantic_sha256,
        lease_id,
        expected_generation,
        observed_at_unix_ms: None,
        resulting_generation: None,
        legacy_binding_incomplete: false,
        result_lease: None,
        result_observation: None,
        state: LeaseOperationStateV1::Prepared,
    }
}

pub(super) fn restore_after_negative_observation(
    state: &mut StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    let Some(lease_id) = operation.lease_id.as_deref() else {
        return Ok(());
    };
    let has_unknown_renew = has_pending_kind(
        state,
        lease_id,
        LeaseOperationKindV1::Renew,
        Some(&operation.operation_id),
    );
    let has_unknown_revoke = has_pending_kind(
        state,
        lease_id,
        LeaseOperationKindV1::Revoke,
        Some(&operation.operation_id),
    );
    let lease = state
        .leases
        .get_mut(lease_id)
        .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
    if matches!(
        lease.state,
        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
    ) {
        return Ok(());
    }
    match operation.kind {
        LeaseOperationKindV1::Issue => {}
        LeaseOperationKindV1::Renew => {
            if lease.state == SecretLeaseStateV1::RenewUnknown && !has_unknown_revoke {
                lease.state = SecretLeaseStateV1::Active;
            }
        }
        LeaseOperationKindV1::Revoke => {
            if lease.state == SecretLeaseStateV1::RevokeUnknown {
                lease.state = if has_unknown_renew {
                    SecretLeaseStateV1::RenewUnknown
                } else {
                    SecretLeaseStateV1::Active
                };
            }
        }
    }
    Ok(())
}

pub(super) fn latest_observed_at(
    state: &StoredRegistryV1,
    lease_id: &str,
    excluded_operation_id: Option<&str>,
) -> Option<u64> {
    state
        .operations
        .values()
        .filter(|operation| {
            excluded_operation_id != Some(operation.operation_id.as_str())
                && operation.lease_id.as_deref() == Some(lease_id)
                && operation.state == LeaseOperationStateV1::Applied
        })
        .filter_map(|operation| operation.observed_at_unix_ms)
        .max()
}

pub(super) fn has_pending_mutation(
    state: &StoredRegistryV1,
    lease_id: &str,
    excluded_operation_id: Option<&str>,
) -> bool {
    state.operations.values().any(|operation| {
        excluded_operation_id != Some(operation.operation_id.as_str())
            && operation.lease_id.as_deref() == Some(lease_id)
            && matches!(
                operation.kind,
                LeaseOperationKindV1::Renew | LeaseOperationKindV1::Revoke
            )
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
    })
}

pub(super) fn has_pending_kind(
    state: &StoredRegistryV1,
    lease_id: &str,
    kind: LeaseOperationKindV1,
    excluded_operation_id: Option<&str>,
) -> bool {
    state.operations.values().any(|operation| {
        excluded_operation_id != Some(operation.operation_id.as_str())
            && operation.lease_id.as_deref() == Some(lease_id)
            && operation.kind == kind
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
    })
}

pub(super) fn ensure_operation_capacity(
    state: &StoredRegistryV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if state.operations.len() >= MAX_RECORDS {
        Err(LeaseRegistryErrorV1::CapacityExceeded)
    } else {
        Ok(())
    }
}
