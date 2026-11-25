//! The paired enrollment is a fourth independently revocable original record.
use super::*;

impl AuthorityLeaseVerifier {
    /// Fence one original issuer, writer, paired effect and enrollment together.
    /// All four roles must be distinct. Each opaque token must belong to this
    /// exact registry Arc; serialized leases or tokens from an equal registry
    /// cannot substitute. The complete records, revocations and deadlines are
    /// checked under one original mutex and one fresh clock sample.
    ///
    /// The callback is only a bounded local boundary. It must not reenter this
    /// registry, await, invoke remote providers or treat the returned metadata
    /// as permission for a later material read. Publishing time-limited output
    /// also requires checking expiry after the callback's own bounded I/O.
    pub fn with_pinned_issuer_paired_dispatch_boundary<T>(
        &self,
        issuer_pin: (&str, u64),
        writer: (LeaseVerifiedUseToken, &AuthorityLeaseBinding),
        effect: (LeaseVerifiedUseToken, &AuthorityLeaseBinding),
        enrollment: (LeaseVerifiedUseToken, &AuthorityLeaseBinding),
        boundary: impl FnOnce(
            &AuthorityLease,
            &AuthorityLease,
            &AuthorityLease,
            &AuthorityLease,
            u64,
            u64,
        ) -> T,
    ) -> Result<T, AuthorityLeaseError> {
        let (writer, expected_writer) = writer;
        let (effect, expected_effect) = effect;
        let (enrollment, expected_enrollment) = enrollment;
        self.pair_token_owner(&writer, expected_writer)?;
        self.pair_token_owner(&effect, expected_effect)?;
        self.pair_token_owner(&enrollment, expected_enrollment)?;
        let ids = [
            issuer_pin.0,
            writer.lease.lease_id.as_str(),
            effect.lease.lease_id.as_str(),
            enrollment.lease.lease_id.as_str(),
        ];
        if ids.iter().enumerate().any(|(i, id)| ids[..i].contains(id)) {
            return Err(AuthorityLeaseError::BindingMismatch);
        }
        let state = self.lock_state()?;
        let now = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        let issuer = live_pinned_issuer(issuer_pin, &state, now)?;
        for (token, expected) in [
            (&writer, expected_writer),
            (&effect, expected_effect),
            (&enrollment, expected_enrollment),
        ] {
            validate_live(&token.lease, &state, token.lease.revision, expected, now)?;
        }
        let result = boundary(
            issuer,
            &writer.lease,
            &effect.lease,
            &enrollment.lease,
            now,
            state.store_revision,
        );
        drop(state);
        Ok(result)
    }
}
