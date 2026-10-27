//! Same original owner revoke with an optional cumulative deadline; no callback.
use super::*;
use std::time::Instant;

pub(super) enum Deadline {
    Unbounded,
    Before(Instant),
}
impl Deadline {
    fn check(&self) -> Result<(), AuthorityLeaseError> {
        match self {
            Self::Before(end) if Instant::now() >= *end => Err(AuthorityLeaseError::Unavailable),
            Self::Unbounded | Self::Before(_) => Ok(()),
        }
    }
}

impl AuthorityLeaseRegistry {
    /// Owner-only original CAS with a cumulative monotonic deadline. Busy state
    /// is unavailable rather than waiting past the caller's live authorization.
    /// Once durable IO begins, timeout is Unknown, never evidence of no effect.
    pub fn revoke_before(
        &self,
        lease_id: &str,
        expected_revision: u64,
        reason_sha256: [u8; 32],
        before: Instant,
    ) -> Result<RevocationReceipt, AuthorityLeaseError> {
        selected(
            self,
            lease_id,
            expected_revision,
            reason_sha256,
            Deadline::Before(before),
        )
    }
}

pub(super) fn selected(
    registry: &AuthorityLeaseRegistry,
    lease_id: &str,
    expected_revision: u64,
    reason_sha256: [u8; 32],
    deadline: Deadline,
) -> Result<RevocationReceipt, AuthorityLeaseError> {
    if !identifier(lease_id) || reason_sha256 == [0; 32] {
        return Err(AuthorityLeaseError::InvalidRevocation);
    }
    deadline.check()?;
    let revoked_at_unix_ms = registry.0.clock.now_unix_ms().map_err(map_trust_error)?;
    if revoked_at_unix_ms == 0 {
        return Err(AuthorityLeaseError::InvalidRevocation);
    }
    deadline.check()?;
    let mut state = match deadline {
        Deadline::Unbounded => registry.lock_state()?,
        Deadline::Before(_) => {
            let state = registry
                .0
                .state
                .try_lock()
                .map_err(|_| AuthorityLeaseError::Unavailable)?;
            if state.failed {
                return Err(AuthorityLeaseError::Unavailable);
            }
            state
        }
    };
    deadline.check()?;
    if let Some(existing) = state.revocations.get(lease_id) {
        if existing.lease_revision == expected_revision.saturating_add(1)
            && existing.reason_sha256 == reason_sha256
        {
            return Ok(receipt(existing, expected_revision));
        }
        return Err(AuthorityLeaseError::Revoked);
    }
    if state.revocations.len() >= MAX_CAPABILITY_REVOCATIONS {
        return Err(AuthorityLeaseError::CapacityExceeded);
    }
    let current = state
        .leases
        .get(lease_id)
        .cloned()
        .ok_or(AuthorityLeaseError::LeaseNotFound)?;
    if current.revision != expected_revision {
        return Err(AuthorityLeaseError::RevisionMismatch);
    }
    let lease_revision = next_revision(current.revision)?;
    let mut next = state.clone();
    next.store_revision = next_revision(next.store_revision)?;
    let mut revoked_lease = current;
    revoked_lease.revision = lease_revision;
    next.leases.insert(lease_id.to_owned(), revoked_lease);
    let revocation = CapabilityRevocation {
        schema_version: LEASE_SCHEMA_VERSION,
        lease_id: lease_id.to_owned(),
        authority_epoch: next.authority_epoch,
        lease_revision,
        store_revision: next.store_revision,
        reason_sha256,
        revoked_at_unix_ms,
    };
    next.revocations
        .insert(lease_id.to_owned(), revocation.clone());
    deadline.check()?;
    registry.persist_or_fence(&mut state, next)?;
    deadline.check()?;
    Ok(receipt(&revocation, expected_revision))
}

#[cfg(all(test, unix))]
#[path = "authority_lease_revoke_tests.rs"]
mod tests;
