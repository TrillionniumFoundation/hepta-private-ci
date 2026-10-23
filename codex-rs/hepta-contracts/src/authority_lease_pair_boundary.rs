//! Bounded same-owner entry and explicit predecessor retirement. No new ledger.
use super::*;

/// Non-authorizing facts about a complete original predecessor lease. They
/// describe the locked registry state; they are not a transferable capability.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityLeaseRetirement {
    /// The exact retained lease remains present, and its signed expiry passed.
    Expired,
    /// Only its revision advanced once, with the exact original revocation.
    Revoked,
    /// The original bounded expiry pruning retained its exact retired revision.
    PrunedExpired,
}

impl AuthorityLeaseVerifier {
    /// Enter one bounded local boundary requiring two distinct original leases.
    /// Both opaque tokens must originate from this exact owner Arc. The same
    /// mutex protects their complete current records, revocation and time check.
    /// The callback receives the actual full leases and global revision only as
    /// metadata. It MUST NOT reenter this registry, wait for remote execution,
    /// or treat those serializable values as a replacement capability. A caller
    /// publishing a time-limited result must also check expiry after its own I/O.
    pub fn with_joint_dispatch_boundary<T>(
        &self,
        first: LeaseVerifiedUseToken,
        expected_first: &AuthorityLeaseBinding,
        second: LeaseVerifiedUseToken,
        expected_second: &AuthorityLeaseBinding,
        boundary: impl FnOnce(&AuthorityLease, &AuthorityLease, u64) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        self.pair_token_owner(&first, expected_first)?;
        self.pair_token_owner(&second, expected_second)?;
        if first.lease.lease_id == second.lease.lease_id {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        validate_live(
            &first.lease,
            &state,
            first.lease.revision,
            expected_first,
            now,
        )?;
        validate_live(
            &second.lease,
            &state,
            second.lease.revision,
            expected_second,
            now,
        )?;
        let result = boundary(&first.lease, &second.lease, state.store_revision);
        drop(state);
        Ok(result)
    }

    /// Enter a trusted local successor boundary only after the exact old lease
    /// is known expired/revoked/pruned-expired in this same locked owner. The
    /// caller must independently authenticate that complete predecessor (e.g.
    /// strict verification of the retained canonical writer proof), enforce its
    /// publisher quiescence and CAS the exact old proof. This API alone grants
    /// no writer rotation, publisher adoption or epoch reset.
    ///
    /// Successor and predecessor use distinct registry IDs in the same epoch;
    /// the separate local durable writer lease may retain its original ID.
    /// Arbitrary missing leases, replacement revisions and epoch retirement are
    /// not inferred as expired. The callback MUST NOT reenter this registry.
    pub fn with_retired_predecessor_boundary<T>(
        &self,
        predecessor: &AuthorityLease,
        successor: LeaseVerifiedUseToken,
        expected_successor: &AuthorityLeaseBinding,
        boundary: impl FnOnce(&AuthorityLease, AuthorityLeaseRetirement, u64) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        predecessor.validate()?;
        self.pair_token_owner(&successor, expected_successor)?;
        if predecessor.lease_id == successor.lease.lease_id {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        validate_live(
            &successor.lease,
            &state,
            successor.lease.revision,
            expected_successor,
            now,
        )?;
        if predecessor.authority_epoch != state.authority_epoch {
            return Err(AuthorityLeaseError::EpochMismatch);
        }
        let retirement = retired_predecessor(predecessor, &state, now)?;
        let result = boundary(&successor.lease, retirement, state.store_revision);
        drop(state);
        Ok(result)
    }

    fn pair_token_owner(
        &self,
        token: &LeaseVerifiedUseToken,
        expected: &AuthorityLeaseBinding,
    ) -> Result<(), AuthorityLeaseError> {
        if !Arc::ptr_eq(&self.0, &token.owner) || &token.lease.binding != expected {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        Ok(())
    }
}

fn retired_predecessor(
    old: &AuthorityLease,
    state: &State,
    now: u64,
) -> Result<AuthorityLeaseRetirement, AuthorityLeaseError> {
    if let Some(revocation) = state.revocations.get(&old.lease_id) {
        let current = state
            .leases
            .get(&old.lease_id)
            .ok_or(AuthorityLeaseError::RevisionMismatch)?;
        let mut previous = current.clone();
        previous.revision = old.revision;
        if old.revision.checked_add(1) == Some(current.revision)
            && previous == *old
            && revocation.authority_epoch == state.authority_epoch
            && revocation.lease_revision == current.revision
        {
            return Ok(AuthorityLeaseRetirement::Revoked);
        }
        return Err(AuthorityLeaseError::RevisionMismatch);
    }
    if now < old.expires_at_unix_ms {
        return Err(AuthorityLeaseError::InvalidLease);
    }
    if state.leases.get(&old.lease_id) == Some(old) {
        return Ok(AuthorityLeaseRetirement::Expired);
    }
    if !state.leases.contains_key(&old.lease_id)
        && state.retired_revisions.get(&old.lease_id) == Some(&old.revision)
    {
        return Ok(AuthorityLeaseRetirement::PrunedExpired);
    }
    Err(AuthorityLeaseError::RevisionMismatch)
}

#[cfg(test)]
#[path = "authority_lease_pair_boundary_tests.rs"]
mod tests;
