//! lease registry reconciliation implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    pub fn reconcile(
        &mut self,
        operation_id: &str,
        observation: ProviderLeaseObservationV1,
    ) -> Result<LeaseOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .operations
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.legacy_binding_incomplete {
            return Err(LeaseRegistryErrorV1::LegacyRequalificationRequired);
        }
        if matches!(
            current.state,
            LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
        ) {
            return if current.result_observation.as_ref() == Some(&observation) {
                Ok(current)
            } else {
                Err(LeaseRegistryErrorV1::ObservationMismatch)
            };
        }
        if observation == ProviderLeaseObservationV1::Unknown {
            return self.mark_unknown(operation_id);
        }
        let accepted_observation = observation.clone();
        let mut next = self.state.clone();
        match (&current.kind, observation) {
            (LeaseOperationKindV1::Issue, ProviderLeaseObservationV1::IssueApplied { lease }) => {
                validate_new_active_lease(&lease)?;
                if lease.issued_at_unix_ms < next.time_frontier_unix_ms {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                if next.leases.contains_key(&lease.lease_id) {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let lease_id = lease.lease_id.clone();
                let issued_at_unix_ms = lease.issued_at_unix_ms;
                let generation = lease.generation;
                next.leases.insert(lease_id.clone(), lease);
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.lease_id = Some(lease_id);
                operation.observed_at_unix_ms = Some(issued_at_unix_ms);
                operation.resulting_generation = Some(generation);
                operation.state = LeaseOperationStateV1::Applied;
            }
            (
                LeaseOperationKindV1::Renew,
                ProviderLeaseObservationV1::RenewApplied {
                    lease_id,
                    observed_at_unix_ms,
                    expires_at_unix_ms,
                    renewable,
                    provider_metadata_sha256,
                },
            ) => {
                if current.lease_id.as_deref() != Some(lease_id.as_str())
                    || provider_metadata_sha256 == [0; 32]
                    || expires_at_unix_ms <= observed_at_unix_ms
                    || has_pending_kind(
                        &next,
                        &lease_id,
                        LeaseOperationKindV1::Revoke,
                        Some(operation_id),
                    )
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let latest_observed = latest_observed_at(&next, &lease_id, Some(operation_id));
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                if current.expected_generation != Some(lease.generation)
                    || !matches!(
                        lease.state,
                        SecretLeaseStateV1::Active | SecretLeaseStateV1::RenewUnknown
                    )
                    || observed_at_unix_ms < lease.issued_at_unix_ms
                    || observed_at_unix_ms < next.time_frontier_unix_ms
                    || latest_observed.is_some_and(|latest| observed_at_unix_ms <= latest)
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let resulting_generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.expires_at_unix_ms = expires_at_unix_ms;
                lease.renewable = renewable;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.generation = resulting_generation;
                lease.state = SecretLeaseStateV1::Active;
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.observed_at_unix_ms = Some(observed_at_unix_ms);
                operation.resulting_generation = Some(resulting_generation);
                operation.state = LeaseOperationStateV1::Applied;
            }
            (
                LeaseOperationKindV1::Revoke,
                ProviderLeaseObservationV1::RevokeApplied {
                    lease_id,
                    observed_at_unix_ms,
                    provider_metadata_sha256,
                },
            ) => {
                if current.lease_id.as_deref() != Some(lease_id.as_str())
                    || provider_metadata_sha256 == [0; 32]
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let latest_observed = latest_observed_at(&next, &lease_id, Some(operation_id));
                let lease = next
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
                if current.expected_generation != Some(lease.generation)
                    || matches!(
                        lease.state,
                        SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
                    )
                    || observed_at_unix_ms < lease.issued_at_unix_ms
                    || observed_at_unix_ms < next.time_frontier_unix_ms
                    || latest_observed.is_some_and(|latest| observed_at_unix_ms <= latest)
                {
                    return Err(LeaseRegistryErrorV1::ObservationMismatch);
                }
                let resulting_generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.provider_metadata_sha256 = provider_metadata_sha256;
                lease.renewable = false;
                lease.generation = resulting_generation;
                lease.state = SecretLeaseStateV1::Revoked;
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.observed_at_unix_ms = Some(observed_at_unix_ms);
                operation.resulting_generation = Some(resulting_generation);
                operation.state = LeaseOperationStateV1::Applied;
            }
            (_, ProviderLeaseObservationV1::Denied | ProviderLeaseObservationV1::NotApplied) => {
                let operation = next
                    .operations
                    .get_mut(operation_id)
                    .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
                operation.state = LeaseOperationStateV1::Denied;
                restore_after_negative_observation(&mut next, &current)?;
            }
            _ => return Err(LeaseRegistryErrorV1::ObservationMismatch),
        }
        let result_lease = next
            .operations
            .get(operation_id)
            .and_then(|operation| operation.lease_id.as_deref())
            .and_then(|lease_id| next.leases.get(lease_id))
            .cloned();
        let operation = next
            .operations
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        operation.result_lease = result_lease;
        operation.result_observation = Some(accepted_observation);
        self.commit(next, 0)?;
        self.operation(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub fn expire_at(&mut self, now_unix_ms: u64) -> Result<usize, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if now_unix_ms < self.state.time_frontier_unix_ms {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        next.time_frontier_unix_ms = now_unix_ms;
        let mut changed = 0usize;
        for lease in next.leases.values_mut() {
            if !matches!(
                lease.state,
                SecretLeaseStateV1::Revoked | SecretLeaseStateV1::Expired
            ) && now_unix_ms >= lease.expires_at_unix_ms
            {
                lease.generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
                lease.renewable = false;
                lease.state = SecretLeaseStateV1::Expired;
                changed += 1;
            }
        }
        if changed != 0 || now_unix_ms != self.state.time_frontier_unix_ms {
            self.commit(next, 0)?;
        }
        Ok(changed)
    }
}
