//! Bounded original-owner observation for explicit administrative retirement.
//! No lease, revocation, epoch or dispatch token is created or changed here.

use super::*;

/// Complete original principal selection at one locked revision and actual
/// clock sample. This serializable metadata is not a transferable capability.
/// Expired, revoked and already-pruned historical rows are not active work.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AuthorityLeaseUnretiredReadV1 {
    pub principal_id: String,
    pub store_revision: u64,
    pub observed_unix_ms: u64,
    pub leases: Vec<AuthorityLease>,
}

impl AuthorityLeaseRegistry {
    /// Read ALL not-yet-retired leases for one principal, or fail if the exact
    /// result exceeds the caller's bound. Not-yet-valid leases are included:
    /// they can become live later and must not escape administrative retirement.
    ///
    /// This method exists only on the original administrative owner, not its
    /// read/verification handle. A caller still uses original revision-checked
    /// revoke for each selected lease, must not revoke a newly admitted current
    /// session, and must observe the complete remaining set before claiming
    /// completion. This snapshot cannot fence later concurrent mutations.
    pub fn read_unretired_for_principal(
        &self,
        principal_id: &str,
        max_to_read: usize,
    ) -> Result<AuthorityLeaseUnretiredReadV1, AuthorityLeaseError> {
        if !identifier(principal_id) || !(1..=MAX_AUTHORITY_LEASES).contains(&max_to_read) {
            return Err(AuthorityLeaseError::InvalidLease);
        }
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let mut leases = Vec::new();
        for lease in state.leases.values() {
            if lease.binding.principal_id != principal_id
                || state.revocations.contains_key(&lease.lease_id)
                || now >= lease.expires_at_unix_ms
            {
                continue;
            }
            // Inspect the whole matching set. Never return a successful
            // truncated prefix as if every original lease had been observed.
            if leases.len() == max_to_read {
                return Err(AuthorityLeaseError::CapacityExceeded);
            }
            leases.push(lease.clone());
        }
        Ok(AuthorityLeaseUnretiredReadV1 {
            principal_id: principal_id.into(),
            store_revision: state.store_revision,
            observed_unix_ms: now,
            leases,
        })
    }
}

#[cfg(all(test, unix))]
#[path = "authority_lease_admin_read_tests.rs"]
mod tests;
