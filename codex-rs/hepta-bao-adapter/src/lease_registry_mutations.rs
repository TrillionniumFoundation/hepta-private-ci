//! lease registry mutations implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    pub fn prepare_issue(
        &mut self,
        operation_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.validate_operation_identity(&operation_id, semantic_sha256, None)?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Issue,
            semantic_sha256,
            None,
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;

        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Issue,
            semantic_sha256,
            None,
            None,
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        let pending_issues = next
            .operations
            .values()
            .filter(|candidate| {
                candidate.kind == LeaseOperationKindV1::Issue
                    && matches!(
                        candidate.state,
                        LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
                    )
            })
            .count();
        let issue_reserve = pending_issues
            .checked_mul(MAX_METADATA_BYTES)
            .and_then(|value| value.checked_add(CONTROL_RESERVE_BYTES))
            .ok_or(LeaseRegistryErrorV1::CapacityExceeded)?;
        self.commit(next, issue_reserve)?;
        Ok(operation)
    }

    pub fn prepare_renew(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.validate_operation_identity(&operation_id, semantic_sha256, Some(&lease_id))?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Renew,
            semantic_sha256,
            Some(&lease_id),
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;
        let lease = self
            .state
            .leases
            .get(&lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if lease.state != SecretLeaseStateV1::Active || !lease.renewable {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        if has_pending_mutation(&self.state, &lease_id, None) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Renew,
            semantic_sha256,
            Some(lease_id),
            Some(lease.generation),
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        self.commit(next, CONTROL_RESERVE_BYTES)?;
        Ok(operation)
    }

    pub fn prepare_revoke(
        &mut self,
        operation_id: String,
        lease_id: String,
        semantic_sha256: [u8; 32],
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.validate_operation_identity(&operation_id, semantic_sha256, Some(&lease_id))?;
        if let Some(existing) = self.matching_existing(
            &operation_id,
            LeaseOperationKindV1::Revoke,
            semantic_sha256,
            Some(&lease_id),
        )? {
            return Ok(existing);
        }
        self.ensure_writable()?;
        let lease = self
            .state
            .leases
            .get(&lease_id)
            .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
        if matches!(
            lease.state,
            SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
        ) || has_pending_kind(&self.state, &lease_id, LeaseOperationKindV1::Revoke, None)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let operation = new_operation(
            operation_id.clone(),
            LeaseOperationKindV1::Revoke,
            semantic_sha256,
            Some(lease_id),
            Some(lease.generation),
        );
        let mut next = self.state.clone();
        ensure_operation_capacity(&next)?;
        next.operations.insert(operation_id, operation.clone());
        self.commit(next, 0)?;
        Ok(operation)
    }

    pub fn mark_unknown(
        &mut self,
        operation_id: &str,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .operations
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if !matches!(
            current.state,
            LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
        ) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }

        let mut next = self.state.clone();
        if let Some(lease_id) = current.lease_id.as_deref() {
            let lease = next
                .leases
                .get_mut(lease_id)
                .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
            if current
                .expected_generation
                .is_some_and(|expected| expected != lease.generation)
                && !matches!(
                    lease.state,
                    SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                )
            {
                return Err(LeaseRegistryErrorV1::ObservationMismatch);
            }
            match current.kind {
                LeaseOperationKindV1::Issue => {}
                LeaseOperationKindV1::Renew => {
                    if lease.state == SecretLeaseStateV1::Active {
                        lease.state = SecretLeaseStateV1::RenewUnknown;
                    }
                }
                LeaseOperationKindV1::Revoke => {
                    if !matches!(
                        lease.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    ) {
                        lease.state = SecretLeaseStateV1::RevokeUnknown;
                    }
                }
            }
        }
        let operation = next
            .operations
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        operation.state = LeaseOperationStateV1::Unknown;
        self.commit(next, 0)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub(super) fn validate_operation_identity(
        &self,
        operation_id: &str,
        semantic_sha256: [u8; 32],
        lease_id: Option<&str>,
    ) -> Result<(), LeaseRegistryErrorV1> {
        if self.state.consumptions.contains_key(operation_id) {
            return Err(LeaseRegistryErrorV1::OperationConflict);
        }
        if !identifier(operation_id)
            || semantic_sha256 == [0; 32]
            || lease_id.is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        Ok(())
    }

    pub(super) fn matching_existing(
        &self,
        operation_id: &str,
        kind: LeaseOperationKindV1,
        semantic_sha256: [u8; 32],
        lease_id: Option<&str>,
    ) -> Result<Option<LeaseOperationV1>, LeaseRegistryErrorV1> {
        let Some(existing) = self.state.operations.get(operation_id) else {
            return Ok(None);
        };
        if existing.kind == kind
            && existing.semantic_sha256 == semantic_sha256
            && (kind == LeaseOperationKindV1::Issue || existing.lease_id.as_deref() == lease_id)
        {
            Ok(Some(existing.clone()))
        } else {
            Err(LeaseRegistryErrorV1::OperationConflict)
        }
    }
}
