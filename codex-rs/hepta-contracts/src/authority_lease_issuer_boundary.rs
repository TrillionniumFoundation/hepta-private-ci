//! Pinned issuer dependencies at the original bounded owner entry.
//! Pins are trusted local configuration, not transferable authorization.
use super::*;

impl AuthorityLeaseVerifier {
    /// Hold one live pinned issuer and one opaque same-owner token together.
    /// The issuer is loaded and checked from this original locked state, never
    /// from an earlier read or a peer-supplied lease clone. If the pin aliases
    /// the token, validate_live still requires the complete same current record.
    /// The callback must not reenter the registry and must check both deadlines
    /// after its own bounded local I/O before publishing a time-limited result.
    pub fn with_pinned_issuer_dispatch_boundary<T>(
        &self,
        issuer_pin: (&str, u64),
        token: LeaseVerifiedUseToken,
        expected: &AuthorityLeaseBinding,
        boundary: impl FnOnce(&AuthorityLease, &AuthorityLease, u64) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        self.pair_token_owner(&token, expected)?;
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let issuer = live_pinned_issuer(issuer_pin, &state, now)?;
        validate_live(&token.lease, &state, token.lease.revision, expected, now)?;
        let result = boundary(issuer, &token.lease, state.store_revision);
        drop(state);
        Ok(result)
    }

    /// Hold a live pinned issuer and the distinct writer/effect tokens under
    /// the same original fence. Both tokens must belong to this exact Arc.
    /// Only issuer/token aliasing is permitted; each complete record, revision,
    /// binding, epoch, revocation and deadline is checked at actual entry.
    pub fn with_pinned_issuer_joint_dispatch_boundary<T>(
        &self,
        issuer_pin: (&str, u64),
        first: (LeaseVerifiedUseToken, &AuthorityLeaseBinding),
        second: (LeaseVerifiedUseToken, &AuthorityLeaseBinding),
        boundary: impl FnOnce(&AuthorityLease, &AuthorityLease, &AuthorityLease, u64) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        let (first, expected_first) = first;
        let (second, expected_second) = second;
        self.pair_token_owner(&first, expected_first)?;
        self.pair_token_owner(&second, expected_second)?;
        if first.lease.lease_id == second.lease.lease_id {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let issuer = live_pinned_issuer(issuer_pin, &state, now)?;
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
        let result = boundary(issuer, &first.lease, &second.lease, state.store_revision);
        drop(state);
        Ok(result)
    }

    /// Administrative predecessor recovery may outlive a nonrevoked issuer
    /// lease. Require its exact retained revision or the original persisted
    /// pruned-expiry floor, with no revocation in this same locked epoch.
    /// Unknown absence, changed revisions and explicit revocation refuse.
    /// This permits no effect dispatch or live issuer observation by itself.
    pub fn with_retired_predecessor_for_pinned_issuer_boundary<T>(
        &self,
        issuer_pin: (&str, u64),
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
        unrevoked_pinned_issuer(issuer_pin, &state, now)?;
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
}

fn validate_pin((id, revision): (&str, u64)) -> Result<(), AuthorityLeaseError> {
    if !identifier(id) || revision == 0 {
        return Err(AuthorityLeaseError::InvalidLease);
    }
    Ok(())
}

fn live_pinned_issuer<'a>(
    pin: (&str, u64),
    state: &'a State,
    now: u64,
) -> Result<&'a AuthorityLease, AuthorityLeaseError> {
    validate_pin(pin)?;
    let issuer = state
        .leases
        .get(pin.0)
        .ok_or(AuthorityLeaseError::LeaseNotFound)?;
    validate_live(issuer, state, pin.1, &issuer.binding, now)?;
    Ok(issuer)
}

fn unrevoked_pinned_issuer(
    pin: (&str, u64),
    state: &State,
    now: u64,
) -> Result<(), AuthorityLeaseError> {
    validate_pin(pin)?;
    if state.revocations.contains_key(pin.0) {
        return Err(AuthorityLeaseError::Revoked);
    }
    match state.leases.get(pin.0) {
        Some(issuer) => {
            if issuer.authority_epoch != state.authority_epoch {
                return Err(AuthorityLeaseError::EpochMismatch);
            }
            if issuer.revision != pin.1 {
                return Err(AuthorityLeaseError::RevisionMismatch);
            }
            if now < issuer.issued_at_unix_ms {
                return Err(AuthorityLeaseError::NotYetValid);
            }
            Ok(())
        }
        // This map is populated only by the original bounded pruning of
        // expired, unrevoked leases. It is persisted in the registry frontier
        // and cleared on epoch advance; absence is never treated as retirement.
        None if state.retired_revisions.get(pin.0) == Some(&pin.1) => Ok(()),
        None => Err(AuthorityLeaseError::LeaseNotFound),
    }
}
