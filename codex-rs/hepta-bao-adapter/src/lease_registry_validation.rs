//! lease registry validation implementation.

use super::*;

pub(super) fn migrate_state(
    mut state: StoredRegistryV1,
) -> Result<StoredRegistryV1, LeaseRegistryErrorV1> {
    if state.schema_version == SCHEMA_VERSION {
        return Ok(state);
    }
    if !matches!(
        state.schema_version,
        LEGACY_SCHEMA_VERSION | INTERMEDIATE_SCHEMA_VERSION | PREVIOUS_SCHEMA_VERSION
    ) {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    let source_schema = state.schema_version;
    state.revision = state.revision.max(1);
    if source_schema != PREVIOUS_SCHEMA_VERSION {
        for operation in state.operations.values_mut() {
            // An old mutable lease row is not the original operation result. Neither
            // a singleton nor the current generation proves a lost historical fact.
            if matches!(
                operation.state,
                LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
            ) || (operation.kind != LeaseOperationKindV1::Issue
                && operation.expected_generation.is_none())
            {
                operation.legacy_binding_incomplete = true;
            }
        }
    }
    consumption::migrate_schema_three_consumptions(&mut state.consumptions, state.revision)?;
    state.schema_version = SCHEMA_VERSION;
    Ok(state)
}

pub(super) fn validate_state(state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    if state.schema_version != SCHEMA_VERSION
        || state.revision == 0
        || state.operations.len() > MAX_RECORDS
        || state.leases.len() > MAX_RECORDS
        || state.consumptions.len() > MAX_RECORDS
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }

    for (id, lease) in &state.leases {
        if id != &lease.lease_id {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        validate_persisted_lease(lease).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
    }

    for (id, row) in &state.consumptions {
        if id != &row.operation_id
            || state.operations.contains_key(id)
            || row.created_revision == 0
            || row.updated_revision < row.created_revision
            || row.updated_revision > state.revision
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        consumption::validate_consumption(row)?;
    }
    let mut pending_renew = BTreeMap::<&str, usize>::new();
    let mut pending_revoke = BTreeMap::<&str, usize>::new();
    for (id, operation) in &state.operations {
        if id != &operation.operation_id
            || !identifier(id)
            || operation.semantic_sha256 == [0; 32]
            || operation
                .lease_id
                .as_deref()
                .is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        validate_operation(state, operation)?;
        if !operation.legacy_binding_incomplete
            && matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
        {
            let Some(lease_id) = operation.lease_id.as_deref() else {
                continue;
            };
            let target = match operation.kind {
                LeaseOperationKindV1::Issue => continue,
                LeaseOperationKindV1::Renew => &mut pending_renew,
                LeaseOperationKindV1::Revoke => &mut pending_revoke,
            };
            let count = target.entry(lease_id).or_default();
            *count += 1;
            if *count > 1 {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
    }
    Ok(())
}

pub(super) fn validate_operation(
    state: &StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if operation.expected_generation == Some(0) || operation.resulting_generation == Some(0) {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if matches!(
        operation.result_observation.as_ref(),
        Some(
            ProviderLeaseObservationV1::IssueApplied { .. }
                | ProviderLeaseObservationV1::RenewApplied { .. }
                | ProviderLeaseObservationV1::RevokeApplied { .. }
        )
    ) && operation.state != LeaseOperationStateV1::Applied
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let Some(snapshot) = operation.result_lease.as_ref() {
        validate_persisted_lease(snapshot).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
        if operation.lease_id.as_deref() != Some(snapshot.lease_id.as_str())
            || operation
                .resulting_generation
                .is_some_and(|generation| generation != snapshot.generation)
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    if !operation.legacy_binding_incomplete {
        let terminal = matches!(
            operation.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        );
        if terminal != operation.result_observation.is_some()
            || (operation.state == LeaseOperationStateV1::Applied
                && operation.result_lease.is_none())
            || (!terminal && operation.result_lease.is_some())
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        match operation.result_observation.as_ref() {
            Some(ProviderLeaseObservationV1::IssueApplied { lease })
                if operation.kind != LeaseOperationKindV1::Issue
                    || operation.result_lease.as_ref() != Some(lease) =>
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            Some(ProviderLeaseObservationV1::IssueApplied { .. }) => {}
            Some(ProviderLeaseObservationV1::RenewApplied {
                lease_id,
                observed_at_unix_ms,
                expires_at_unix_ms,
                renewable,
                provider_metadata_sha256,
            }) => {
                let snapshot = operation
                    .result_lease
                    .as_ref()
                    .ok_or(LeaseRegistryErrorV1::CorruptState)?;
                if operation.kind != LeaseOperationKindV1::Renew
                    || snapshot.lease_id != *lease_id
                    || operation.observed_at_unix_ms != Some(*observed_at_unix_ms)
                    || snapshot.expires_at_unix_ms != *expires_at_unix_ms
                    || snapshot.renewable != *renewable
                    || snapshot.provider_metadata_sha256 != *provider_metadata_sha256
                    || snapshot.state != SecretLeaseStateV1::Active
                {
                    return Err(LeaseRegistryErrorV1::CorruptState);
                }
            }
            Some(ProviderLeaseObservationV1::RevokeApplied {
                lease_id,
                observed_at_unix_ms,
                provider_metadata_sha256,
            }) => {
                let snapshot = operation
                    .result_lease
                    .as_ref()
                    .ok_or(LeaseRegistryErrorV1::CorruptState)?;
                if operation.kind != LeaseOperationKindV1::Revoke
                    || snapshot.lease_id != *lease_id
                    || operation.observed_at_unix_ms != Some(*observed_at_unix_ms)
                    || snapshot.provider_metadata_sha256 != *provider_metadata_sha256
                    || snapshot.state != SecretLeaseStateV1::Revoked
                {
                    return Err(LeaseRegistryErrorV1::CorruptState);
                }
            }
            Some(ProviderLeaseObservationV1::Denied | ProviderLeaseObservationV1::NotApplied)
                if operation.state != LeaseOperationStateV1::Denied =>
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            Some(ProviderLeaseObservationV1::Denied | ProviderLeaseObservationV1::NotApplied) => {}
            Some(ProviderLeaseObservationV1::Unknown) => {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            None => {}
        }
    }
    match operation.kind {
        LeaseOperationKindV1::Issue => {
            if operation.expected_generation.is_some() {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            if operation.state == LeaseOperationStateV1::Applied
                && !operation.legacy_binding_incomplete
                && (operation.lease_id.is_none()
                    || operation.observed_at_unix_ms.is_none()
                    || operation.resulting_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
        LeaseOperationKindV1::Renew | LeaseOperationKindV1::Revoke => {
            if !operation.legacy_binding_incomplete
                && (operation.lease_id.is_none() || operation.expected_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
            if operation.state == LeaseOperationStateV1::Applied
                && !operation.legacy_binding_incomplete
                && (operation.observed_at_unix_ms.is_none()
                    || operation.resulting_generation.is_none())
            {
                return Err(LeaseRegistryErrorV1::CorruptState);
            }
        }
    }

    if matches!(
        operation.state,
        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
    ) && operation.resulting_generation.is_some()
        && !operation.legacy_binding_incomplete
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let (Some(expected), Some(resulting)) = (
        operation.expected_generation,
        operation.resulting_generation,
    ) && resulting <= expected
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let Some(lease_id) = operation.lease_id.as_deref() {
        let lease = state
            .leases
            .get(lease_id)
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        if operation
            .resulting_generation
            .is_some_and(|resulting| resulting > lease.generation)
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    Ok(())
}

pub(super) fn validate_new_active_lease(
    lease: &SecretLeaseMetadataV1,
) -> Result<(), LeaseRegistryErrorV1> {
    validate_persisted_lease(lease)?;
    if lease.state != SecretLeaseStateV1::Active || lease.generation != 1 {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}

pub(super) fn validate_persisted_lease(
    lease: &SecretLeaseMetadataV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if !identifier(&lease.lease_id)
        || !identifier(&lease.secret_reference_id)
        || !identifier(&lease.consumer_id)
        || lease.scope_sha256 == [0; 32]
        || lease.provider_metadata_sha256 == [0; 32]
        || lease.generation == 0
        || lease.expires_at_unix_ms <= lease.issued_at_unix_ms
    {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    let encoded = serde_json::to_vec(lease).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    if encoded.len() > MAX_METADATA_BYTES {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}
